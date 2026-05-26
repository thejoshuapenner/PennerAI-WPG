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

def standardize_jurisdiction(raw_name: str, conn, is_pg: bool) -> str:
    if not raw_name:
        return "Unknown"
    
    # Counties are named as "Adams County", "King County", etc.
    clean_name = raw_name.strip()
    if not clean_name.lower().endswith("county"):
        clean_name = f"{clean_name} County"
        
    cur = conn.cursor()
    try:
        if is_pg:
            cur.execute("SELECT name FROM jurisdictions WHERE name ILIKE %s LIMIT 1", (f"%{clean_name}%",))
        else:
            cur.execute("SELECT name FROM jurisdictions WHERE name LIKE ? LIMIT 1", (f"%{clean_name}%",))
        row = cur.fetchone()
        if row:
            return row[0] if is_pg else row["name"]
    except Exception:
        pass
    finally:
        cur.close()
        
    return clean_name

def sync_fit_budgets():
    print("🚀 [FIT BUDGET SYNC] Fetching Washington Local County Road Budgets...")
    
    # 1. Fetch Revenues (29hx-2hie)
    rev_url = "https://data.wa.gov/resource/29hx-2hie.json"
    print(f"  Fetching revenues from Socrata: {rev_url}")
    try:
        resp = requests.get(rev_url, params={"$limit": 5000}, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"Socrata revenue API returned {resp.status_code}: {resp.text}")
        raw_revs = resp.json()
        print(f"  Successfully fetched {len(raw_revs)} revenue records.")
    except Exception as e:
        print(f"  [ERROR] Failed to fetch revenues: {e}")
        raise e
        
    # 2. Fetch Expenditures (bxeh-ranj)
    exp_url = "https://data.wa.gov/resource/bxeh-ranj.json"
    print(f"  Fetching expenditures from Socrata: {exp_url}")
    try:
        resp = requests.get(exp_url, params={"$limit": 5000}, timeout=30)
        if resp.status_code != 200:
            raise Exception(f"Socrata expenditure API returned {resp.status_code}: {resp.text}")
        raw_exps = resp.json()
        print(f"  Successfully fetched {len(raw_exps)} expenditure records.")
    except Exception as e:
        print(f"  [ERROR] Failed to fetch expenditures: {e}")
        raise e

    # Build maps keying on (countyname, calendaryear)
    rev_map = {}
    for r in raw_revs:
        county = r.get("countyname")
        year = r.get("calendaryear")
        if county and year:
            rev_map[(county.strip().lower(), str(year))] = r
            
    exp_map = {}
    for r in raw_exps:
        county = r.get("countyname")
        year = r.get("calendaryear")
        if county and year:
            exp_map[(county.strip().lower(), str(year))] = r

    # Write to databases
    pg_conn = get_pg_conn()
    sqlite_conn = get_sqlite_conn()
    
    pg_cur = pg_conn.cursor() if pg_conn else None
    sqlite_cur = sqlite_conn.cursor() if sqlite_conn else None
    
    # Truncate tables first
    print("  Truncating budgets and budget_items tables...")
    if sqlite_cur:
        sqlite_cur.execute("DELETE FROM budget_items")
        sqlite_cur.execute("DELETE FROM budgets")
        sqlite_conn.commit()
    if pg_cur:
        pg_cur.execute("DELETE FROM budget_items")
        pg_cur.execute("DELETE FROM budgets")
        pg_conn.commit()

    saved_budget_count = 0
    saved_item_count = 0
    
    # Revenue fields to extract
    rev_fields = [
        ("directdistribution", "Direct Distribution"),
        ("tib", "Transportation Improvement Board (TIB)"),
        ("rapprogram", "Rural Arterial Program (RAP)"),
        ("cappprogram", "County Arterial Preservation (CAP)"),
        ("propertytax", "Property Tax"),
        ("timberexcisetax", "Timber Excise Tax"),
        ("othertax", "Other Tax"),
        ("federalgrants", "Federal Grants"),
        ("federallands", "Federal Lands"),
        ("miscellaneousother", "Miscellaneous Other")
    ]
    
    # Expenditure fields to extract
    exp_fields = [
        ("construction", "Construction"),
        ("maintenance", "Maintenance"),
        ("administrationandoperations", "Administration & Operations"),
        ("facilities", "Facilities"),
        ("ferry", "Ferry"),
        ("bondwarrant", "Bond Warrant"),
        ("trafficpolicing", "Traffic Policing"),
        ("other", "Other Expenditures")
    ]

    # Process alignment
    keys = set(rev_map.keys()).intersection(set(exp_map.keys()))
    print(f"  Aligned {len(keys)} budgets to process.")
    
    for key in sorted(keys):
        county_raw, year_str = key
        r_row = rev_map[key]
        e_row = exp_map[key]
        
        county_disp = r_row.get("countyname", "Unknown")
        
        conn_to_use = pg_conn if pg_conn else sqlite_conn
        is_pg_mode = True if pg_conn else False
        std_name = standardize_jurisdiction(county_disp, conn_to_use, is_pg_mode)
        
        year = int(year_str)
        total_rev = float(r_row.get("total", 0))
        total_exp = float(e_row.get("total", 0))
        
        budget_id = None
        source_url = f"https://data.wa.gov/resource/bxeh-ranj.json?countyname={county_disp}"
        
        # SQLite Budget Parent Insert
        if sqlite_conn and sqlite_cur:
            try:
                sqlite_cur.execute(
                    """
                    INSERT INTO budgets (jurisdiction_name, entity_type, fiscal_year, total_revenue, total_expenditures, fund_balance_beginning, fund_balance_ending, source_url)
                    VALUES (?, 'county', ?, ?, ?, 0.0, 0.0, ?)
                    """,
                    (std_name, year, total_rev, total_exp, source_url)
                )
                sqlite_cur.execute("SELECT last_insert_rowid()")
                sqlite_budget_id = sqlite_cur.fetchone()[0]
                if not pg_conn:
                    budget_id = sqlite_budget_id
                    saved_budget_count += 1
            except Exception as sq_err:
                print(f"  SQLite insert budget failed for {std_name} ({year}): {sq_err}")
                
        # Postgres Budget Parent Insert
        if pg_conn and pg_cur:
            try:
                pg_cur.execute(
                    """
                    INSERT INTO budgets (jurisdiction_name, entity_type, fiscal_year, total_revenue, total_expenditures, fund_balance_beginning, fund_balance_ending, source_url)
                    VALUES (%s, 'county', %s, %s, %s, 0.0, 0.0, %s)
                    RETURNING id
                    """,
                    (std_name, year, total_rev, total_exp, source_url)
                )
                budget_id = pg_cur.fetchone()[0]
                saved_budget_count += 1
            except Exception as pg_err:
                print(f"  Postgres insert budget failed for {std_name} ({year}): {pg_err}")
                pg_conn.rollback()
                
        # Ingest budget_items
        if budget_id:
            # 1. Ingest Revenues BARS
            for field, label in rev_fields:
                amt = float(r_row.get(field, 0))
                if amt > 0:
                    # SQLite Item Insert
                    if sqlite_conn and sqlite_cur:
                        try:
                            sqlite_cur.execute(
                                """
                                INSERT INTO budget_items (budget_id, category_type, major_category, amount, account_code, description, embedding)
                                VALUES (?, 'revenue', ?, ?, 'BARS', ?, NULL)
                                """,
                                (budget_id, label, amt, f"County Road Revenue: {label}")
                            )
                            if not pg_conn:
                                saved_item_count += 1
                        except Exception as sq_child_err:
                            print(f"    SQLite insert revenue item failed: {sq_child_err}")
                            
                    # Postgres Item Insert
                    if pg_conn and pg_cur:
                        try:
                            pg_cur.execute(
                                """
                                INSERT INTO budget_items (budget_id, category_type, major_category, amount, account_code, description, embedding)
                                VALUES (%s, 'revenue', %s, %s, 'BARS', %s, NULL)
                                """,
                                (budget_id, label, amt, f"County Road Revenue: {label}")
                            )
                            saved_item_count += 1
                        except Exception as pg_child_err:
                            print(f"    Postgres insert revenue item failed: {pg_child_err}")
                            pg_conn.rollback()
                            
            # 2. Ingest Expenditures BARS
            for field, label in exp_fields:
                amt = float(e_row.get(field, 0))
                if amt > 0:
                    # SQLite Item Insert
                    if sqlite_conn and sqlite_cur:
                        try:
                            sqlite_cur.execute(
                                """
                                INSERT INTO budget_items (budget_id, category_type, major_category, amount, account_code, description, embedding)
                                VALUES (?, 'expenditure', ?, ?, 'BARS', ?, NULL)
                                """,
                                (budget_id, label, amt, f"County Road Expenditure: {label}")
                            )
                            if not pg_conn:
                                saved_item_count += 1
                        except Exception as sq_child_err:
                            print(f"    SQLite insert expenditure item failed: {sq_child_err}")
                            
                    # Postgres Item Insert
                    if pg_conn and pg_cur:
                        try:
                            pg_cur.execute(
                                """
                                INSERT INTO budget_items (budget_id, category_type, major_category, amount, account_code, description, embedding)
                                VALUES (%s, 'expenditure', %s, %s, 'BARS', %s, NULL)
                                """,
                                (budget_id, label, amt, f"County Road Expenditure: {label}")
                            )
                            saved_item_count += 1
                        except Exception as pg_child_err:
                            print(f"    Postgres insert expenditure item failed: {pg_child_err}")
                            pg_conn.rollback()

    if pg_conn:
        pg_conn.commit()
        pg_cur.close()
        pg_conn.close()
        
    if sqlite_conn:
        sqlite_conn.commit()
        sqlite_cur.close()
        sqlite_conn.close()
        
    print(f"✅ [FIT BUDGET SYNC] Ingested {saved_budget_count} budgets and {saved_item_count} category breakdowns.")

if __name__ == "__main__":
    sync_fit_budgets()

