import os
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
import requests
import json
import time
from datetime import datetime

# Database Connection Paths
SQLITE_DIR = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper"
POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:postgres_dev_password@localhost:5432/penner_governance_db"
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MEMBRANE_API_KEY = os.environ.get("MEMBRANE_API_KEY", "")

def get_pg_conn():
    return psycopg2.connect(POSTGRES_URL)

def get_embedding(text: str) -> list:
    """Fetch 1536-dim embedding for pgvector cosine comparison."""
    if not GEMINI_API_KEY:
        return None
    
    # We use Google's Gemini text-embedding-004 or text-embedding-3-small via litellm/direct call
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
            # Google's embeddings are 768 dims by default. We pad/scale or fit vector(1536) in DB.
            # Wait, our init.sql has vector(1536) for OpenAI compatibility or text-embedding-3-small.
            # If embedding is 768 dims, we can pad it with zeros to make it 1536, or resize database type to 768.
            # Let's adjust to pad to 1536 (or if we have OpenAI/LiteLLM, get 1536).
            # To be robust, let's pad the 768-dim vector to 1536 by adding 768 zeros at the end.
            if len(embedding) == 768:
                embedding.extend([0.0] * 768)
            return embedding[:1536]
    except Exception as e:
        print(f"  Warning: Embedding generation failed: {e}")
    return None

def migrate_ledger(pg_cursor):
    db_path = os.path.join(SQLITE_DIR, "ingestion_ledger.db")
    if not os.path.exists(db_path):
        print(f"Skipping ledger: {db_path} not found")
        return
    
    print("Migrating Ingestion Ledger...")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT jurisdiction_name, entity_type, state, official_url, vendor, api_endpoint, target_start_date, last_scrape_attempt, last_scrape_status, documents_vaulted, notes FROM ingestion_ledger")
    rows = c.fetchall()
    
    insert_query = """
    INSERT INTO ingestion_ledger (
        jurisdiction_name, entity_type, state, official_url, vendor, 
        api_endpoint, target_start_date, last_scrape_attempt, last_scrape_status, 
        documents_vaulted, notes
    ) VALUES %s
    ON CONFLICT (jurisdiction_name, entity_type) DO UPDATE SET
        state = EXCLUDED.state,
        official_url = EXCLUDED.official_url,
        vendor = EXCLUDED.vendor,
        api_endpoint = EXCLUDED.api_endpoint,
        target_start_date = EXCLUDED.target_start_date,
        last_scrape_attempt = EXCLUDED.last_scrape_attempt,
        last_scrape_status = EXCLUDED.last_scrape_status,
        documents_vaulted = EXCLUDED.documents_vaulted,
        notes = EXCLUDED.notes
    """
    execute_values(pg_cursor, insert_query, rows)
    conn.close()
    print(f"  Migrated {len(rows)} ledger entries.")

def migrate_findings(pg_cursor):
    """Merges and migrates findings from sao_2024.db, sao_audits.db, and audit_findings from municipal_intent.db."""
    sao_files = [
        ("sao_2024.db", "findings"),
        ("sao_audits.db", "findings"),
        ("municipal_intent.db", "audit_findings")
    ]
    
    total_migrated = 0
    report_nums_migrated = set()
    
    for filename, table in sao_files:
        db_path = os.path.join(SQLITE_DIR, filename)
        if not os.path.exists(db_path):
            print(f"Skipping findings file {filename}: not found")
            continue
            
        print(f"Migrating findings from {filename}:{table}...")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # Check if year column exists in this table
        c.execute(f"PRAGMA table_info({table})")
        columns = [col[1] for col in c.fetchall()]
        has_year = 'year' in columns
        
        try:
            q_cols = "report_num, jurisdiction, type, category, summary, root_cause, dollar_impact"
            if has_year:
                q_cols += ", year"
            c.execute(f"SELECT {q_cols} FROM {table}")
            rows = c.fetchall()
        except sqlite3.OperationalError as e:
            print(f"  Error reading table {table} from {filename}: {e}")
            conn.close()
            continue
            
        findings_to_insert = []
        for row in rows:
            report_num = row[0]
            if report_num in report_nums_migrated or not report_num:
                continue
                
            # Parse year from table or find default
            year = None
            if has_year:
                year = row[7]
            if not year:
                import re
                years_in_sum = re.findall(r'\b(202\d)\b', str(row[4]))
                if years_in_sum:
                    year = int(max(years_in_sum))
                else:
                    year = 2024 if filename == "sao_2024.db" else 2025
                    
            # Compute embedding for summary
            embedding = None
            if GEMINI_API_KEY:
                print(f"  -> Generating vector embedding for Report {report_num}...")
                embedding = get_embedding(row[4]) # row[4] is summary
                time.sleep(0.5) # simple rate limit buffer
                
            findings_to_insert.append((
                row[0], # report_num
                row[1], # jurisdiction
                row[2], # type
                row[3], # category
                row[4], # summary
                row[5], # root_cause
                row[6] or 0, # dollar_impact
                year,
                embedding
            ))
            report_nums_migrated.add(report_num)
            
        if findings_to_insert:
            insert_query = """
            INSERT INTO findings (
                report_num, jurisdiction, type, category, summary, root_cause, dollar_impact, year, embedding
            ) VALUES %s
            ON CONFLICT (report_num) DO UPDATE SET
                jurisdiction = EXCLUDED.jurisdiction,
                type = EXCLUDED.type,
                category = EXCLUDED.category,
                summary = EXCLUDED.summary,
                root_cause = EXCLUDED.root_cause,
                dollar_impact = EXCLUDED.dollar_impact,
                year = EXCLUDED.year,
                embedding = COALESCE(EXCLUDED.embedding, findings.embedding)
            """
            execute_values(pg_cursor, insert_query, findings_to_insert)
            total_migrated += len(findings_to_insert)
            
        conn.close()
        
    print(f"  Successfully merged and migrated {total_migrated} findings.")

def migrate_municipal_records(pg_cursor):
    db_path = os.path.join(SQLITE_DIR, "municipal_intent.db")
    if not os.path.exists(db_path):
        print(f"Skipping municipal records: {db_path} not found")
        return
        
    print("Migrating Municipal Records...")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 1. meeting_actions
    c.execute("SELECT event_id, jurisdiction, committee, meeting_date, key_action, dollar_amount, vote_outcome FROM meeting_actions")
    m_rows = c.fetchall()
    insert_meeting = """
    INSERT INTO meeting_actions (event_id, jurisdiction, committee, meeting_date, key_action, dollar_amount, vote_outcome)
    VALUES %s
    ON CONFLICT (event_id) DO NOTHING
    """
    execute_values(pg_cursor, insert_meeting, m_rows)
    print(f"  Migrated {len(m_rows)} raw meeting actions.")
    
    # 2. merged_actions (with embeddings)
    c.execute("SELECT event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount, vote_outcome FROM merged_actions")
    merged_rows = c.fetchall()
    merged_to_insert = []
    for r in merged_rows:
        embedding = None
        if GEMINI_API_KEY:
            print(f"  -> Generating vector embedding for Action {r[0]}...")
            embedding = get_embedding(r[4]) # key_action
            time.sleep(0.5)
            
        # Parse date representation
        m_date = None
        if r[3]:
            try:
                m_date = datetime.strptime(r[3][:10], "%Y-%m-%d").date()
            except:
                pass
                
        merged_to_insert.append((
            r[0], r[1], r[2], m_date, r[4], r[5], r[6] or 0, r[7], embedding
        ))
        
    insert_merged = """
    INSERT INTO merged_actions (event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount, vote_outcome, embedding)
    VALUES %s
    ON CONFLICT (event_id) DO UPDATE SET
        key_action = EXCLUDED.key_action,
        vendor = EXCLUDED.vendor,
        dollar_amount = EXCLUDED.dollar_amount,
        vote_outcome = EXCLUDED.vote_outcome,
        embedding = COALESCE(EXCLUDED.embedding, merged_actions.embedding)
    """
    execute_values(pg_cursor, insert_merged, merged_to_insert)
    print(f"  Migrated {len(merged_rows)} merged actions.")
    
    # 3. raw_civic_scraper_files
    c.execute("SELECT id, jurisdiction, file_url, file_type, local_path, processed FROM raw_civic_scraper_files")
    file_rows = c.fetchall()
    insert_files = """
    INSERT INTO raw_civic_scraper_files (id, jurisdiction, file_url, file_type, local_path, processed)
    VALUES %s
    ON CONFLICT (id) DO NOTHING
    """
    execute_values(pg_cursor, insert_files, file_rows)
    print(f"  Migrated {len(file_rows)} tracked files.")

    # 4. processed_intent (with embeddings)
    c.execute("SELECT file_id, jurisdiction, meeting_date, event_id, doc_type, item_number, agenda_item_title, key_action, vendor, dollar_amount, vote_outcome, primary_entity FROM processed_intent")
    intent_rows = c.fetchall()
    intent_to_insert = []
    for r in intent_rows:
        embedding = None
        if GEMINI_API_KEY:
            print(f"  -> Generating vector embedding for Intent Item {r[7][:25]}...")
            embedding = get_embedding(f"{r[6]}: {r[7]}") # agenda_item_title + key_action
            time.sleep(0.5)
            
        m_date = None
        if r[2]:
            try:
                m_date = datetime.strptime(r[2][:10], "%Y-%m-%d").date()
            except:
                pass
                
        intent_to_insert.append((
            r[0], r[1], m_date, r[3], r[4], r[5], r[6], r[7], r[8], r[9] or 0, r[10], r[11], embedding
        ))
        
    insert_intent = """
    INSERT INTO processed_intent (file_id, jurisdiction, meeting_date, event_id, doc_type, item_number, agenda_item_title, key_action, vendor, dollar_amount, vote_outcome, primary_entity, embedding)
    VALUES %s
    """
    execute_values(pg_cursor, insert_intent, intent_to_insert)
    print(f"  Migrated {len(intent_rows)} granular processed intents.")

    conn.close()

def main():
    print("Starting SQLite to PostgreSQL Migration...")
    start_time = time.time()
    
    try:
        pg_conn = get_pg_conn()
        pg_cursor = pg_conn.cursor()
    except Exception as e:
        print(f"Fatal error connecting to PostgreSQL database: {e}")
        return
        
    try:
        migrate_ledger(pg_cursor)
        pg_conn.commit()
        
        migrate_findings(pg_cursor)
        pg_conn.commit()
        
        migrate_municipal_records(pg_cursor)
        pg_conn.commit()
        
        print("\n=========================================")
        print("MIGRATION COMPLETE")
        print(f"Time elapsed: {time.time() - start_time:.2f} seconds")
        print("=========================================")
        
    except Exception as e:
        pg_conn.rollback()
        print(f"\nMigration failed with error: {e}")
        
    finally:
        pg_cursor.close()
        pg_conn.close()

if __name__ == "__main__":
    main()
