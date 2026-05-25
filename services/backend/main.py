import os
import json
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from dotenv import load_dotenv

# Import shared models and Membrane adapter
from packages.shared.shared_schemas import AlertSubscriptionSchema
from services.membrane import MembraneClient

load_dotenv()

app = FastAPI(title="PennerAI Governance Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:penner_secret_password_2026@localhost:5432/penner_governance_db"
)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Initialize the Membrane client
membrane = MembraneClient()

class ChatRequest(BaseModel):
    query: str
    lens: str = "comprehensive" # "comprehensive" | "audits" | "council"

class SynthesizeRequest(BaseModel):
    jurisdiction: str
    query: str

def get_pg_conn():
    return psycopg2.connect(POSTGRES_URL)

def get_embedding(text: str) -> Optional[List[float]]:
    """Get vector embedding (1536-dim padded) for query lookup."""
    if not GEMINI_API_KEY:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "models/text-embedding-004",
        "content": {"parts": [{"text": text[:2000]}]}
    }
    try:
        import requests
        res = requests.post(url, headers=headers, json=payload, timeout=5)
        if res.status_code == 200:
            embedding = res.json()["embedding"]["values"]
            if len(embedding) == 768:
                embedding.extend([0.0] * 768)
            return embedding[:1536]
    except Exception as e:
        print(f"Error fetching embedding for query: {e}")
    return None

def extract_intent(query_text: str) -> tuple:
    """Uses Membrane semantic gate capability to extract target entities."""
    prompt = """You are the Membrane Semantic Gate. Extract the target jurisdiction (e.g. City/County/School District) and 2-3 keywords. Return strict JSON: {"jurisdiction": "Name", "keywords": ["kw1", "kw2"]}"""
    try:
        res = membrane.chat_completion(
            model="membrane-engagement-layer",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query_text}
            ],
            response_format={"type": "json_object"}
        )
        content_str = res["choices"][0]["message"]["content"]
        parsed = json.loads(content_str)
        return parsed.get("jurisdiction", ""), parsed.get("keywords", [])
    except Exception as e:
        print(f"Membrane gate classification failed, using heuristic: {e}")
        
    # Heuristic fallback
    jurisdiction = ""
    keywords = []
    clean_query = query_text.lower()
    wa_cities = ["seattle", "tacoma", "bellevue", "spokane", "everett", "kent", "renton", "yakima", "olympia", "orting"]
    for city in wa_cities:
        if city in clean_query:
            jurisdiction = city.title()
            break
    return jurisdiction, keywords

def send_alert_email(email: str, name: str, topics: str):
    """Mocks sending a tracking confirmation alert."""
    print(f"📧 [ALERT EMAIL SENT] To: {email} | Recipient: {name} | Subject: PennerAI Active Monitor Set for '{topics}'")

@app.post("/api/v1/auth/assign")
async def register_alert(req: AlertSubscriptionSchema, background_tasks: BackgroundTasks):
    """Registers alert subscriptions inside the PostgreSQL database (lead capture)."""
    conn = get_pg_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO alert_subscriptions (name, email, topics, jurisdiction, query)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (req.name, req.email, req.topics, req.jurisdiction, req.query)
        )
        conn.commit()
        # Trigger immediate confirmation email asynchronously
        background_tasks.add_task(send_alert_email, req.email, req.name, req.topics)
        return {"status": "success", "message": "Alert subscription active."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database write failed: {e}")
    finally:
        cur.close()
        conn.close()

@app.post("/api/v1/chat")
async def chat_stream(req: ChatRequest):
    """
    Main conversational chat streaming endpoint.
    Performs hybrid SQL filter + pgvector cosine similarity, fanning out metadata.
    """
    jurisdiction, keywords = extract_intent(req.query)
    
    conn = get_pg_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Fetch data from DB based on lens
    context_lines = []
    citations = []
    
    # Clean jurisdiction string (strip possessives)
    juris_clean = re.sub(r"[']?s$", "", jurisdiction.strip())
    
    # Query findings
    if req.lens in ["comprehensive", "audits"]:
        q = "SELECT report_num, jurisdiction, category, summary, dollar_impact FROM findings WHERE 1=1"
        params = []
        if juris_clean:
            q += " AND jurisdiction ILIKE %s"
            params.append(f"%{juris_clean}%")
        if keywords:
            kw_clauses = ["summary ILIKE %s" for _ in keywords]
            q += f" AND ({' OR '.join(kw_clauses)})"
            params.extend([f"%{kw}%" for kw in keywords])
        q += " LIMIT 5"
        
        cur.execute(q, params)
        rows = cur.fetchall()
        for r in rows:
            impact = f"${r['dollar_impact']:,}" if r['dollar_impact'] else "None"
            context_lines.append(f"[SAO AUDIT] Agency: {r['jurisdiction']} | Report: {r['report_num']} | Category: {r['category']} | Impact: {impact} | Summary: {r['summary']}")
            citations.append({"text": f"{r['jurisdiction']} Audit - {r['report_num']}", "url": f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber={r['report_num']}"})
            
    # Query council actions
    if req.lens in ["comprehensive", "council"]:
        q = "SELECT event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount, vote_outcome FROM merged_actions WHERE 1=1"
        params = []
        if juris_clean:
            q += " AND jurisdiction ILIKE %s"
            params.append(f"%{juris_clean}%")
        if keywords:
            kw_clauses = ["key_action ILIKE %s" for _ in keywords]
            q += f" AND ({' OR '.join(kw_clauses)})"
            params.extend([f"%{kw}%" for kw in keywords])
        q += " LIMIT 5"
        
        cur.execute(q, params)
        rows = cur.fetchall()
        for r in rows:
            impact = f"${r['dollar_amount']:,}" if r['dollar_amount'] else "None"
            context_lines.append(f"[COUNCIL ACTION] Jurisdiction: {r['jurisdiction']} | Committee: {r['committee']} | Action: {r['key_action']} | Vendor: {r['vendor']} | Impact: {impact} | Vote: {r['vote_outcome']}")
            citations.append({"text": f"{r['jurisdiction']} Action {r['event_id']}", "url": "https://portal.sao.wa.gov/"})

    # 2. Vector similarity searches to surface correlations
    correlations = []
    query_emb = get_embedding(req.query)
    if query_emb:
        # Search audits
        if req.lens in ["comprehensive", "audits"]:
            cur.execute(
                """
                SELECT report_num, jurisdiction, category, summary, dollar_impact,
                (embedding <=> %s::vector) as distance
                FROM findings 
                ORDER BY distance ASC LIMIT 2
                """,
                (query_emb,)
            )
            for r in cur.fetchall():
                correlations.append({
                    "jurisdiction": r["jurisdiction"],
                    "category": r["category"],
                    "summary": r["summary"],
                    "dollar_impact": r["dollar_impact"],
                    "source": "audit",
                    "similarity": float(1 - r["distance"])
                })
        # Search council actions
        if req.lens in ["comprehensive", "council"]:
            cur.execute(
                """
                SELECT event_id, jurisdiction, committee, key_action, vendor, dollar_amount,
                (embedding <=> %s::vector) as distance
                FROM merged_actions 
                ORDER BY distance ASC LIMIT 2
                """,
                (query_emb,)
            )
            for r in cur.fetchall():
                correlations.append({
                    "jurisdiction": r["jurisdiction"],
                    "category": r["committee"] or "Council Action",
                    "summary": r["key_action"],
                    "dollar_impact": r["dollar_amount"],
                    "source": "council",
                    "similarity": float(1 - r["distance"])
                })

    cur.close()
    conn.close()

    context_str = "\n".join(context_lines) if context_lines else "No direct matching database records found."
    
    # 3. Construct Synthesis Prompts
    system_prompt = f"""You are the PennerAI Civic Intelligence Agent. 
You provide deep, fact-based answers exploring Washington State policies and local governance.
Format your answer strictly in 2-3 readable paragraphs using markdown.
Rely strictly on the provided context. If no records exist, answer dynamically but state that data records are empty.

CONTEXT DATABASE RECORDS:
{context_str}
"""

    async def event_generator():
        # Call the Membrane client chat completions
        # Default follow up suggestions
        suggestions = [
            f"Show other findings for {jurisdiction}" if jurisdiction else "Are there similar audit findings?",
            "What was the total dollar impact?",
            "How did city council vote on this?"
        ]
        
        try:
            stream = membrane.chat_completion(
                model="membrane-engagement-layer",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": req.query}
                ],
                stream=True
            )
            
            for line in stream:
                # Membrane streams standard SSE lines like 'data: {"choices": [{"delta": {"content": "..."}}]}'
                # Or local proxy streams simpler formats. We handle both.
                if line.startswith("data: "):
                    content = line[6:].strip()
                    if content == "[DONE]":
                        continue
                    try:
                        parsed = json.loads(content)
                        # Yield token content if present
                        token = ""
                        if "choices" in parsed:
                            token = parsed["choices"][0]["delta"].get("content", "")
                        elif "chunk" in parsed:
                            token = parsed["chunk"]
                        
                        if token:
                            yield f"data: {json.dumps({'chunk': token})}\n\n"
                    except:
                        pass
                        
            # Yield metadata event right before completion
            metadata_event = {
                "citations": citations[:4],
                "suggestions": suggestions,
                "correlations": correlations
            }
            yield f"data: {json.dumps(metadata_event)}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'chunk': f'Error rendering narrative: {e}'})}\n\n"
            
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/v1/oracle/synthesize")
async def synthesize(req: SynthesizeRequest):
    """Synthesis router compatible with original frontend specifications."""
    # Convert query into chat_stream format and return StreamingResponse
    chat_req = ChatRequest(query=f"{req.query} in {req.jurisdiction}", lens="comprehensive")
    return await chat_stream(chat_req)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
