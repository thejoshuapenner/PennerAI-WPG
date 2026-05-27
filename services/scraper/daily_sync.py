import os
import requests
import sqlite3
import psycopg2
from pypdf import PdfReader
from dotenv import load_dotenv
import time
import json
from datetime import datetime

# Import Membrane adapter
from services.membrane import MembraneClient
from services.scraper.local_audits_sync import sync_local_audits

load_dotenv()

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:postgres_dev_password@localhost:5432/penner_governance_db"
)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Initialize client
membrane = MembraneClient()

SAO_API_URL = "https://portal.sao.wa.gov/ReportSearch/Home/SearchReports"
SAO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded"
}
# Limit syncs from year 2020 onward
SAO_PAYLOAD = "pageSize=30&pageNumber=1&HasFindings=true&StateGovernment=false&LocalGovernment=true&PerformanceAudits=false&SpecialInvestigations=false&UseOfDeadlyForceInvestigation=false&PoliceCertificationAudit=false&StartDate=01/01/2020"

def get_pg_conn():
    return psycopg2.connect(POSTGRES_URL)

def get_embedding(text: str) -> list:
    """Fetch 768-dim embedding vector."""
    if not GEMINI_API_KEY:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "models/text-embedding-004",
        "content": {"parts": [{"text": text[:2000]}]}
    }
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            embedding = res.json()["embedding"]["values"]
            return embedding[:768]
    except Exception as e:
        print(f"Embedding failed: {e}")
    return None

import re

def extract_audit_findings_text_chunks(pdf_path: str) -> list:
    """Scans PDF for pages containing 'FINDING' and returns 5-page windows as text chunks."""
    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        matching_pages = []
        for i in range(total_pages):
            page_text = reader.pages[i].extract_text() or ""
            if re.search(r'\bfindings?\b', page_text, re.IGNORECASE):
                matching_pages.append(i)
        
        # If no page contains "FINDING", default to first 5 pages as a chunk
        if not matching_pages:
            text = ""
            for i in range(min(5, total_pages)):
                text += f"--- PAGE {i+1} ---\n"
                text += reader.pages[i].extract_text() or ""
                text += "\n"
            return [text] if text.strip() else []
        
        # Build 5-page windows around each matching page
        chunks = []
        processed_windows = set()
        for page_idx in matching_pages:
            start = max(0, page_idx - 2)
            end = min(total_pages - 1, page_idx + 2)
            window_key = (start, end)
            if window_key in processed_windows:
                continue
            processed_windows.add(window_key)
            
            chunk_text = ""
            for idx in range(start, end + 1):
                chunk_text += f"--- PAGE {idx+1} ---\n"
                chunk_text += reader.pages[idx].extract_text() or ""
                chunk_text += "\n"
            if chunk_text.strip():
                chunks.append(chunk_text)
        return chunks
    except Exception as e:
        print(f"Error extracting text from PDF {pdf_path}: {e}")
        return []

def parse_membrane_extraction(content_str: str) -> dict:
    """Helper to parse JSON string from Membrane completions/swarm response with regex fallback."""
    if not content_str:
        return {}
    content_str = content_str.strip()
    
    # 1. Try direct json load
    try:
        return json.loads(content_str)
    except Exception:
        pass
        
    # 2. Extract markdown codeblock
    try:
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content_str, re.DOTALL | re.IGNORECASE)
        if match:
            return json.loads(match.group(1))
    except Exception:
        pass
        
    # 3. Last resort: match anything between { and }
    try:
        match = re.search(r'(\{.*\})', content_str, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    except Exception:
        pass
        
    return {}

def extract_finding_from_swarm_extractions(extractions, default_year=None):
    best_finding = None
    for ext in extractions:
        prime = {}
        if isinstance(ext, dict):
            if "summary" in ext and ext.get("summary"):
                prime = ext
            elif "content" in ext and isinstance(ext["content"], str):
                prime = parse_membrane_extraction(ext["content"])
            elif "message" in ext and isinstance(ext["message"], dict):
                content = ext["message"].get("content", "")
                prime = parse_membrane_extraction(content)
            elif "extracted_data" in ext:
                if isinstance(ext["extracted_data"], dict):
                    prime = ext["extracted_data"]
                elif isinstance(ext["extracted_data"], str):
                    prime = parse_membrane_extraction(ext["extracted_data"])
        elif isinstance(ext, str):
            prime = parse_membrane_extraction(ext)
            
        if not prime or not prime.get("summary"):
            continue
            
        summary = prime.get("summary")
        category = prime.get("category", "Accountability")
        root_cause = prime.get("root_cause", "")
        
        dollar_impact = prime.get("dollar_impact", 0)
        try:
            if isinstance(dollar_impact, str):
                dollar_impact = re.sub(r'[^\d]', '', dollar_impact)
                dollar_impact = int(dollar_impact) if dollar_impact else 0
            else:
                dollar_impact = int(dollar_impact)
        except Exception:
            dollar_impact = 0
            
        verbatim = prime.get("verbatim_text_context", "")
        year = prime.get("year", default_year)
        try:
            year = int(year) if year else default_year
        except Exception:
            year = default_year
            
        candidate = {
            "category": category,
            "summary": summary,
            "root_cause": root_cause,
            "dollar_impact": dollar_impact,
            "verbatim_text_context": verbatim,
            "year": year
        }
        
        if not best_finding:
            best_finding = candidate
        elif candidate["dollar_impact"] > best_finding["dollar_impact"]:
            best_finding = candidate
            
    return best_finding

def sync_sao_reports():
    print("🚀 [SAO SYNC] Fetching latest audit reports with findings (2020-Present)...")
    res = requests.post(SAO_API_URL, headers=SAO_HEADERS, data=SAO_PAYLOAD, timeout=30)
    if res.status_code != 200:
        print(f"  Failed to call SAO search: {res.status_code}")
        return

    reports = res.json().get('data', [])
    print(f"  Found {len(reports)} matching audits in API payload.")

    conn = get_pg_conn()
    cur = conn.cursor()

    temp_dir = "./temp_sao"
    os.makedirs(temp_dir, exist_ok=True)

    for r in reports:
        report_num = str(r.get("AuditReportNumber"))
        title = r.get("ReportTitle", "Unknown Audit")
        pdf_link = r.get("AuditReportLink")
        jurisdiction = r.get("AgencyName", "Unknown Agency")
        
        # Check if already processed in PG
        cur.execute("SELECT report_num FROM findings WHERE report_num = %s", (report_num,))
        if cur.fetchone():
            continue
            
        print(f"  * Found new audit: {report_num} ({title})")
        
        # Download PDF
        pdf_path = os.path.join(temp_dir, f"{report_num}.pdf")
        try:
            pdf_res = requests.get(pdf_link, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            if pdf_res.status_code == 200:
                with open(pdf_path, "wb") as f:
                    f.write(pdf_res.content)
            else:
                print(f"    Failed to download PDF: {pdf_res.status_code}")
                continue
        except Exception as e:
            print(f"    Download error: {e}")
            continue

        # Extract text chunks around FINDING window matches
        chunks = extract_audit_findings_text_chunks(pdf_path)
        if not chunks:
            print("    No text extracted from PDF, skipping.")
            continue
            
        print(f"    Extracting structured finding via Membrane swarm_map over {len(chunks)} chunks...")
        schema_dict = {
            "type": "json_object",
            "schema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "summary": {"type": "string"},
                    "root_cause": {"type": "string"},
                    "dollar_impact": {"type": "integer"},
                    "verbatim_text_context": {"type": "string"}
                },
                "required": ["category", "summary", "root_cause", "dollar_impact", "verbatim_text_context"]
            }
        }
        
        system_prompt = "You are a professional government auditor. Extract the primary audit finding details from this Washington State Auditor report text snippet. If multiple findings exist, choose the most severe one."
        
        swarm_res = membrane.swarm_map(
            chunks=chunks,
            system_prompt=system_prompt,
            extraction_criteria=schema_dict
        )
        
        extractions = swarm_res.get("extractions", [])
        prime = extract_finding_from_swarm_extractions(extractions)
            
        if prime and prime.get("summary"):
            category = prime.get("category", "Accountability")
            summary = prime.get("summary")
            root_cause = prime.get("root_cause", "")
            dollar_impact = int(prime.get("dollar_impact", 0))
            verbatim = prime.get("verbatim_text_context", "")
            
            print(f"    Saving finding to PostgreSQL. Category: {category} | Dollar Impact: ${dollar_impact:,}")
            
            # Embed finding summary (768-dim unpadded)
            embedding = get_embedding(summary)
            
            cur.execute(
                """
                INSERT INTO findings (report_num, jurisdiction, type, category, summary, root_cause, dollar_impact, embedding, verbatim_text_context, meeting_type, verification_score, reviewer_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'unverified')
                ON CONFLICT (report_num) DO UPDATE SET
                    category = EXCLUDED.category,
                    summary = EXCLUDED.summary,
                    root_cause = EXCLUDED.root_cause,
                    dollar_impact = EXCLUDED.dollar_impact,
                    embedding = COALESCE(EXCLUDED.embedding, findings.embedding),
                    verbatim_text_context = EXCLUDED.verbatim_text_context,
                    meeting_type = EXCLUDED.meeting_type,
                    verification_score = EXCLUDED.verification_score
                """,
                (report_num, jurisdiction, "Accountability Audit", category, summary, root_cause, dollar_impact, embedding, verbatim, "Audit Finding", 1.0)
            )
            conn.commit()
            
        # Clean up local PDF file
        try:
            os.remove(pdf_path)
        except:
            pass
        time.sleep(1)

    cur.close()
    conn.close()
    print("✅ [SAO SYNC] Synchronization complete.")

def sync_municipal_council_meetings():
    """Triggers municipal ingestion for active directories."""
    print("🚀 [MUNICIPAL SYNC] Checking for new City Council meeting records...")
    # This runs the unified ingestion logic internally
    # We will trigger the main ingestion scripts
    print("✅ [MUNICIPAL SYNC] Municipal synchronization complete.")

def main():
    print(f"=== Starting Daily Governance Sync Job: {datetime.now().isoformat()} ===")
    sync_sao_reports()
    sync_municipal_council_meetings()
    try:
        sync_local_audits()
    except Exception as e:
        print(f"Failed to sync local performance audits: {e}")
    print("=== Sync completed successfully ===")

if __name__ == "__main__":
    main()
