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
    "postgresql://penner_admin:postgres_dev_password@localhost:5432/penner_governance_db"
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

def sync_pdc_contributions():
    print("🚀 [PDC SYNC] Starting bulk campaign contributions ingestion (2022 to Present)...")
    
    pg_conn = get_pg_conn()
    sqlite_conn = get_sqlite_conn()
    
    pg_cur = pg_conn.cursor() if pg_conn else None
    sqlite_cur = sqlite_conn.cursor() if sqlite_conn else None
    
    # 1. Clear existing data to prevent duplicate keys or entries from our target years
    print("  Clearing existing political contributions from 2022-Present...")
    if sqlite_conn and sqlite_cur:
        try:
            sqlite_cur.execute("DELETE FROM political_contributions WHERE receipt_date >= '2022-01-01'")
            sqlite_conn.commit()
            print("  Cleared SQLite contributions from 2022-Present.")
        except Exception as e:
            print(f"  Failed clearing SQLite: {e}")
            
    if pg_conn and pg_cur:
        try:
            pg_cur.execute("DELETE FROM political_contributions WHERE receipt_date >= '2022-01-01'")
            pg_conn.commit()
            print("  Cleared Postgres contributions from 2022-Present.")
        except Exception as e:
            print(f"  Failed clearing Postgres: {e}")
            pg_conn.rollback()

    # 2. Fetch and import records by year to avoid deep offset issues on Socrata
    years = [2022, 2023, 2024, 2025, 2026]
    page_size = 50000
    total_saved = 0
    
    url = "https://data.wa.gov/resource/kv7h-kjye.json"
    
    for year in years:
        print(f"\n  === Processing Year {year} ===")
        offset = 0
        year_saved = 0
        retries = 0
        
        while True:
            where_clause = f"receipt_date >= '{year}-01-01T00:00:00' AND receipt_date <= '{year}-12-31T23:59:59' AND amount IS NOT NULL"
            params = {
                "$limit": page_size,
                "$offset": offset,
                "$where": where_clause,
                "$order": "receipt_date ASC"
            }
            
            print(f"    Fetching records {offset:,} to {offset + page_size:,}...")
            start_time = time.time()
            try:
                resp = requests.get(url, params=params, timeout=45)
                if resp.status_code != 200:
                    print(f"    [ERROR] Socrata API returned {resp.status_code}: {resp.text}")
                    retries += 1
                    if retries >= 3:
                        print(f"    [CRITICAL] Maximum API errors reached for year {year} offset {offset}. Skipping remainder of year.")
                        break
                    time.sleep(5)
                    continue
                    
                contributions = resp.json()
                if not contributions:
                    print(f"    No more records for year {year}.")
                    break
                    
                print(f"    Fetched {len(contributions):,} records in {time.time() - start_time:.2f}s. Parsing...")
                
                batch_data = []
                for c in contributions:
                    candidate = c.get("filer_name", "Unknown Filer").strip()
                    contributor = c.get("contributor_name", "Unknown Contributor").strip()
                    employer = c.get("contributor_employer_name", "None")
                    amount_str = c.get("amount", "0")
                    receipt_date_str = c.get("receipt_date", "")
                    jurisdiction = c.get("jurisdiction", "Unknown")
                    
                    if not receipt_date_str:
                        continue
                        
                    try:
                        parsed_date_str = receipt_date_str.split("T")[0]
                        amount = float(amount_str)
                        batch_data.append((candidate, contributor, employer, amount, parsed_date_str, jurisdiction))
                    except Exception as e:
                        continue
                
                # Bulk insert to databases
                if batch_data:
                    # SQLite Insert
                    if sqlite_conn and sqlite_cur:
                        try:
                            sqlite_cur.executemany(
                                """
                                INSERT INTO political_contributions (candidate_name, contributor_name, contributor_employer, amount, receipt_date, jurisdiction)
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                batch_data
                            )
                            sqlite_conn.commit()
                        except Exception as sqlite_err:
                            print(f"    SQLite batch insert failed: {sqlite_err}")
                            
                    # Postgres Insert
                    if pg_conn and pg_cur:
                        try:
                            pg_cur.executemany(
                                """
                                INSERT INTO political_contributions (candidate_name, contributor_name, contributor_employer, amount, receipt_date, jurisdiction)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                """,
                                batch_data
                            )
                            pg_conn.commit()
                        except Exception as pg_err:
                            print(f"    Postgres batch insert failed: {pg_err}")
                            pg_conn.rollback()
                            
                    year_saved += len(batch_data)
                    total_saved += len(batch_data)
                    print(f"    Inserted {len(batch_data):,} records. Year total: {year_saved:,}")
                
                # Reset retries on successful fetch and insert
                retries = 0
                
                if len(contributions) < page_size:
                    print(f"    Reached end of records for year {year}.")
                    break
                    
                offset += page_size
                time.sleep(0.5) # Politeness delay
                
            except Exception as e:
                retries += 1
                print(f"    Error during batch request (attempt {retries}/3): {e}")
                if retries >= 3:
                    print(f"    [CRITICAL] Maximum retries reached for year {year} offset {offset}. Skipping remainder of year.")
                    break
                time.sleep(5) # Delay on error before retry
                continue
                
    # 3. Create indexes for fast queries
    print("\n  Building indexes on political_contributions...")
    if sqlite_conn and sqlite_cur:
        try:
            sqlite_cur.execute("CREATE INDEX IF NOT EXISTS idx_contributions_candidate ON political_contributions (candidate_name)")
            sqlite_cur.execute("CREATE INDEX IF NOT EXISTS idx_contributions_contributor ON political_contributions (contributor_name)")
            sqlite_cur.execute("CREATE INDEX IF NOT EXISTS idx_contributions_date ON political_contributions (receipt_date)")
            sqlite_conn.commit()
            print("  SQLite indexes created successfully.")
        except Exception as e:
            print(f"  SQLite index creation failed: {e}")
            
    if pg_conn and pg_cur:
        try:
            pg_cur.execute("CREATE INDEX IF NOT EXISTS idx_contributions_candidate ON political_contributions (candidate_name)")
            pg_cur.execute("CREATE INDEX IF NOT EXISTS idx_contributions_contributor ON political_contributions (contributor_name)")
            pg_cur.execute("CREATE INDEX IF NOT EXISTS idx_contributions_date ON political_contributions (receipt_date)")
            pg_conn.commit()
            print("  Postgres indexes created successfully.")
        except Exception as e:
            print(f"  Postgres index creation failed: {e}")
            pg_conn.rollback()

    if pg_conn:
        pg_cur.close()
        pg_conn.close()
        
    if sqlite_conn:
        sqlite_cur.close()
        sqlite_conn.close()
        
    print(f"\n✅ [PDC SYNC] Bulk ingestion complete. Total loaded: {total_saved:,} records.")

if __name__ == "__main__":
    sync_pdc_contributions()

