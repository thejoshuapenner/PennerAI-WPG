import os
import re
import requests
import hashlib
import sqlite3
import psycopg2
import tempfile
from pypdf import PdfReader
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import time
import json
from datetime import datetime

# Import Membrane adapter
from services.membrane import MembraneClient

load_dotenv()

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:postgres_dev_password@localhost:5432/penner_governance_db"
)
SQLITE_PATH = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/sao_audits.db"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Initialize client
membrane = MembraneClient()

def get_pg_conn():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except Exception as e:
        print(f"PostgreSQL connection failed: {e}")
        return None

def get_sqlite_conn():
    try:
        if os.path.exists(SQLITE_PATH):
            conn = sqlite3.connect(SQLITE_PATH)
            conn.row_factory = sqlite3.Row
            return conn
    except Exception as e:
        print(f"SQLite connection failed: {e}")
    return None

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


def migrate_databases():
    """Ensure source_url column exists in findings table in both PG and SQLite."""
    print("🛠️ [LOCAL SYNC] Checking database migrations...")
    
    # 1. Migrate PostgreSQL
    conn_pg = get_pg_conn()
    if conn_pg:
        try:
            cur = conn_pg.cursor()
            cur.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_url TEXT;")
            conn_pg.commit()
            cur.close()
            conn_pg.close()
            print("  PostgreSQL findings table updated with source_url.")
        except Exception as e:
            print(f"  PostgreSQL migration failed: {e}")
            
    # 2. Migrate SQLite
    conn_sq = get_sqlite_conn()
    if conn_sq:
        try:
            cur = conn_sq.cursor()
            # SQLite does not support ADD COLUMN IF NOT EXISTS natively in all versions, 
            # so we check if the column is present first.
            cur.execute("PRAGMA table_info(findings);")
            columns = [row[1] for row in cur.fetchall()]
            if "source_url" not in columns:
                cur.execute("ALTER TABLE findings ADD COLUMN source_url TEXT;")
                conn_sq.commit()
                print("  SQLite sao_audits.db findings table updated with source_url.")
            else:
                print("  SQLite findings table already contains source_url.")
            cur.close()
            conn_sq.close()
        except Exception as e:
            print(f"  SQLite migration failed: {e}")

def fetch_seattle_audit_links() -> list:
    """Scrape Seattle Auditor's page for PDF reports."""
    from urllib.parse import urljoin
    url = "https://www.seattle.gov/cityauditor/reports"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    links = []
    try:
        print(f"🔗 [LOCAL SYNC] Fetching Seattle Auditor listings from: {url}")
        res = requests.get(url, headers=headers, timeout=20)
        if res.status_code != 200:
            print(f"  Failed to load Seattle listings: {res.status_code}")
            return []
            
        soup = BeautifulSoup(res.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            # Identify audit report PDF URLs
            if ".pdf" in href.lower() and ("/documents/" in href.lower() or "auditreports" in href.lower()):
                # Resolve relative URL against the root domain of seattle.gov instead of parent reports path
                resolved_url = urljoin("https://www.seattle.gov/", href)
                title = a.get_text().strip() or "Seattle Auditor Report"
                links.append({"url": resolved_url, "title": title, "jurisdiction": "Seattle"})
    except Exception as e:
        print(f"  Seattle link scraping failed: {e}")
    
    # Deduplicate by URL
    seen = set()
    deduped = []
    for l in links:
        if l["url"] not in seen:
            seen.add(l["url"])
            deduped.append(l)
    print(f"  Found {len(deduped)} unique Seattle audit report links.")
    return deduped

def fetch_king_county_audit_links() -> list:
    """Scrape King County Auditor's page for PDF reports (two-step crawler)."""
    from urllib.parse import urljoin
    homepage_url = "https://kingcounty.gov/en/legacy/depts/auditor"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    links = []
    try:
        print(f"🔗 [LOCAL SYNC] Fetching King County Auditor legacy homepage: {homepage_url}")
        res = requests.get(homepage_url, headers=headers, timeout=20)
        if res.status_code != 200:
            print(f"  Failed to load King County legacy homepage: {res.status_code}")
            return []
            
        soup = BeautifulSoup(res.text, "html.parser")
        sub_page_urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            # Extract links containing auditors-office reports
            if "/auditors-office/reports-papers/reports/" in href or "/reports-papers/reports/" in href:
                resolved_url = urljoin(homepage_url, href)
                if resolved_url not in sub_page_urls:
                    sub_page_urls.append(resolved_url)
                    
        print(f"  Found {len(sub_page_urls)} report sub-pages. Crawling sub-pages for PDF links...")
        
        # Request each sub-page to extract the direct PDF link
        for sub_url in sub_page_urls[:15]:  # Limit to the first 15 sub-pages to be fast
            try:
                sub_res = requests.get(sub_url, headers=headers, timeout=15)
                if sub_res.status_code != 200:
                    continue
                sub_soup = BeautifulSoup(sub_res.text, "html.parser")
                for a_sub in sub_soup.find_all("a", href=True):
                    pdf_href = a_sub["href"].strip()
                    if ".pdf" in pdf_href.lower() and ("/auditors-office/reports/" in pdf_href.lower() or "/independent/" in pdf_href.lower() or "/~/media/" in pdf_href.lower() or "/media/" in pdf_href.lower()):
                        resolved_pdf_url = urljoin(sub_url, pdf_href)
                        # Use clean text or title
                        pdf_title = a_sub.get_text().strip() or a_sub.get("title", "").strip() or "King County Auditor Report"
                        links.append({"url": resolved_pdf_url, "title": pdf_title, "jurisdiction": "King County"})
                        break # Usually one main report PDF per sub-page
            except Exception as sub_err:
                print(f"    Failed to parse sub-page {sub_url}: {sub_err}")
                
    except Exception as e:
        print(f"  King County link scraping failed: {e}")
    
    # Deduplicate by URL
    seen = set()
    deduped = []
    for l in links:
        if l["url"] not in seen:
            seen.add(l["url"])
            deduped.append(l)
    print(f"  Found {len(deduped)} unique King County audit report links.")
    return deduped

def sync_local_audits(max_new_audits=10):
    """Scrapes, processes, and indexes local performance audits into PG and SQLite."""
    print("🚀 [LOCAL AUDITS SYNC] Starting local performance and policy audits sync...")
    
    # Migrate databases first
    migrate_databases()
    
    audit_sources = []
    audit_sources.extend(fetch_seattle_audit_links())
    audit_sources.extend(fetch_king_county_audit_links())
    
    if not audit_sources:
        print("  No local audit links found to sync.")
        return

    conn_pg = get_pg_conn()
    conn_sq = get_sqlite_conn()
    
    if not conn_pg and not conn_sq:
        print("❌ [LOCAL SYNC] No database connections available. Aborting.")
        return
        
    synced_count = 0
    
    for audit in audit_sources:
        if synced_count >= max_new_audits:
            print(f"  Reached execution limit of {max_new_audits} new audits in this run.")
            break
            
        url = audit["url"]
        title = audit["title"]
        jurisdiction = audit["jurisdiction"]
        
        # Check if already processed in either database
        already_processed = False
        if conn_pg:
            try:
                cur = conn_pg.cursor()
                cur.execute("SELECT report_num FROM findings WHERE source_url = %s", (url,))
                if cur.fetchone():
                    already_processed = True
                cur.close()
            except Exception as e:
                print(f"  PG check failed: {e}")
                
        if not already_processed and conn_sq:
            try:
                cur = conn_sq.cursor()
                cur.execute("SELECT report_num FROM findings WHERE source_url = ?", (url,))
                if cur.fetchone():
                    already_processed = True
                cur.close()
            except Exception as e:
                print(f"  SQLite check failed: {e}")
                
        if already_processed:
            continue
            
        # Generate custom report ID: Prefix + MD5 hash of URL
        url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:10].upper()
        prefix = "SEA-" if jurisdiction == "Seattle" else "KCA-"
        report_num = f"{prefix}{url_hash}"
        
        print(f"  * Found new local audit: {report_num} | Jurisdiction: {jurisdiction} | Title: {title}")
        
        # Download PDF to temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            pdf_path = tmp_file.name
            
        try:
            pdf_res = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }, timeout=30)
            if pdf_res.status_code == 200 and len(pdf_res.content) > 0:
                with open(pdf_path, "wb") as f:
                    f.write(pdf_res.content)
            else:
                print(f"    Failed to download PDF: {pdf_res.status_code}")
                try:
                    os.remove(pdf_path)
                except:
                    pass
                continue
        except Exception as download_err:
            print(f"    Download error: {download_err}")
            try:
                os.remove(pdf_path)
            except:
                pass
            continue
            
        # Extract text chunks around FINDING window matches
        chunks = extract_audit_findings_text_chunks(pdf_path)
        try:
            os.remove(pdf_path)
        except:
            pass
            
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
                    "verbatim_text_context": {"type": "string"},
                    "year": {"type": "integer"}
                },
                "required": ["category", "summary", "root_cause", "dollar_impact", "verbatim_text_context", "year"]
            }
        }
        
        system_prompt = f"You are a professional local government auditor. Extract the primary audit findings, category, root cause, dollar impact, publication/release year, and verbatim text snippet from the provided text snippet of this {jurisdiction} Auditor report. If multiple findings exist, choose the most severe or important one."
        
        swarm_res = membrane.swarm_map(
            chunks=chunks,
            system_prompt=system_prompt,
            extraction_criteria=schema_dict
        )
        
        extractions = swarm_res.get("extractions", [])
        prime = extract_finding_from_swarm_extractions(extractions, default_year=datetime.now().year)
            
        if prime and prime.get("summary"):
            category = prime.get("category", "Performance Audit")
            summary = prime.get("summary")
            root_cause = prime.get("root_cause", "")
            dollar_impact = int(prime.get("dollar_impact", 0))
            verbatim = prime.get("verbatim_text_context", "")
            year = int(prime.get("year", datetime.now().year))
            
            print(f"    Saving finding to DB. Year: {year} | Category: {category} | Dollar Impact: ${dollar_impact:,}")
            
            # Embed finding summary (768-dim unpadded)
            embedding = get_embedding(summary)
            
            # 1. Save to PostgreSQL
            if conn_pg:
                try:
                    cur = conn_pg.cursor()
                    cur.execute(
                        """
                        INSERT INTO findings (report_num, jurisdiction, type, category, summary, root_cause, dollar_impact, year, embedding, verbatim_text_context, meeting_type, verification_score, reviewer_status, source_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1.0, 'unverified', %s)
                        ON CONFLICT (report_num) DO UPDATE SET
                            category = EXCLUDED.category,
                            summary = EXCLUDED.summary,
                            root_cause = EXCLUDED.root_cause,
                            dollar_impact = EXCLUDED.dollar_impact,
                            year = EXCLUDED.year,
                            embedding = COALESCE(EXCLUDED.embedding, findings.embedding),
                            verbatim_text_context = EXCLUDED.verbatim_text_context,
                            meeting_type = EXCLUDED.meeting_type,
                            source_url = EXCLUDED.source_url
                        """,
                        (report_num, jurisdiction, "Performance Audit", category, summary, root_cause, dollar_impact, year, embedding, verbatim, "Audit Finding", url)
                    )
                    conn_pg.commit()
                    cur.close()
                    print("      Saved to PostgreSQL.")
                except Exception as pg_err:
                    print(f"      PostgreSQL insert failed: {pg_err}")
                    conn_pg.rollback()
                    
            # 2. Save to SQLite Fallback
            if conn_sq:
                try:
                    cur = conn_sq.cursor()
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO findings (report_num, jurisdiction, category, summary, dollar_impact, year, source_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (report_num, jurisdiction, category, summary, dollar_impact, year, url)
                    )
                    conn_sq.commit()
                    cur.close()
                    print("      Saved to SQLite.")
                except Exception as sq_err:
                    print(f"      SQLite insert failed: {sq_err}")
            
            synced_count += 1
            time.sleep(1)
            
    if conn_pg:
        conn_pg.close()
    if conn_sq:
        conn_sq.close()
    print(f"✅ [LOCAL AUDITS SYNC] Sync complete. Ingested {synced_count} new local audits.")

if __name__ == "__main__":
    sync_local_audits()
