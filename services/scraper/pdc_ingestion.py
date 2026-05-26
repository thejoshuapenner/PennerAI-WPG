import os
import requests
import json
import sqlite3
import psycopg2
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
        return conn
    except Exception as e:
        print(f"SQLite connection failed: {e}")
        return None

def sync_pdc_contributions(limit=5000):
    print(f"🚀 [PDC SYNC] Fetching campaign contributions from 2020 to present (Limit: {limit})...")
    
    # Socrata Query: 2020 to present, ordering by receipt_date descending
    # Parameter `$where` must be filtered for receipt_date >= '2020-01-01T00:00:00.000'
    params = {
        "$limit": limit,
        "$where": "receipt_date >= '2020-01-01T00:00:00' AND amount IS NOT NULL",
        "$order": "receipt_date DESC"
    }
    
    url = "https://data.wa.gov/resource/kv7h-kjye.json"
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"  [ERROR] Socrata API returned {resp.status_code}: {resp.text}")
            return
            
        contributions = resp.json()
        print(f"  Fetched {len(contributions)} records from PDC Socrata Portal.")
        
        # Connect to databases
        pg_conn = get_pg_conn()
        sqlite_conn = get_sqlite_conn()
        
        pg_cur = pg_conn.cursor() if pg_conn else None
        sqlite_cur = sqlite_conn.cursor() if sqlite_conn else None
        
        saved_count = 0
        
        for c in contributions:
            candidate = c.get("filer_name", "Unknown Filer").strip()
            contributor = c.get("contributor_name", "Unknown Contributor").strip()
            employer = c.get("contributor_employer_name", "None")
            amount_str = c.get("amount", "0")
            receipt_date_str = c.get("receipt_date", "")
            jurisdiction = c.get("jurisdiction", "Unknown")
            
            if not receipt_date_str:
                continue
                
            # Parse receipt_date
            try:
                # Socrata timestamp format e.g. "2025-09-15T00:00:00.000"
                parsed_date = datetime.strptime(receipt_date_str.split("T")[0], "%Y-%m-%d").date()
                amount = float(amount_str)
            except Exception as e:
                print(f"  Failed parsing row values amount={amount_str} date={receipt_date_str}: {e}")
                continue
                
            # Postgres Insertion
            if pg_conn and pg_cur:
                try:
                    # Check if already exists to prevent duplicate ingestion
                    # (PDC rows don't have a unique ID in Socrata, so we match on core values)
                    pg_cur.execute(
                        """
                        SELECT id FROM political_contributions 
                        WHERE candidate_name = %s AND contributor_name = %s AND amount = %s AND receipt_date = %s
                        LIMIT 1
                        """,
                        (candidate, contributor, amount, parsed_date)
                    )
                    if not pg_cur.fetchone():
                        pg_cur.execute(
                            """
                            INSERT INTO political_contributions (candidate_name, contributor_name, contributor_employer, amount, receipt_date, jurisdiction)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (candidate, contributor, employer, amount, parsed_date, jurisdiction)
                        )
                        saved_count += 1
                except Exception as pg_err:
                    print(f"  Postgres insert failed: {pg_err}")
                    pg_conn.rollback()
                    
            # SQLite Insertion
            if sqlite_conn and sqlite_cur:
                try:
                    sqlite_cur.execute(
                        """
                        SELECT id FROM political_contributions 
                        WHERE candidate_name = ? AND contributor_name = ? AND amount = ? AND receipt_date = ?
                        LIMIT 1
                        """,
                        (candidate, contributor, amount, parsed_date.isoformat())
                    )
                    if not sqlite_cur.fetchone():
                        sqlite_cur.execute(
                            """
                            INSERT INTO political_contributions (candidate_name, contributor_name, contributor_employer, amount, receipt_date, jurisdiction)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (candidate, contributor, employer, amount, parsed_date.isoformat(), jurisdiction)
                        )
                        if not pg_conn: # Count SQLite only if Postgres fallback active
                            saved_count += 1
                except Exception as sqlite_err:
                    print(f"  SQLite insert failed: {sqlite_err}")
                    
        if pg_conn:
            pg_conn.commit()
            pg_cur.close()
            pg_conn.close()
            
        if sqlite_conn:
            sqlite_conn.commit()
            sqlite_cur.close()
            sqlite_conn.close()
            
        print(f"✅ [PDC SYNC] Successfully loaded {saved_count} new donation records.")
    except Exception as e:
        print(f"[PDC SYNC] Ingestion crash: {e}")

if __name__ == "__main__":
    sync_pdc_contributions()
