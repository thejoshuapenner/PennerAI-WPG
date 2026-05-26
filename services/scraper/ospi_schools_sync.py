import os
import requests
import json
import sqlite3
import psycopg2
import time
from datetime import datetime
from dotenv import load_dotenv

# Load environmental variables
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "../backend/.env"))

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:penner_secret_password_2026@localhost:5432/penner_governance_db"
)
SQLITE_PATH = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/municipal_intent.db"

def get_pg_conn():
    try:
        return psycopg2.connect(POSTGRES_URL)
    except Exception as e:
        print(f"Postgres connection failed: {e}")
        return None

def get_sqlite_conn():
    try:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=DELETE;")
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn
    except Exception as e:
        print(f"SQLite connection failed: {e}")
        return None

def get_embedding(text: str) -> list:
    """Fetch 1536-dim embedding vector."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "models/text-embedding-004",
        "content": {"parts": [{"text": text[:2000]}]}
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            values = res.json()["embedding"]["values"]
            if len(values) == 768:
                values.extend([0.0] * 768)
            return values[:1536]
    except Exception as e:
        print(f"Gemini embedding failed: {e}")
    return None

def load_jurisdictions(conn, is_pg: bool) -> list:
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM jurisdictions WHERE entity_type = 'school_district'")
        if is_pg:
            return [r[0] for r in cur.fetchall()]
        else:
            return [r["name"] for r in cur.fetchall()]
    except Exception as e:
        print(f"Failed loading jurisdictions: {e}")
        return []
    finally:
        cur.close()

def standardize_jurisdiction(raw_name: str, jurisdictions: list) -> str:
    if not raw_name:
        return "Unknown"
    
    clean_name = raw_name.strip()
    # Normalize common suffix
    if "school district" in clean_name.lower():
         # Keep standard form
         pass
    else:
         clean_name_with_sd = f"{clean_name} School District"
         
    for name in jurisdictions:
        if clean_name.lower() in name.lower() or name.lower() in clean_name.lower():
            return name
        if "school district" in clean_name.lower():
            simple = clean_name.lower().replace("school district", "").strip()
            if simple in name.lower():
                return name
                
    return clean_name

def sync_ospi_schools():
    print("🚀 [OSPI SCHOOLS SYNC] Fetching real Washington School District Financials...")
    
    # Query vnm3-j8pe for the last 5 school years at the District level
    url = "https://data.wa.gov/resource/vnm3-j8pe.json"
    params = {
        "$limit": 5000,
        "organization_level": "District",
        "$where": "school_year_code >= '2020-21'"
    }
    
    try:
        print(f"  Querying Socrata API: {url}")
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"Socrata API returned status {resp.status_code}: {resp.text}")
            
        raw_records = resp.json()
        print(f"  Successfully fetched {len(raw_records)} records from OSPI Socrata API.")
    except Exception as e:
        print(f"  [ERROR] Failed to query Socrata API: {e}")
        raise e

    # Write to databases
    pg_conn = get_pg_conn()
    sqlite_conn = get_sqlite_conn()
    
    pg_cur = pg_conn.cursor() if pg_conn else None
    sqlite_cur = sqlite_conn.cursor() if sqlite_conn else None
    
    # Pre-load school district jurisdictions to map correctly
    conn_to_use = pg_conn if pg_conn else sqlite_conn
    is_pg_mode = True if pg_conn else False
    jurisdictions_list = load_jurisdictions(conn_to_use, is_pg_mode)
    
    saved_count = 0
    
    # Truncate tables first to ensure a clean sync of the last 4-5 years
    if sqlite_cur:
        sqlite_cur.execute("DELETE FROM school_district_financials")
        sqlite_conn.commit()
    if pg_cur:
        pg_cur.execute("DELETE FROM school_district_financials")
        pg_conn.commit()

    for r in raw_records:
        district_raw = r.get("districtname")
        if not district_raw:
            continue
            
        std_name = standardize_jurisdiction(district_raw, jurisdictions_list)
        
        # Parse school_year_code (e.g. "2023-24" -> 2024)
        year_code = r.get("school_year_code", "")
        parts = year_code.split("-")
        if len(parts) == 2:
            year = int(parts[0][:2] + parts[1])
        else:
            continue
            
        enrollment = float(r.get("enrollment", 0))
        
        # Financial variables
        exp_local = float(r.get("expenditures_from_local", 0))
        exp_state = float(r.get("expenditures_from_state", 0))
        exp_federal = float(r.get("expenditures_from_federal", 0))
        total_exp = float(r.get("total_expenditures1", exp_local + exp_state + exp_federal))
        
        # Revenues (using sum of local + state + federal expenditures as revenue proxy)
        total_rev = exp_local + exp_state + exp_federal
        
        levy_amount = exp_local # local expenditure represents the levy funding portion
        fed_funding = exp_federal
        
        source_url = f"https://data.wa.gov/resource/vnm3-j8pe.json?districtname={district_raw}"
        
        # Embeddings generation is throttled/skipped for performance except on universe districts to keep it fast
        embedding = None
        # Only generate embeddings for districts that match our target universe to save time/calls
        if std_name in jurisdictions_list and saved_count < 300: 
            summary_text = f"School District: {std_name} | Year: {year} | Enrollment: {enrollment:.0f} FTE | Total Expenditures: ${total_exp:,.0f} | State: ${exp_state:,.0f} | Federal: ${fed_funding:,.0f}"
            # Embed occasionally/fast or skip if it slows down too much
            # embedding = get_embedding(summary_text) # disabled by default to run instantly, can re-enable if required
            
        # SQLite Insertion
        if sqlite_conn and sqlite_cur:
            try:
                embed_str = json.dumps(embedding) if embedding else None
                sqlite_cur.execute(
                    """
                    INSERT INTO school_district_financials (district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (std_name, year, enrollment, total_rev, total_exp, levy_amount, 0.0, fed_funding, source_url, embed_str)
                )
            except Exception as sq_err:
                print(f"  SQLite insert failed for {std_name} ({year}): {sq_err}")
                
        # Postgres Insertion
        if pg_conn and pg_cur:
            try:
                pg_cur.execute(
                    """
                    INSERT INTO school_district_financials (district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (std_name, year, enrollment, total_rev, total_exp, levy_amount, 0.0, fed_funding, source_url, embedding)
                )
            except Exception as pg_err:
                print(f"  Postgres insert failed for {std_name} ({year}): {pg_err}")
                pg_conn.rollback()
                
        saved_count += 1

    if pg_conn:
        pg_conn.commit()
        pg_cur.close()
        pg_conn.close()
        
    if sqlite_conn:
        sqlite_conn.commit()
        sqlite_cur.close()
        sqlite_conn.close()
        
    print(f"✅ [OSPI SCHOOLS SYNC] Sync complete. Ingested {saved_count} real school district financial profiles.")

if __name__ == "__main__":
    sync_ospi_schools()

