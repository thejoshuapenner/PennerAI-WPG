import os
import requests
import json
import sqlite3
import psycopg2
import time
import re
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

def load_jurisdictions(conn, is_pg: bool) -> dict:
    """Load and prepare jurisdictions by entity type."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT name, entity_type FROM jurisdictions")
        rows = cur.fetchall()
        
        j_by_type = {
            'school_district': [],
            'port': [],
            'county': [],
            'city': []
        }
        
        for r in rows:
            name = r[0] if is_pg else r['name']
            etype = r[1] if is_pg else r['entity_type']
            
            clean_name = name.strip()
            if clean_name.startswith('"') and clean_name.endswith('"'):
                clean_name = clean_name[1:-1].strip()
                
            base = clean_name
            if etype == 'school_district':
                base = re.sub(r'\s+School\s+District.*$', '', clean_name, flags=re.IGNORECASE)
            elif etype == 'port':
                base = re.sub(r'^Port\s+of\s+', '', clean_name, flags=re.IGNORECASE)
            elif etype == 'county':
                base = re.sub(r'\s+County$', '', clean_name, flags=re.IGNORECASE)
                
            j_by_type[etype].append({
                'std_name': clean_name,
                'base': base.upper().strip()
            })
            
        return j_by_type
    except Exception as e:
        print(f"Failed loading jurisdictions: {e}")
        return {}
    finally:
        cur.close()

def match_recipient(recip_name, j_by_type) -> tuple:
    """Match raw recipient name to standardized jurisdiction."""
    if not recip_name:
        return None, None
        
    name_up = recip_name.upper().strip()
    
    exclude_terms = [
        "COLLEGE", "UNIVERSITY", "HOSPITAL", "CLINIC", "CANCER CENTER", "HEALTH CENTER", 
        "ASSOCIATION", "SOCIETY", "CHAMBER OF COMMERCE", "FOUNDATION", "DEVELOPMENT SERVICE", 
        "FAMILY SERVICES", "HOUSING AUTHORITY", "PUBLIC UTILITY DISTRICT", "CONSERVATION DISTRICT", 
        "COALITION", "COMMUNITY SERVICES", "COMMUNITY ACTION", "HEALTHCARE", "CENTER FOR",
        "PUD NO", "P.U.D."
    ]
    if any(term in name_up for term in exclude_terms):
        return None, None
        
    # 1. Ports
    if "PORT" in name_up:
        for p in j_by_type['port']:
            if f"PORT OF {p['base']}" in name_up or f"{p['base']} PORT" in name_up or name_up == p['base']:
                return p['std_name'], 'port'
            if "PORT OF" in name_up and p['base'] in name_up:
                return p['std_name'], 'port'
                
    # 2. School Districts
    if ("SCHOOL" in name_up or "DISTRICT" in name_up or " SD" in name_up or "PUBLIC SCHOOLS" in name_up) and "PUBLIC UTILITY DISTRICT" not in name_up:
        for sd in j_by_type['school_district']:
            if sd['base'] in name_up:
                return sd['std_name'], 'school_district'
                
    # 3. Counties
    if "COUNTY" in name_up and "SCHOOL" not in name_up and "DISTRICT" not in name_up:
        for c in j_by_type['county']:
            if f"{c['base']} COUNTY" in name_up or f"COUNTY OF {c['base']}" in name_up:
                return c['std_name'], 'county'
            if c['base'] in name_up and "COUNTY" in name_up:
                return c['std_name'], 'county'
                
    # 4. Cities
    for city in j_by_type['city']:
        base = city['base']
        patterns = [
            f"CITY OF {base}",
            f"TOWN OF {base}",
            f"{base}, CITY OF",
            f"{base}, TOWN OF",
            f"{base} CITY",
            f"{base} TOWN"
        ]
        if any(p in name_up for p in patterns) or name_up == base:
            return city['std_name'], 'city'
            
    return None, None

def sync_grants():
    print("🚀 [GRANTS SYNC] Fetching real Federal Grants for Washington local entities from USA Spending...")
    
    # 1. Load jurisdictions list using a brief SQLite/Postgres connection
    sqlite_conn = get_sqlite_conn()
    pg_conn = get_pg_conn()
    
    conn_to_use = pg_conn if pg_conn else sqlite_conn
    is_pg_mode = True if pg_conn else False
    if not conn_to_use:
        print("[ERROR] No database connections available.")
        return
        
    j_by_type = load_jurisdictions(conn_to_use, is_pg_mode)
    
    if sqlite_conn:
        sqlite_conn.close()
    if pg_conn:
        pg_conn.close()
        
    # 2. Query USA Spending API in memory (no open database connections during network calls)
    years = [2022, 2023, 2024, 2025, 2026]
    grants_to_insert = []
    seen_keys = set()
    
    url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    
    for year in years:
        print(f"\n  === Querying USA Spending for Year {year} ===")
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        
        # Fetch the top 5 pages (500 records) of grant awards in WA for each year
        for page in range(1, 6):
            payload = {
                "filters": {
                    "time_period": [
                        {"start_date": start_date, "end_date": end_date}
                    ],
                    "recipient_locations": [
                        {"country": "USA", "state": "WA"}
                    ],
                    "award_type_codes": ["02", "03", "04", "05"],
                    "recipient_type_names": ["local_government"]
                },
                "fields": [
                    "Award ID",
                    "Recipient Name",
                    "Award Amount",
                    "Awarding Agency",
                    "Awarding Sub Agency",
                    "Start Date",
                    "End Date",
                    "Description",
                    "generated_internal_id"
                ],
                "sort": "Award Amount",
                "order": "desc",
                "limit": 100,
                "page": page
            }
            
            print(f"    Fetching page {page}...")
            try:
                resp = requests.post(url, json=payload, timeout=30)
                if resp.status_code != 200:
                    print(f"    [ERROR] USA Spending API returned {resp.status_code}: {resp.text}")
                    break
                    
                results = resp.json().get("results", [])
                if not results:
                    break
                    
                for r in results:
                    recip = r.get("Recipient Name", "")
                    std_name, etype = match_recipient(recip, j_by_type)
                    if not std_name:
                        continue
                        
                    grant_id = r.get("Award ID", "Unknown ID")
                    amount = float(r.get("Award Amount", 0.0))
                    
                    desc = r.get("Description", "")
                    if desc:
                        title = desc[:250] + ("..." if len(desc) > 250 else "")
                    else:
                        title = f"{r.get('Awarding Agency', 'Federal')} Grant Award"
                        
                    agency = r.get("Awarding Agency", "Federal Agency")
                    if r.get("Awarding Sub Agency"):
                        agency = f"{agency} ({r.get('Awarding Sub Agency')})"
                        
                    award_date_str = r.get("Start Date")
                    perf_start = r.get("Start Date")
                    perf_end = r.get("End Date")
                    purpose = r.get("Awarding Sub Agency", "Federal Assistance")
                    source = "Federal"
                    
                    internal_id = r.get("generated_internal_id", "")
                    source_url = f"https://www.usaspending.gov/award/{internal_id}" if internal_id else "https://www.usaspending.gov/"
                    
                    # Deduplicate in-memory using a unique key
                    unique_key = (grant_id, title, std_name, amount)
                    if unique_key in seen_keys:
                        continue
                    seen_keys.add(unique_key)
                    
                    grants_to_insert.append((
                        title, grant_id, agency, std_name, etype, amount, 
                        award_date_str, perf_start, perf_end, purpose, source, source_url
                    ))
                    
                time.sleep(0.5) # Politeness delay
                
            except Exception as e:
                print(f"    [ERROR] Request failed on page {page}: {e}")
                break
                
    print(f"\n  Fetched and matched {len(grants_to_insert)} awards in memory.")
    
    # 3. Perform database operations in one fast transaction
    saved_count = 0
    
    # Re-open database connections for insertion
    sqlite_conn = get_sqlite_conn()
    pg_conn = get_pg_conn()
    
    sqlite_cur = sqlite_conn.cursor() if sqlite_conn else None
    pg_cur = pg_conn.cursor() if pg_conn else None
    
    print("  Truncating grants tables...")
    if sqlite_cur:
        try:
            sqlite_cur.execute("DELETE FROM grants")
            sqlite_conn.commit()
        except Exception as e:
            print(f"  [ERROR] SQLite truncate failed: {e}")
    if pg_cur:
        try:
            pg_cur.execute("DELETE FROM grants")
            pg_conn.commit()
        except Exception as e:
            print(f"  [ERROR] Postgres truncate failed: {e}")
            
    # Batch Insert SQLite
    if sqlite_conn and sqlite_cur and grants_to_insert:
        print("  Inserting records into SQLite...")
        try:
            sqlite_cur.executemany(
                """
                INSERT INTO grants (grant_title, grant_id, awarding_agency, recipient_jurisdiction, recipient_entity_type, award_amount, award_date, performance_period_start, performance_period_end, purpose_category, funding_source, source_url, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                grants_to_insert
            )
            sqlite_conn.commit()
            if not pg_conn:
                saved_count = len(grants_to_insert)
        except Exception as e:
            print(f"  [ERROR] SQLite batch insert failed: {e}")
            
    # Batch Insert Postgres
    if pg_conn and pg_cur and grants_to_insert:
        print("  Inserting records into Postgres...")
        try:
            pg_cur.executemany(
                """
                INSERT INTO grants (grant_title, grant_id, awarding_agency, recipient_jurisdiction, recipient_entity_type, award_amount, award_date, performance_period_start, performance_period_end, purpose_category, funding_source, source_url, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                """,
                grants_to_insert
            )
            pg_conn.commit()
            saved_count = len(grants_to_insert)
        except Exception as e:
            print(f"  [ERROR] Postgres batch insert failed: {e}")
            pg_conn.rollback()
            
    if sqlite_conn:
        sqlite_cur.close()
        sqlite_conn.close()
    if pg_conn:
        pg_cur.close()
        pg_conn.close()
        
    print(f"\n✅ [GRANTS SYNC] Ingested {saved_count} real federal grant records.")

if __name__ == "__main__":
    sync_grants()
