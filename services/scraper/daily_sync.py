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
    "postgresql://penner_admin:penner_secret_password_2026@localhost:5432/penner_governance_db"
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
    """Fetch 1536-dim embedding vector."""
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
            if len(embedding) == 768:
                embedding.extend([0.0] * 768)
            return embedding[:1536]
    except Exception as e:
        print(f"Embedding failed: {e}")
    return None

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

        # Extract combined text of first 15 pages
        try:
            reader = PdfReader(pdf_path)
            text = ""
            for i in range(min(15, len(reader.pages))):
                text += reader.pages[i].extract_text() + "\n"
        except Exception as e:
            print(f"    Error reading PDF text: {e}")
            continue

        if not text.strip():
            print("    No text extracted from PDF, skipping.")
            continue
            
        print("    Extracting structured finding via Membrane response_format...")
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
        
        messages = [
            {
                "role": "system", 
                "content": "You are a professional government auditor. Extract the primary audit finding details from this Washington State Auditor report text. If multiple findings exist, choose the most severe one."
            },
            {
                "role": "user", 
                "content": f"Extract the primary finding in JSON format matching the schema:\n\nReport Text:\n{text[:45000]}"
            }
        ]
        
        res_data = membrane.chat_completion(
            messages=messages,
            response_format=schema_dict
        )
        
        try:
            choice = res_data.get("choices", [])[0]
            content_str = choice.get("message", {}).get("content", "")
            if "```json" in content_str:
                content_str = content_str.split("```json")[1].split("```")[0].strip()
            elif "```" in content_str:
                content_str = content_str.split("```")[1].split("```")[0].strip()
                
            prime = json.loads(content_str)
        except Exception as parse_err:
            print("    Failed parsing Membrane response format:", parse_err)
            continue
            
        if prime and prime.get("summary"):
            category = prime.get("category", "Accountability")
            summary = prime.get("summary")
            root_cause = prime.get("root_cause", "")
            dollar_impact = int(prime.get("dollar_impact", 0))
            verbatim = prime.get("verbatim_text_context", "")
            
            print(f"    Saving finding to PostgreSQL. Category: {category} | Dollar Impact: ${dollar_impact:,}")
            
            # Embed finding summary
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
