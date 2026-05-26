import os
import sqlite3
import requests
import json
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/mrsc_knowledge.db"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MEMBRANE_API_KEY = os.environ.get("MEMBRANE_API_KEY", "")

def search_mrsc_knowledge(keyword: str):
    """Basic keyword search across the MRSC local database."""
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. Please run the crawler script first.")
        return []
        
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Search title and content for keywords
    cur.execute("""
        SELECT url, title, section, content_markdown 
        FROM mrsc_knowledge 
        WHERE title LIKE ? OR content_markdown LIKE ?
        LIMIT 2
    """, (f"%{keyword}%", f"%{keyword}%"))
    
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def generate_grounded_answer(query: str, mrsc_context_list: list):
    """Sends query + MRSC context to the LLM to get a grounded answer with citations."""
    if not mrsc_context_list:
        print("No MRSC context records found to ground the query.")
        return
        
    context_str = ""
    citations = []
    for idx, ctx in enumerate(mrsc_context_list, 1):
        # Clip content to prevent token overflow in test
        clipped_content = ctx["content_markdown"][:1500]
        context_str += f"[MRSC-{idx}] URL: {ctx['url']} | Title: {ctx['title']} | Content:\n{clipped_content}\n\n"
        citations.append({
            "label": f"[MRSC-{idx}]",
            "title": ctx["title"],
            "url": ctx["url"]
        })
        
    system_prompt = """You are the PennerAI Civic Intelligence Agent.
You answer questions about Washington State local government structure and policy.
Ground your response strictly in the provided MRSC CONTEXT.
At the end of sentences referencing facts from the context, include the exact citation label (e.g., [MRSC-1], [MRSC-2]).
Do not introduce conversational filler. Begin directly with the answer."""

    prompt = f"""User Question: {query}

MRSC CONTEXT:
{context_str}
"""

    # Try Gemini first, then fall back to Membrane
    if GEMINI_API_KEY:
        print("Querying Gemini 3.5 Flash with MRSC grounding...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"temperature": 0.1}
        }
        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code == 200:
                answer = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                print_grounded_result(answer, citations)
                return
            else:
                print(f"Gemini API returned status {r.status_code}: {r.text}")
        except Exception as e:
            print(f"Gemini API call failed: {e}")
            
    # Fallback to Membrane
    if MEMBRANE_API_KEY:
        print("Querying Membrane Engagement Layer with MRSC grounding...")
        url = "https://membrane-api.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {MEMBRANE_API_KEY}"
        }
        payload = {
            "model": "membrane-engagement-layer",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 200:
                answer = r.json()["choices"][0]["message"]["content"].strip()
                print_grounded_result(answer, citations)
                return
            else:
                print(f"Membrane API returned status {r.status_code}: {r.text}")
        except Exception as e:
            print(f"Membrane API call failed: {e}")

def print_grounded_result(answer: str, citations: list):
    print("\n================ GROUNDED ANSWER ================")
    print(answer)
    print("\n================ SOURCES CITED ================")
    for c in citations:
        print(f"{c['label']} {c['title']} - {c['url']}")
    print("=================================================\n")

if __name__ == "__main__":
    search_term = "special purpose district"
    user_query = "What is a special purpose district in Washington State, and how does it differ from a city?"
    
    print(f"Testing search for keyword: '{search_term}'...")
    results = search_mrsc_knowledge(search_term)
    if results:
        print(f"Found {len(results)} matching explore-topic pages.")
        for r in results:
            print(f" - Title: {r['title']} ({r['url']})")
        generate_grounded_answer(user_query, results)
    else:
        print("No matching MRSC pages found in database.")
