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

import sqlite3

def get_pg_conn():
    return psycopg2.connect(POSTGRES_URL)

def get_sqlite_conn(db_name: str):
    sqlite_dir = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper"
    db_path = os.path.join(sqlite_dir, db_name)
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    return None

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
    # Check if Postgres is active
    pg_active = True
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alert_subscriptions (name, email, topics, jurisdiction, query)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (req.name, req.email, req.topics, req.jurisdiction, req.query)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Postgres alerts save failed, falling back to console: {e}")
        pg_active = False
        
    # Trigger immediate confirmation email asynchronously
    background_tasks.add_task(send_alert_email, req.email, req.name, req.topics)
    return {"status": "success", "message": "Alert subscription active."}

@app.post("/api/v1/chat")
async def chat_stream(req: ChatRequest):
    """
    Main conversational chat streaming endpoint.
    Performs hybrid SQL filter + pgvector cosine similarity, falling back to local SQLite if PG is offline.
    """
    jurisdiction, keywords = extract_intent(req.query)
    juris_clean = re.sub(r"[']?s$", "", jurisdiction.strip())
    
    use_sqlite = False
    conn_pg = None
    cur_pg = None
    
    try:
        conn_pg = get_pg_conn()
        cur_pg = conn_pg.cursor(cursor_factory=RealDictCursor)
        # Test connection
        cur_pg.execute("SELECT 1")
    except Exception as e:
        print(f"Postgres connection unavailable, routing query to local SQLite databases: {e}")
        use_sqlite = True

    context_lines = []
    citations = []
    correlations = []

    if not use_sqlite:
        try:
            # 1. Fetch data from DB based on lens (PostgreSQL)
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
                cur_pg.execute(q, params)
                for r in cur_pg.fetchall():
                    impact = f"${r['dollar_impact']:,}" if r['dollar_impact'] else "None"
                    context_lines.append(f"[SAO AUDIT] Agency: {r['jurisdiction']} | Report: {r['report_num']} | Category: {r['category']} | Impact: {impact} | Summary: {r['summary']}")
                    citations.append({"text": f"{r['jurisdiction']} Audit - {r['report_num']}", "url": f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber={r['report_num']}"})
                    
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
                cur_pg.execute(q, params)
                for r in cur_pg.fetchall():
                    impact = f"${r['dollar_amount']:,}" if r['dollar_amount'] else "None"
                    context_lines.append(f"[COUNCIL ACTION] Jurisdiction: {r['jurisdiction']} | Committee: {r['committee']} | Action: {r['key_action']} | Vendor: {r['vendor']} | Impact: {impact} | Vote: {r['vote_outcome']}")
                    citations.append({"text": f"{r['jurisdiction']} Action {r['event_id']}", "url": "https://portal.sao.wa.gov/"})

            # 2. Vector similarity searches to surface correlations
            query_emb = get_embedding(req.query)
            if query_emb:
                if req.lens in ["comprehensive", "audits"]:
                    cur_pg.execute(
                        "SELECT report_num, jurisdiction, category, summary, dollar_impact, (embedding <=> %s::vector) as distance FROM findings ORDER BY distance ASC LIMIT 2",
                        (query_emb,)
                    )
                    for r in cur_pg.fetchall():
                        correlations.append({
                            "jurisdiction": r["jurisdiction"],
                            "category": r["category"],
                            "summary": r["summary"],
                            "dollar_impact": r["dollar_impact"],
                            "source": "audit",
                            "similarity": float(1 - r["distance"])
                        })
                if req.lens in ["comprehensive", "council"]:
                    cur_pg.execute(
                        "SELECT event_id, jurisdiction, committee, key_action, vendor, dollar_amount, (embedding <=> %s::vector) as distance FROM merged_actions ORDER BY distance ASC LIMIT 2",
                        (query_emb,)
                    )
                    for r in cur_pg.fetchall():
                        correlations.append({
                            "jurisdiction": r["jurisdiction"],
                            "category": r["committee"] or "Council Action",
                            "summary": r["key_action"],
                            "dollar_impact": r["dollar_amount"],
                            "source": "council",
                            "similarity": float(1 - r["distance"])
                        })
            cur_pg.close()
            conn_pg.close()
        except Exception as pg_err:
            print("Postgres query failed, forcing SQLite fallback:", pg_err)
            use_sqlite = True

    if use_sqlite:
        # SQLite Query Fallback
        # 1. Fetch audits from both sao_audits.db and sao_2024.db
        if req.lens in ["comprehensive", "audits"]:
            for db_name in ["sao_audits.db", "sao_2024.db"]:
                conn_sao = get_sqlite_conn(db_name)
                if conn_sao:
                    try:
                        cur_sao = conn_sao.cursor()
                        q = "SELECT report_num, jurisdiction, category, summary, dollar_impact FROM findings WHERE 1=1"
                        params = []
                        if juris_clean:
                            q += " AND jurisdiction LIKE ?"
                            params.append(f"%{juris_clean}%")
                        if keywords:
                            kw_clauses = ["summary LIKE ?" for _ in keywords]
                            q += f" AND ({' OR '.join(kw_clauses)})"
                            params.extend([f"%{kw}%" for kw in keywords])
                        q += " LIMIT 5"
                        cur_sao.execute(q, params)
                        rows = [dict(row) for row in cur_sao.fetchall()]
                        for r in rows:
                            impact = f"${r['dollar_impact']:,}" if r['dollar_impact'] else "None"
                            context_lines.append(f"[SAO AUDIT] Agency: {r['jurisdiction']} | Report: {r['report_num']} | Category: {r['category']} | Impact: {impact} | Summary: {r['summary']}")
                            citations.append({"text": f"{r['jurisdiction']} Audit - {r['report_num']}", "url": f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber={r['report_num']}"})
                            
                            # Add correlation item
                            correlations.append({
                                "jurisdiction": r["jurisdiction"],
                                "category": r["category"],
                                "summary": r["summary"],
                                "dollar_impact": r["dollar_impact"],
                                "source": "audit",
                                "similarity": 0.85
                            })
                        conn_sao.close()
                    except Exception as e:
                        print(f"SQLite Audits Read Error for {db_name}:", e)

        # 2. Fetch council actions from municipal_intent.db (using processed_intent table)
        if req.lens in ["comprehensive", "council"]:
            conn_muni = get_sqlite_conn("municipal_intent.db")
            if conn_muni:
                try:
                    cur_muni = conn_muni.cursor()
                    q = "SELECT event_id, jurisdiction, doc_type as committee, meeting_date, agenda_item_title, key_action, vendor, dollar_amount, vote_outcome FROM processed_intent WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND jurisdiction LIKE ?"
                        params.append(f"%{juris_clean}%")
                    if keywords:
                        kw_clauses = ["(agenda_item_title LIKE ? OR key_action LIKE ?)" for _ in keywords]
                        q += f" AND ({' OR '.join(kw_clauses)})"
                        for kw in keywords:
                            params.extend([f"%{kw}%", f"%{kw}%"])
                    q += " LIMIT 5"
                    cur_muni.execute(q, params)
                    rows = [dict(row) for row in cur_muni.fetchall()]
                    for r in rows:
                        summary_text = f"{r['agenda_item_title']}: {r['key_action']}" if r['agenda_item_title'] else r['key_action']
                        impact = f"${r['dollar_amount']:,}" if r['dollar_amount'] else "None"
                        context_lines.append(f"[COUNCIL ACTION] Jurisdiction: {r['jurisdiction']} | Committee: {r['committee']} | Action: {summary_text} | Vendor: {r['vendor']} | Impact: {impact} | Vote: {r['vote_outcome']}")
                        citations.append({"text": f"{r['jurisdiction']} Action {r['event_id']}", "url": "https://portal.sao.wa.gov/"})
                        
                        # Add correlation item
                        correlations.append({
                            "jurisdiction": r["jurisdiction"],
                            "category": r["committee"] or "Council Action",
                            "summary": summary_text,
                            "dollar_impact": r["dollar_amount"],
                            "source": "council",
                            "similarity": 0.88
                        })
                    conn_muni.close()
                except Exception as e:
                    print("SQLite Municipal Read Error:", e)

    context_str = "\n".join(context_lines) if context_lines else "No direct matching database records found."
    
    # 3. Construct Synthesis Prompts
    system_prompt = f"""You are the PennerAI Civic Intelligence Agent. 
You provide deep, fact-based answers exploring Washington State policies and local governance.
Format your answer strictly in 2-3 readable paragraphs using markdown.

CONTEXT DATABASE RECORDS:
{context_str}
"""

    async def event_generator():
        # Default follow up suggestions
        suggestions = [
            f"Show other findings for {jurisdiction}" if jurisdiction else "Are there similar audit findings?",
            "What was the total dollar impact?",
            "How did city council vote on this?"
        ]
        
        if not GEMINI_API_KEY:
            # Fallback to Membrane client completions if key is missing
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
                    if line.startswith("data: "):
                        content = line[6:].strip()
                        if content == "[DONE]":
                            continue
                        try:
                            parsed = json.loads(content)
                            token = ""
                            if "choices" in parsed:
                                token = parsed["choices"][0]["delta"].get("content", "")
                            elif "chunk" in parsed:
                                token = parsed["chunk"]
                            
                            if token:
                                yield f"data: {json.dumps({'chunk': token})}\n\n"
                        except:
                            pass
                
            except Exception as e:
                yield f"data: {json.dumps({'chunk': f'Error rendering narrative: {e}'})}\n\n"
        else:
            # Main path: Direct Gemini 3.5 Flash call with live Google Search Grounding
            import requests
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:streamGenerateContent?key={GEMINI_API_KEY}"
            headers = {"Content-Type": "application/json"}
            
            prompt = f"""You are the PennerAI Civic Intelligence Agent.
Answer the user's question about Washington State local governance.
Rely on the provided CONTEXT DATABASE RECORDS for any specific local audits or council actions.
If the CONTEXT DATABASE RECORDS do not contain enough information to fully answer the user's question, use your search grounding tool to search the web for the latest factual information about Washington State cities, councils, and state laws.
State clearly which parts of your answer come from our verified audit/council database and which parts are from public search grounding.
Be factual, cite your sources, and do not hallucinate.

User Question: {req.query}
"""
            
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"googleSearch": {}}],
                "generationConfig": {
                    "temperature": 0.2
                },
                "systemInstruction": {
                    "parts": [{"text": system_prompt}]
                }
            }
            
            try:
                res = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
                res.raise_for_status()
                
                buffer = ""
                for chunk in res.iter_content(chunk_size=1024, decode_unicode=True):
                    if chunk:
                        buffer += chunk
                        while True:
                            start_idx = buffer.find("{")
                            if start_idx == -1:
                                break
                            
                            brace_count = 0
                            in_string = False
                            escape = False
                            end_idx = -1
                            
                            for idx in range(start_idx, len(buffer)):
                                char = buffer[idx]
                                if char == '"' and not escape:
                                    in_string = not in_string
                                elif char == '\\' and in_string:
                                    escape = not escape
                                    continue
                                elif not in_string:
                                    if char == '{':
                                        brace_count += 1
                                    elif char == '}':
                                        brace_count -= 1
                                        if brace_count == 0:
                                            end_idx = idx
                                            break
                                escape = False
                                
                            if end_idx != -1:
                                obj_str = buffer[start_idx:end_idx+1]
                                buffer = buffer[end_idx+1:]
                                try:
                                    parsed = json.loads(obj_str)
                                    candidate = parsed["candidates"][0]
                                    
                                    # Yield text token
                                    text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
                                    if text:
                                        yield f"data: {json.dumps({'chunk': text})}\n\n"
                                        
                                    # Extract grounding chunks (sources) if present
                                    metadata = candidate.get("groundingMetadata", {})
                                    if "groundingChunks" in metadata:
                                        for web_chunk in metadata["groundingChunks"]:
                                            if "web" in web_chunk:
                                                uri = web_chunk["web"].get("uri", "")
                                                title = web_chunk["web"].get("title", "")
                                                if uri and title:
                                                    # Deduplicate and add to citations list
                                                    if not any(c["url"] == uri for c in citations):
                                                        citations.append({"text": title, "url": uri})
                                except Exception as e:
                                    pass
                            else:
                                break
                                
            except Exception as e:
                yield f"data: {json.dumps({'chunk': f'Error contacting Gemini Grounded API: {e}'})}\n\n"
                
        # Unified citations merging logic (limit 4 DB findings and 6 web search sources)
        db_cits = [c for c in citations if "portal.sao.wa.gov" in c["url"]]
        web_cits = [c for c in citations if c not in db_cits]
        final_citations = db_cits[:4] + web_cits[:6]
        
        # Yield metadata event right before completion
        metadata_event = {
            "citations": final_citations,
            "suggestions": suggestions,
            "correlations": correlations
        }
        yield f"data: {json.dumps(metadata_event)}\n\n"
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
