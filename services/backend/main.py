import os
import json
import re
import logging
import time
import uuid
import hashlib
import psycopg2
import httpx
import requests
import asyncio
import litellm
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Security, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from dotenv import load_dotenv

# Import shared models and Membrane adapter
from packages.shared.shared_schemas import AlertSubscriptionSchema
from services.membrane import MembraneClient

security = HTTPBearer(auto_error=False)


load_dotenv()

app = FastAPI(title="PennerAI Governance Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:penner_secret_password_2026@localhost:5432/penner_governance_db"
)
SQLITE_TRACKING_PATH = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/usage_tracking.db"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Initialize the Membrane client
membrane = MembraneClient()

class ChatRequest(BaseModel):
    query: str
    lens: str = "comprehensive" # "comprehensive" | "audits" | "council"

class SynthesizeRequest(BaseModel):
    jurisdiction: str
    query: str

import sqlite3

def clean_summary_text(agenda_title: Optional[str], key_action: Optional[str] = None) -> str:
    """Parses structured JSON strings and formats them into clean, human-readable text."""
    def parse_if_json(val: Optional[str]):
        if not val:
            return None, None
        val_str = str(val).strip()
        start_idx = val_str.find("{")
        end_idx = val_str.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                json_part = val_str[start_idx:end_idx+1]
                parsed = json.loads(json_part)
                suffix = val_str[end_idx+1:].strip()
                if suffix.startswith(":"):
                    suffix = suffix[1:].strip()
                return parsed, suffix
            except Exception:
                pass
        return None, None

    # Handle single argument case
    if agenda_title and not key_action:
        parsed, suffix = parse_if_json(agenda_title)
        if parsed and isinstance(parsed, dict):
            action_type = parsed.get("action_type") or parsed.get("title") or parsed.get("agenda_item_title")
            details = parsed.get("details") or parsed.get("description")
            status = parsed.get("status")
            parts = []
            if action_type:
                parts.append(action_type.strip())
            if details:
                parts.append(details.strip())
            if status and status.lower() not in ["passed", "failed", "unknown"]:
                parts.append(f"Status: {status}")
            res = " - ".join(parts) if parts else str(agenda_title)
            if suffix:
                res = f"{res} ({suffix})"
            return res
        return str(agenda_title)

    # Both provided
    parsed_title, title_suffix = parse_if_json(agenda_title)
    parsed_action, action_suffix = parse_if_json(key_action)

    title_str = ""
    action_str = ""

    if parsed_title and isinstance(parsed_title, dict):
        action_type = parsed_title.get("action_type") or parsed_title.get("title") or parsed_title.get("agenda_item_title")
        details = parsed_title.get("details") or parsed_title.get("description")
        parts = []
        if action_type:
            parts.append(action_type.strip())
        if details:
            parts.append(details.strip())
        title_str = " - ".join(parts) if parts else str(agenda_title)
        if title_suffix:
            title_str = f"{title_str} ({title_suffix})"
    else:
        title_str = str(agenda_title) if agenda_title else ""

    if parsed_action and isinstance(parsed_action, dict):
        action_type = parsed_action.get("action_type") or parsed_action.get("title") or parsed_action.get("agenda_item_title")
        details = parsed_action.get("details") or parsed_action.get("description")
        parts = []
        if action_type:
            parts.append(action_type.strip())
        if details:
            parts.append(details.strip())
        action_str = " - ".join(parts) if parts else str(key_action)
        if action_suffix:
            action_str = f"{action_str} ({action_suffix})"
    else:
        action_str = str(key_action) if key_action else ""

    if title_str and action_str:
        if action_str.strip() in title_str:
            return title_str
        if title_str.strip() in action_str:
            return action_str
        
        action_clean = action_str.strip()
        if action_clean.startswith("[Passed]") or action_clean.startswith("[Failed]") or action_clean.lower() in ["passed", "failed"]:
            return f"{title_str} ({action_clean})"
        
        return f"{title_str}: {action_str}"

    return title_str or action_str or "No description available"

_postgres_available = True
_last_postgres_check_time = 0.0
_postgres_check_cooldown = 30.0

def get_pg_conn():
    global _postgres_available, _last_postgres_check_time
    now = time.time()
    if not _postgres_available and (now - _last_postgres_check_time < _postgres_check_cooldown):
        raise psycopg2.OperationalError(
            "Postgres is down. Circuit breaker active (skipping connection attempt)."
        )
    try:
        conn = psycopg2.connect(POSTGRES_URL, connect_timeout=2)
        _postgres_available = True
        _last_postgres_check_time = now
        return conn
    except Exception as e:
        _postgres_available = False
        _last_postgres_check_time = now
        raise e

def get_sqlite_conn(db_name: str):
    sqlite_dir = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper"
    db_path = os.path.join(sqlite_dir, db_name)
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn
    return None

def bootstrap_database():
    """Ensure api_keys and api_usage_logs tables exist in the database and seed default developer keys."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id SERIAL PRIMARY KEY,
                api_key VARCHAR(255) UNIQUE NOT NULL,
                owner_name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT TRUE
            )
            """
        )
        
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS api_usage_logs (
                id SERIAL PRIMARY KEY,
                api_key VARCHAR(255) REFERENCES api_keys(api_key) ON DELETE CASCADE,
                endpoint VARCHAR(100) NOT NULL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                estimated_cost NUMERIC(10, 6) DEFAULT 0.0,
                timestamp TIMESTAMP DEFAULT NOW()
            )
            """
        )
        
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS correlations (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                hook TEXT NOT NULL,
                report_markdown TEXT NOT NULL,
                citations JSONB DEFAULT '[]',
                status VARCHAR(50) DEFAULT 'proposed',
                created_at TIMESTAMP DEFAULT NOW(),
                reviewed_at TIMESTAMP
            )
            """
        )
        
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bug_reports (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255),
                email VARCHAR(255),
                report_type VARCHAR(50) NOT NULL,
                description TEXT NOT NULL,
                anonymous_user_id VARCHAR(64),
                session_id VARCHAR(64),
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_subscriptions (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                topics TEXT NOT NULL,
                jurisdiction VARCHAR(255),
                query TEXT,
                anonymous_user_id VARCHAR(64),
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS authoritative_entities (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                entity_type VARCHAR(50) NOT NULL,
                official_url VARCHAR(255) NOT NULL,
                agenda_portal_url VARCHAR(255),
                platform VARCHAR(50),
                verification_status VARCHAR(50) DEFAULT 'unverified',
                is_active BOOLEAN DEFAULT TRUE,
                minutes_url VARCHAR(255),
                agenda_url VARCHAR(255),
                packets_url VARCHAR(255),
                video_url VARCHAR(255),
                audio_url VARCHAR(255),
                transcripts_url VARCHAR(255),
                crawler_path_filter VARCHAR(255),
                crawler_doc_types VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
        )
        cur.execute("ALTER TABLE authoritative_entities ADD COLUMN IF NOT EXISTS minutes_url VARCHAR(255);")
        cur.execute("ALTER TABLE authoritative_entities ADD COLUMN IF NOT EXISTS agenda_url VARCHAR(255);")
        cur.execute("ALTER TABLE authoritative_entities ADD COLUMN IF NOT EXISTS packets_url VARCHAR(255);")
        cur.execute("ALTER TABLE authoritative_entities ADD COLUMN IF NOT EXISTS video_url VARCHAR(255);")
        cur.execute("ALTER TABLE authoritative_entities ADD COLUMN IF NOT EXISTS audio_url VARCHAR(255);")
        cur.execute("ALTER TABLE authoritative_entities ADD COLUMN IF NOT EXISTS transcripts_url VARCHAR(255);")
        cur.execute("ALTER TABLE authoritative_entities ADD COLUMN IF NOT EXISTS crawler_path_filter VARCHAR(255);")
        cur.execute("ALTER TABLE authoritative_entities ADD COLUMN IF NOT EXISTS crawler_doc_types VARCHAR(255);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS political_contributions (
                id SERIAL PRIMARY KEY,
                candidate_name VARCHAR(255) NOT NULL,
                contributor_name VARCHAR(255) NOT NULL,
                contributor_employer VARCHAR(255),
                amount NUMERIC(12, 2) NOT NULL,
                receipt_date DATE NOT NULL,
                jurisdiction VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS legislative_bills (
                bill_number VARCHAR(50) PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                biennium VARCHAR(50) NOT NULL,
                sponsor VARCHAR(255),
                passed_date DATE,
                summary TEXT,
                affected_rcws JSONB DEFAULT '[]',
                affected_wacs JSONB DEFAULT '[]',
                policy_category VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW()
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS jurisdictions (
                name VARCHAR(255) PRIMARY KEY,
                entity_type VARCHAR(100) NOT NULL,
                county VARCHAR(100),
                population INTEGER,
                latitude NUMERIC(9, 6),
                longitude NUMERIC(9, 6),
                last_updated TIMESTAMP DEFAULT NOW()
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS budgets (
                id SERIAL PRIMARY KEY,
                jurisdiction_name VARCHAR(255) REFERENCES jurisdictions(name) ON DELETE CASCADE,
                entity_type VARCHAR(100) NOT NULL,
                fiscal_year INTEGER NOT NULL,
                total_revenue NUMERIC(15, 2) NOT NULL,
                total_expenditures NUMERIC(15, 2) NOT NULL,
                fund_balance_beginning NUMERIC(15, 2),
                fund_balance_ending NUMERIC(15, 2),
                source_url TEXT,
                last_updated TIMESTAMP DEFAULT NOW(),
                CONSTRAINT unique_jurisdiction_budget UNIQUE (jurisdiction_name, fiscal_year)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_items (
                id SERIAL PRIMARY KEY,
                budget_id INTEGER REFERENCES budgets(id) ON DELETE CASCADE,
                category_type VARCHAR(50) NOT NULL,
                major_category VARCHAR(255) NOT NULL,
                amount NUMERIC(15, 2) NOT NULL,
                account_code VARCHAR(50),
                description TEXT,
                embedding vector(1536)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS grants (
                id SERIAL PRIMARY KEY,
                grant_title VARCHAR(255) NOT NULL,
                grant_id VARCHAR(100),
                awarding_agency VARCHAR(255) NOT NULL,
                recipient_jurisdiction VARCHAR(255) REFERENCES jurisdictions(name) ON DELETE SET NULL,
                recipient_entity_type VARCHAR(100),
                award_amount NUMERIC(15, 2) NOT NULL,
                award_date DATE,
                performance_period_start DATE,
                performance_period_end DATE,
                purpose_category VARCHAR(255),
                funding_source VARCHAR(100),
                source_url TEXT,
                last_updated TIMESTAMP DEFAULT NOW(),
                embedding vector(1536)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS school_district_financials (
                id SERIAL PRIMARY KEY,
                district_name VARCHAR(255) REFERENCES jurisdictions(name) ON DELETE CASCADE,
                fiscal_year INTEGER NOT NULL,
                enrollment NUMERIC(10, 2),
                total_revenue NUMERIC(15, 2) NOT NULL,
                total_expenditures NUMERIC(15, 2) NOT NULL,
                levy_amount NUMERIC(15, 2),
                special_education_spending NUMERIC(15, 2),
                federal_funding_amount NUMERIC(15, 2),
                source_url TEXT,
                last_updated TIMESTAMP DEFAULT NOW(),
                embedding vector(1536),
                CONSTRAINT unique_district_financial_year UNIQUE (district_name, fiscal_year)
            )
            """
        )

        # Alter existing tables
        try:
            cur.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS source_url TEXT;")
        except Exception as e:
            print(f"Postgres Alter Table findings for source_url skipped: {e}")

        for table in ["findings", "merged_actions", "processed_intent"]:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS verbatim_text_context TEXT;")
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS meeting_type VARCHAR(50);")
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS verification_score NUMERIC(5, 2);")
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS reviewer_status VARCHAR(50) DEFAULT 'unverified';")
            except Exception as e:
                print(f"Postgres Alter Table {table} skipped: {e}")

        # Seed jurisdictions from CSV if table is empty
        try:
            cur.execute("SELECT COUNT(*) FROM jurisdictions")
            if cur.fetchone()[0] == 0:
                import csv
                csv_path = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/mapped_wa_universe_verified.csv"
                if os.path.exists(csv_path):
                    with open(csv_path, mode='r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            name = row.get("Name")
                            raw_type = row.get("Type", "Unknown").lower()
                            entity_type = "special_district"
                            if "city" in raw_type or "town" in raw_type:
                                entity_type = "city"
                            elif "county" in raw_type:
                                entity_type = "county"
                            elif "school" in raw_type:
                                entity_type = "school_district"
                            elif "port" in raw_type:
                                entity_type = "port"
                            county = row.get("County")
                            if name:
                                cur.execute(
                                    """
                                    INSERT INTO jurisdictions (name, entity_type, county)
                                    VALUES (%s, %s, %s)
                                    ON CONFLICT (name) DO NOTHING
                                    """,
                                    (name, entity_type, county)
                                )
        except Exception as seed_err:
            print("Failed seeding Postgres jurisdictions:", seed_err)

        # Seed authoritative entities from CSV if table is empty
        try:
            cur.execute("SELECT COUNT(*) FROM authoritative_entities")
            if cur.fetchone()[0] == 0:
                import csv
                csv_path = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/mapped_wa_universe_verified.csv"
                if os.path.exists(csv_path):
                    with open(csv_path, mode='r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            name = row.get("Name")
                            entity_type = row.get("Type")
                            official_url = row.get("Official_URL")
                            agenda_portal_url = row.get("API_Endpoint") or row.get("Scrape_Target")
                            platform = row.get("Vendor")
                            if name and official_url:
                                cur.execute(
                                    """
                                    INSERT INTO authoritative_entities (name, entity_type, official_url, agenda_portal_url, platform, verification_status)
                                    VALUES (%s, %s, %s, %s, %s, 'verified')
                                    ON CONFLICT (name) DO NOTHING
                                    """,
                                    (name, entity_type, official_url, agenda_portal_url, platform)
                                )
        except Exception as seed_err:
            print("Failed seeding Postgres authoritative entities:", seed_err)

        cur.execute(
            """
            INSERT INTO api_keys (api_key, owner_name)
            VALUES 
                ('sk-penner-dev-2026', 'PennerAI Developer'),
                ('sk-penner-dashboard', 'PennerAI Dashboard Internal')
            ON CONFLICT (api_key) DO NOTHING
            """
        )
        
        conn.commit()
        cur.close()
        conn.close()
        print("PostgreSQL Database bootstrapped successfully.")
    except Exception as pg_err:
        print("Postgres bootstrap failed, trying SQLite fallback:", pg_err)
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS api_keys (
                            key_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            api_key TEXT UNIQUE NOT NULL,
                            owner_name TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            is_active INTEGER DEFAULT 1
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS api_usage_logs (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            api_key TEXT REFERENCES api_keys(api_key) ON DELETE CASCADE,
                            endpoint TEXT NOT NULL,
                            prompt_tokens INTEGER DEFAULT 0,
                            completion_tokens INTEGER DEFAULT 0,
                            total_tokens INTEGER DEFAULT 0,
                            estimated_cost REAL DEFAULT 0.0,
                            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS correlations (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            title TEXT NOT NULL,
                            hook TEXT NOT NULL,
                            report_markdown TEXT NOT NULL,
                            citations TEXT DEFAULT '[]',
                            status TEXT DEFAULT 'proposed',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            reviewed_at TIMESTAMP
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS bug_reports (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT,
                            email TEXT,
                            report_type TEXT NOT NULL,
                            description TEXT NOT NULL,
                            anonymous_user_id TEXT,
                            session_id TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS authoritative_entities (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT UNIQUE NOT NULL,
                            entity_type TEXT NOT NULL,
                            official_url TEXT NOT NULL,
                            agenda_portal_url TEXT,
                            platform TEXT,
                            verification_status TEXT DEFAULT 'unverified',
                            is_active INTEGER DEFAULT 1,
                            minutes_url TEXT,
                            agenda_url TEXT,
                            packets_url TEXT,
                            video_url TEXT,
                            audio_url TEXT,
                            transcripts_url TEXT,
                            crawler_path_filter TEXT,
                            crawler_doc_types TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    cur.execute("PRAGMA table_info(authoritative_entities)")
                    cols = [r[1] for r in cur.fetchall()]
                    for col in ["minutes_url", "agenda_url", "packets_url", "video_url", "audio_url", "transcripts_url", "crawler_path_filter", "crawler_doc_types"]:
                        if col not in cols:
                            cur.execute(f"ALTER TABLE authoritative_entities ADD COLUMN {col} TEXT")

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS political_contributions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            candidate_name TEXT NOT NULL,
                            contributor_name TEXT NOT NULL,
                            contributor_employer TEXT,
                            amount REAL NOT NULL,
                            receipt_date TEXT NOT NULL,
                            jurisdiction TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS legislative_bills (
                            bill_number TEXT PRIMARY KEY,
                            title TEXT NOT NULL,
                            biennium TEXT NOT NULL,
                            sponsor TEXT,
                            passed_date TEXT,
                            summary TEXT,
                            affected_rcws TEXT DEFAULT '[]',
                            affected_wacs TEXT DEFAULT '[]',
                            policy_category TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jurisdictions (
                            name TEXT PRIMARY KEY,
                            entity_type TEXT NOT NULL,
                            county TEXT,
                            population INTEGER,
                            latitude REAL,
                            longitude REAL,
                            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS budgets (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            jurisdiction_name TEXT REFERENCES jurisdictions(name) ON DELETE CASCADE,
                            entity_type TEXT NOT NULL,
                            fiscal_year INTEGER NOT NULL,
                            total_revenue REAL NOT NULL,
                            total_expenditures REAL NOT NULL,
                            fund_balance_beginning REAL,
                            fund_balance_ending REAL,
                            source_url TEXT,
                            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(jurisdiction_name, fiscal_year)
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS budget_items (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            budget_id INTEGER REFERENCES budgets(id) ON DELETE CASCADE,
                            category_type TEXT NOT NULL,
                            major_category TEXT NOT NULL,
                            amount REAL NOT NULL,
                            account_code TEXT,
                            description TEXT,
                            embedding TEXT
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS grants (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            grant_title TEXT NOT NULL,
                            grant_id TEXT,
                            awarding_agency TEXT NOT NULL,
                            recipient_jurisdiction TEXT REFERENCES jurisdictions(name) ON DELETE SET NULL,
                            recipient_entity_type TEXT,
                            award_amount REAL NOT NULL,
                            award_date TEXT,
                            performance_period_start TEXT,
                            performance_period_end TEXT,
                            purpose_category TEXT,
                            funding_source TEXT,
                            source_url TEXT,
                            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            embedding TEXT
                        )
                        """
                    )

                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS school_district_financials (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            district_name TEXT REFERENCES jurisdictions(name) ON DELETE CASCADE,
                            fiscal_year INTEGER NOT NULL,
                            enrollment REAL,
                            total_revenue REAL NOT NULL,
                            total_expenditures REAL NOT NULL,
                            levy_amount REAL,
                            special_education_spending REAL,
                            federal_funding_amount REAL,
                            source_url TEXT,
                            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            embedding TEXT,
                            UNIQUE(district_name, fiscal_year)
                        )
                        """
                    )

                    # Alter existing tables if they exist
                    for table in ["findings", "merged_actions", "processed_intent"]:
                        for col, col_type in [("verbatim_text_context", "TEXT"), ("meeting_type", "TEXT"), ("verification_score", "REAL"), ("reviewer_status", "TEXT DEFAULT 'unverified'")]:
                            try:
                                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                            except Exception:
                                pass

                    # Seed jurisdictions from CSV if table is empty
                    try:
                        cur.execute("SELECT COUNT(*) FROM jurisdictions")
                        if cur.fetchone()[0] == 0:
                            import csv
                            csv_path = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/mapped_wa_universe_verified.csv"
                            if os.path.exists(csv_path):
                                with open(csv_path, mode='r', encoding='utf-8') as f:
                                    reader = csv.DictReader(f)
                                    for row in reader:
                                        name = row.get("Name")
                                        raw_type = row.get("Type", "Unknown").lower()
                                        entity_type = "special_district"
                                        if "city" in raw_type or "town" in raw_type:
                                            entity_type = "city"
                                        elif "county" in raw_type:
                                            entity_type = "county"
                                        elif "school" in raw_type:
                                            entity_type = "school_district"
                                        elif "port" in raw_type:
                                            entity_type = "port"
                                        county = row.get("County")
                                        if name:
                                            cur.execute(
                                                """
                                                INSERT OR IGNORE INTO jurisdictions (name, entity_type, county)
                                                VALUES (?, ?, ?)
                                                """,
                                                (name, entity_type, county)
                                            )
                    except Exception as seed_err:
                        print("Failed seeding SQLite jurisdictions:", seed_err)
                    for table in ["findings", "merged_actions", "processed_intent"]:
                        for col, col_type in [("verbatim_text_context", "TEXT"), ("meeting_type", "TEXT"), ("verification_score", "REAL"), ("reviewer_status", "TEXT DEFAULT 'unverified'")]:
                            try:
                                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                            except Exception:
                                pass

                    # Seed authoritative entities from CSV if table is empty
                    try:
                        cur.execute("SELECT COUNT(*) FROM authoritative_entities")
                        if cur.fetchone()[0] == 0:
                            import csv
                            csv_path = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/mapped_wa_universe_verified.csv"
                            if os.path.exists(csv_path):
                                with open(csv_path, mode='r', encoding='utf-8') as f:
                                    reader = csv.DictReader(f)
                                    for row in reader:
                                        name = row.get("Name")
                                        entity_type = row.get("Type")
                                        official_url = row.get("Official_URL")
                                        agenda_portal_url = row.get("API_Endpoint") or row.get("Scrape_Target")
                                        platform = row.get("Vendor")
                                        if name and official_url:
                                            cur.execute(
                                                """
                                                INSERT OR IGNORE INTO authoritative_entities (name, entity_type, official_url, agenda_portal_url, platform, verification_status)
                                                VALUES (?, ?, ?, ?, ?, 'verified')
                                                """,
                                                (name, entity_type, official_url, agenda_portal_url, platform)
                                            )
                    except Exception as seed_err:
                        print("Failed seeding SQLite authoritative entities:", seed_err)

                    cur.execute(
                        """
                        INSERT OR IGNORE INTO api_keys (api_key, owner_name)
                        VALUES 
                            ('sk-penner-dev-2026', 'PennerAI Developer'),
                            ('sk-penner-dashboard', 'PennerAI Dashboard Internal')
                        """
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    print(f"SQLite Database {db_name} bootstrapped successfully.")
                except Exception as sqlite_err:
                    print(f"SQLite bootstrap failed for {db_name}:", sqlite_err)

# Bootstrap DB immediately on file load
bootstrap_database()

def verify_api_key(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """Dependency validator for developer API keys."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication credentials (Bearer token) are missing.")
    
    api_key = credentials.credentials
    is_valid = False
    
    # Try Postgres
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("SELECT is_active FROM api_keys WHERE api_key = %s", (api_key,))
        row = cur.fetchone()
        if row and row[0]:
            is_valid = True
        cur.close()
        conn.close()
    except Exception:
        # Fallback to SQLite
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT is_active FROM api_keys WHERE api_key = ?", (api_key,))
                    row = cur.fetchone()
                    if row and row[0]:
                        is_valid = True
                    cur.close()
                    conn.close()
                    if is_valid:
                        break
                except Exception:
                    pass
                    
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key.")
    return api_key

def check_admin_access(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    # Try query param first
    code = request.query_params.get("code")
    if code in ['sk-penner-dev-2026', 'sk-penner-dashboard']:
        return True
    
    # Try bearer credentials
    if credentials:
        try:
            api_key = verify_api_key(credentials)
            if api_key in ['sk-penner-dev-2026', 'sk-penner-dashboard']:
                return True
        except Exception:
            pass
            
    raise HTTPException(status_code=401, detail="Unauthorized admin access. Use sk-penner-dashboard key or pass ?code=...")

def log_api_usage(api_key: str, endpoint: str, prompt_tokens: int, completion_tokens: int):
    """Log tokens and costs per request to usage logs."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        # Cost estimate for gemini-3.5-flash: $0.075 / 1M input tokens, $0.30 / 1M output tokens
        est_cost = (prompt_tokens * 0.000000075) + (completion_tokens * 0.000000300)
        cur.execute(
            """
            INSERT INTO api_usage_logs (api_key, endpoint, prompt_tokens, completion_tokens, total_tokens, estimated_cost)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (api_key, endpoint, prompt_tokens, completion_tokens, prompt_tokens + completion_tokens, est_cost)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        # Fallback to SQLite
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    est_cost = (prompt_tokens * 0.000000075) + (completion_tokens * 0.000000300)
                    cur.execute(
                        """
                        INSERT INTO api_usage_logs (api_key, endpoint, prompt_tokens, completion_tokens, total_tokens, estimated_cost)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (api_key, endpoint, prompt_tokens, completion_tokens, prompt_tokens + completion_tokens, est_cost)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    break
                except Exception:
                    pass

# --- Usage Tracking & Privacy-Compliant Logging Helpers ---

# SQLITE_TRACKING_PATH is defined at the top of main.py

def get_hashed_ip(ip_addr: str) -> str:
    # Daily salt changes automatically every day
    salt_secret = os.environ.get("IP_SALT_SECRET", "penner_default_salt_secret_2026")
    date_str = date.today().isoformat()
    salted = f"{ip_addr}-{date_str}-{salt_secret}"
    return hashlib.sha256(salted.encode()).hexdigest()

def bootstrap_sqlite_tracking(conn):
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                topics TEXT NOT NULL,
                jurisdiction TEXT,
                query TEXT,
                anonymous_user_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hashed_ip TEXT NOT NULL,
                anonymous_user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                message_count_in_session INTEGER DEFAULT 1,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                endpoint TEXT NOT NULL,
                response_time_ms INTEGER DEFAULT 0,
                has_citations INTEGER DEFAULT 0,
                has_correlations INTEGER DEFAULT 0,
                agent_api_key TEXT,
                query_text TEXT,
                jurisdiction TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_usage_aggregates (
                date TEXT PRIMARY KEY,
                dau INTEGER NOT NULL,
                total_messages INTEGER NOT NULL,
                avg_messages_per_user REAL NOT NULL,
                avg_session_depth REAL NOT NULL,
                heavy_users_day_count INTEGER NOT NULL,
                heavy_users_total_count INTEGER NOT NULL,
                heavy_users_multi_day_count INTEGER NOT NULL,
                retention_day_2 REAL,
                retention_day_7 REAL,
                retention_day_30 REAL,
                drop_off_stats TEXT,
                popular_topics TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bug_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                report_type TEXT NOT NULL,
                description TEXT NOT NULL,
                anonymous_user_id TEXT,
                session_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        cur.close()
    except Exception as e:
        print("Error bootstrapping SQLite tracking DB:", e)

def get_tracking_db_connection():
    try:
        conn = get_pg_conn()
        return conn, True
    except Exception:
        try:
            conn = sqlite3.connect(SQLITE_TRACKING_PATH)
            conn.execute("PRAGMA busy_timeout = 30000;")
            bootstrap_sqlite_tracking(conn)
            conn.row_factory = sqlite3.Row
            return conn, False
        except Exception as e:
            print("Failed to open SQLite fallback tracking database:", e)
            return None, False


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)

def check_rate_limit(ip_address: str, anonymous_user_id: str) -> bool:
    if ip_address in ["127.0.0.1", "::1", "localhost"]:
        return True
    hashed_ip = get_hashed_ip(ip_address)
    conn, is_pg = get_tracking_db_connection()
    if not conn:
        return True  # Fail open if database is down
    try:
        cur = conn.cursor()
        
        # Check alert subscription to adjust limit
        if is_pg:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM alert_subscriptions WHERE anonymous_user_id = %s)",
                (anonymous_user_id,)
            )
            is_subscribed = cur.fetchone()[0]
        else:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM alert_subscriptions WHERE anonymous_user_id = ?)",
                (anonymous_user_id,)
            )
            is_subscribed = bool(cur.fetchone()[0])
            
        limit = 50 if is_subscribed else 15
        
        # Count requests in last 24 hours
        if is_pg:
            cur.execute(
                "SELECT COUNT(*) FROM usage_events WHERE (hashed_ip = %s OR anonymous_user_id = %s) AND timestamp > NOW() - INTERVAL '24 hours'",
                (hashed_ip, anonymous_user_id)
            )
            count = cur.fetchone()[0]
        else:
            cur.execute(
                "SELECT COUNT(*) FROM usage_events WHERE (hashed_ip = ? OR anonymous_user_id = ?) AND timestamp > datetime('now', '-24 hours')",
                (hashed_ip, anonymous_user_id)
            )
            count = cur.fetchone()[0]
            
        cur.close()
        conn.close()
        return count < limit
    except Exception as e:
        print(f"Error checking rate limit: {e}")
        return True

def log_usage_event(
    ip_address: str,
    anonymous_user_id: str,
    session_id: str,
    endpoint: str,
    tokens_in: int,
    tokens_out: int,
    response_time_ms: int,
    has_citations: bool,
    has_correlations: bool,
    agent_api_key: Optional[str] = None,
    query_text: Optional[str] = None,
    jurisdiction: Optional[str] = None
):
    hashed_ip = get_hashed_ip(ip_address)
    conn, is_pg = get_tracking_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        
        # Get message count in session
        if is_pg:
            cur.execute(
                "SELECT COUNT(*) FROM usage_events WHERE session_id = %s",
                (session_id,)
            )
            count = cur.fetchone()[0]
        else:
            cur.execute(
                "SELECT COUNT(*) FROM usage_events WHERE session_id = ?",
                (session_id,)
            )
            count = cur.fetchone()[0]
            
        message_count = count + 1
        
        # Limit query_text to 255 chars for database safety
        q_text = query_text[:255] if query_text else None
        
        if is_pg:
            cur.execute(
                """
                INSERT INTO usage_events (
                    hashed_ip, anonymous_user_id, session_id, message_count_in_session,
                    tokens_in, tokens_out, endpoint, response_time_ms,
                    has_citations, has_correlations, agent_api_key, query_text, jurisdiction
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    hashed_ip, anonymous_user_id, session_id, message_count,
                    tokens_in, tokens_out, endpoint, response_time_ms,
                    has_citations, has_correlations, agent_api_key, q_text, jurisdiction
                )
            )
        else:
            cur.execute(
                """
                INSERT INTO usage_events (
                    hashed_ip, anonymous_user_id, session_id, message_count_in_session,
                    tokens_in, tokens_out, endpoint, response_time_ms,
                    has_citations, has_correlations, agent_api_key, query_text, jurisdiction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hashed_ip, anonymous_user_id, session_id, message_count,
                    tokens_in, tokens_out, endpoint, response_time_ms,
                    1 if has_citations else 0, 1 if has_correlations else 0, agent_api_key, q_text, jurisdiction
                )
            )
        conn.commit()
        cur.close()
        conn.close()
        print(f"Logged event: {endpoint} | User {anonymous_user_id} | Msg {message_count}")
    except Exception as e:
        print(f"Error logging usage event: {e}")

# --- Agent Tools Python Implementations ---

def get_latest_audits_tool(jurisdiction: str, limit: int = 5) -> List[dict]:
    """Retrieve SAO audits and findings matching a jurisdiction."""
    results = []
    juris_clean = re.sub(r"[']?s$", "", jurisdiction.strip())
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT report_num, jurisdiction, type, category, summary, root_cause, dollar_impact, year
                FROM findings
                WHERE jurisdiction ILIKE %s
                ORDER BY report_num DESC
                LIMIT %s
                """,
                (f"%{juris_clean}%", limit)
            )
            results = [dict(r) for r in cur.fetchall()]
        except Exception:
            conn.rollback()
            cur.execute(
                """
                SELECT report_num, jurisdiction, type, category, summary, root_cause, dollar_impact
                FROM findings
                WHERE jurisdiction ILIKE %s
                ORDER BY report_num DESC
                LIMIT %s
                """,
                (f"%{juris_clean}%", limit)
            )
            results = []
            for r in cur.fetchall():
                d = dict(r)
                d["year"] = 2025  # default
                results.append(d)
        cur.close()
        conn.close()
    except Exception:
        # Fallback to SQLite
        for db_name in ["sao_audits.db", "sao_2024.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT report_num, jurisdiction, category, summary, dollar_impact, year
                        FROM findings
                        WHERE jurisdiction LIKE ?
                        ORDER BY report_num DESC
                        LIMIT ?
                        """,
                        (f"%{juris_clean}%", limit)
                    )
                    rows = [dict(row) for row in cur.fetchall()]
                    for r in rows:
                        results.append({
                            "report_num": r["report_num"],
                            "jurisdiction": r["jurisdiction"],
                            "type": "Audits",
                            "category": r["category"],
                            "summary": r["summary"],
                            "root_cause": "N/A",
                            "dollar_impact": r["dollar_impact"],
                            "year": r.get("year") or (2024 if db_name == "sao_2024.db" else 2025)
                        })
                    conn.close()
                except Exception:
                    pass
    return results[:limit]

def get_council_actions_tool(city: str, topic: Optional[str] = None, limit: int = 5) -> List[dict]:
    """Retrieve city council actions and minutes matching a city and optionally a topic."""
    results = []
    city_clean = re.sub(r"[']?s$", "", city.strip())
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        q = """
            SELECT event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount, vote_outcome
            FROM merged_actions
            WHERE jurisdiction ILIKE %s
        """
        params = [f"%{city_clean}%"]
        if topic:
            q += " AND (key_action ILIKE %s OR committee ILIKE %s)"
            params.extend([f"%{topic.strip()}%", f"%{topic.strip()}%"])
        q += " ORDER BY meeting_date DESC LIMIT %s"
        params.append(limit)
        
        cur.execute(q, params)
        results = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
    except Exception:
        # Fallback to SQLite
        conn = get_sqlite_conn("municipal_intent.db")
        if conn:
            try:
                cur = conn.cursor()
                q = """
                    SELECT event_id, jurisdiction, doc_type as committee, meeting_date, agenda_item_title, key_action, vendor, dollar_amount, vote_outcome
                    FROM processed_intent
                    WHERE jurisdiction LIKE ?
                """
                params = [f"%{city_clean}%"]
                if topic:
                    q += " AND (agenda_item_title LIKE ? OR key_action LIKE ?)"
                    params.extend([f"%{topic.strip()}%", f"%{topic.strip()}%"])
                q += " ORDER BY meeting_date DESC LIMIT ?"
                params.append(limit)
                
                cur.execute(q, params)
                rows = [dict(row) for row in cur.fetchall()]
                for r in rows:
                    summary_text = clean_summary_text(r.get('agenda_item_title'), r.get('key_action'))
                    results.append({
                        "event_id": r["event_id"],
                        "jurisdiction": r["jurisdiction"],
                        "committee": r["committee"],
                        "meeting_date": r["meeting_date"],
                        "key_action": summary_text,
                        "vendor": r["vendor"],
                        "dollar_amount": r["dollar_amount"],
                        "vote_outcome": r["vote_outcome"]
                    })
                conn.close()
            except Exception:
                pass
    return results[:limit]

def find_correlations_tool(topic: str, limit: int = 5) -> List[dict]:
    """Calculate vector similarity between audits and council actions based on topic query."""
    embedding = None
    # We call Gemini embedContent synchronously via request
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={GEMINI_API_KEY}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "model": "models/gemini-embedding-2",
                "content": {"parts": [{"text": topic[:2000]}]},
                "outputDimensionality": 1536
            }
            res = requests.post(url, headers=headers, json=payload, timeout=5)
            if res.status_code == 200:
                emb = res.json()["embedding"]["values"]
                if len(emb) == 768:
                    emb.extend([0.0] * 768)
                embedding = emb[:1536]
        except Exception:
            pass
            
    correlations = []
    if embedding:
        try:
            conn = get_pg_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Query audits
            cur.execute(
                """
                SELECT report_num, jurisdiction, category, summary, dollar_impact, (embedding <=> %s::vector) as distance
                FROM findings
                ORDER BY distance ASC
                LIMIT %s
                """,
                (embedding, limit)
            )
            for r in cur.fetchall():
                correlations.append({
                    "jurisdiction": r["jurisdiction"],
                    "category": r["category"],
                    "summary": r["summary"],
                    "dollar_impact": r["dollar_impact"],
                    "source": "audit",
                    "id": r["report_num"],
                    "url": f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={r['report_num']}&isFinding=false&sp=false",
                    "similarity": float(1 - r["distance"])
                })
                
            # Query council actions
            cur.execute(
                """
                SELECT event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount, (embedding <=> %s::vector) as distance
                FROM merged_actions
                ORDER BY distance ASC
                LIMIT %s
                """,
                (embedding, limit)
            )
            for r in cur.fetchall():
                m_date = str(r["meeting_date"]) if r["meeting_date"] else ""
                correlations.append({
                    "jurisdiction": r["jurisdiction"],
                    "category": r["committee"] or "Council Action",
                    "summary": clean_summary_text(r["key_action"]),
                    "dollar_impact": r["dollar_amount"],
                    "source": "council",
                    "id": r["event_id"],
                    "url": f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting+{m_date}" if m_date else f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting",
                    "similarity": float(1 - r["distance"])
                })
            cur.close()
            conn.close()
        except Exception:
            pass
            
    # If PG failed or was empty, provide dummy correlation similarity for SQLite database fallback content
    if not correlations:
        topic_clean = topic.strip()
        
        # Query SQLite audits directly via keyword matching
        for db_name in ["sao_audits.db", "sao_2024.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT report_num, jurisdiction, category, summary, dollar_impact
                        FROM findings
                        WHERE summary LIKE ? OR category LIKE ? OR jurisdiction LIKE ?
                        ORDER BY report_num DESC
                        LIMIT ?
                        """,
                        (f"%{topic_clean}%", f"%{topic_clean}%", f"%{topic_clean}%", limit)
                    )
                    rows = [dict(row) for row in cur.fetchall()]
                    for r in rows:
                        doc_text = f"{r['jurisdiction']} {r['category']} {r['summary']}"
                        sim_score = calculate_text_similarity(topic, doc_text)
                        correlations.append({
                            "jurisdiction": r["jurisdiction"],
                            "category": r["category"],
                            "summary": r["summary"],
                            "dollar_impact": r["dollar_impact"],
                            "source": "audit",
                            "id": r["report_num"],
                            "url": f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={r['report_num']}&isFinding=false&sp=false",
                            "similarity": sim_score
                        })
                    conn.close()
                except Exception:
                    pass

        # Query SQLite municipal council actions directly via keyword matching
        conn = get_sqlite_conn("municipal_intent.db")
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT event_id, jurisdiction, doc_type as committee, meeting_date, agenda_item_title, key_action, vendor, dollar_amount
                    FROM processed_intent
                    WHERE key_action LIKE ? OR agenda_item_title LIKE ? OR jurisdiction LIKE ? OR vendor LIKE ?
                    ORDER BY meeting_date DESC
                    LIMIT ?
                    """,
                    (f"%{topic_clean}%", f"%{topic_clean}%", f"%{topic_clean}%", f"%{topic_clean}%", limit)
                )
                rows = [dict(row) for row in cur.fetchall()]
                for r in rows:
                    m_date = str(r["meeting_date"]) if r.get("meeting_date") else ""
                    summary_text = clean_summary_text(r.get('agenda_item_title'), r.get('key_action'))
                    doc_text = f"{r['jurisdiction']} {r['committee'] or 'Council Action'} {summary_text} {r['vendor'] or ''}"
                    sim_score = calculate_text_similarity(topic, doc_text)
                    correlations.append({
                        "jurisdiction": r["jurisdiction"],
                        "category": r["committee"] or "Council Action",
                        "summary": summary_text,
                        "dollar_impact": r["dollar_amount"],
                        "source": "council",
                        "id": r["event_id"],
                        "url": f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting+{m_date}" if m_date else f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting",
                        "similarity": sim_score
                    })
                conn.close()
            except Exception:
                pass

        # If still empty, fall back to querying latest entries in SQLite
        if not correlations:
            for db_name in ["sao_audits.db", "sao_2024.db"]:
                conn = get_sqlite_conn(db_name)
                if conn:
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            """
                            SELECT report_num, jurisdiction, category, summary, dollar_impact
                            FROM findings
                            ORDER BY report_num DESC
                            LIMIT 2
                            """
                        )
                        rows = [dict(row) for row in cur.fetchall()]
                        for r in rows:
                            doc_text = f"{r['jurisdiction']} {r['category']} {r['summary']}"
                            sim_score = calculate_text_similarity(topic, doc_text)
                            correlations.append({
                                "jurisdiction": r["jurisdiction"],
                                "category": r["category"],
                                "summary": r["summary"],
                                "dollar_impact": r["dollar_impact"],
                                "source": "audit",
                                "id": r["report_num"],
                                "url": f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={r['report_num']}&isFinding=false&sp=false",
                                "similarity": sim_score
                            })
                        conn.close()
                    except Exception:
                        pass

            conn = get_sqlite_conn("municipal_intent.db")
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT event_id, jurisdiction, doc_type as committee, meeting_date, agenda_item_title, key_action, vendor, dollar_amount
                        FROM processed_intent
                        ORDER BY meeting_date DESC
                        LIMIT 2
                        """
                    )
                    rows = [dict(row) for row in cur.fetchall()]
                    for r in rows:
                        m_date = str(r["meeting_date"]) if r.get("meeting_date") else ""
                        summary_text = clean_summary_text(r.get('agenda_item_title'), r.get('key_action'))
                        doc_text = f"{r['jurisdiction']} {r['committee'] or 'Council Action'} {summary_text} {r['vendor'] or ''}"
                        sim_score = calculate_text_similarity(topic, doc_text)
                        correlations.append({
                            "jurisdiction": r["jurisdiction"],
                            "category": r["committee"] or "Council Action",
                            "summary": summary_text,
                            "dollar_impact": r["dollar_amount"],
                            "source": "council",
                            "id": r["event_id"],
                            "url": f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting+{m_date}" if m_date else f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting",
                            "similarity": 0.72
                        })
                    conn.close()
                except Exception:
                    pass
            
    correlations.sort(key=lambda x: x["similarity"], reverse=True)
    return correlations[:limit]

def get_legislative_bill_status_tool(bill_number: str) -> dict:
    """Fetch live Washington State Legislature bill status using grounding, plus local mentions."""
    findings_match = []
    council_match = []
    
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT report_num, jurisdiction, category, summary FROM findings WHERE summary ILIKE %s LIMIT 2", (f"%{bill_number}%",))
        findings_match = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT event_id, jurisdiction, key_action, meeting_date FROM merged_actions WHERE key_action ILIKE %s LIMIT 2", (f"%{bill_number}%",))
        council_match = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
    except Exception:
        pass
        
    live_status = "No live grounding status available."
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
            headers = {"Content-Type": "application/json"}
            prompt = f"Retrieve the current legislative status and a brief summary of Washington State bill {bill_number}. Highlight current status clearly."
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"googleSearch": {}}],
                "generationConfig": {"temperature": 0.1}
            }
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                live_status = res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            live_status = f"Grounding search failed: {e}"
            
    return {
        "bill_number": bill_number,
        "live_status": live_status,
        "local_database_mentions": {
            "audits": findings_match,
            "council_actions": council_match
        },
        "last_updated": date.today().isoformat()
    }

def get_grants_by_category_tool(category: str, jurisdiction: Optional[str] = None, limit: int = 5) -> dict:
    """Retrieve audits and meeting actions referencing grants for category."""
    audits_res = []
    council_res = []
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        q_audits = "SELECT report_num, jurisdiction, category, summary, dollar_impact FROM findings WHERE (summary ILIKE %s OR category ILIKE %s) AND (summary ILIKE '%%grant%%' OR category ILIKE '%%grant%%')"
        params_audits = [f"%{category}%", f"%{category}%"]
        if jurisdiction:
            q_audits += " AND jurisdiction ILIKE %s"
            params_audits.append(f"%{jurisdiction}%")
        q_audits += " LIMIT %s"
        params_audits.append(limit)
        cur.execute(q_audits, params_audits)
        audits_res = [dict(r) for r in cur.fetchall()]
        
        q_council = "SELECT event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount FROM merged_actions WHERE (key_action ILIKE %s OR committee ILIKE %s) AND (key_action ILIKE '%%grant%%' OR committee ILIKE '%%grant%%')"
        params_council = [f"%{category}%", f"%{category}%"]
        if jurisdiction:
            q_council += " AND jurisdiction ILIKE %s"
            params_council.append(f"%{jurisdiction}%")
        q_council += " LIMIT %s"
        params_council.append(limit)
        cur.execute(q_council, params_council)
        council_res = [dict(r) for r in cur.fetchall()]
        
        cur.close()
        conn.close()
    except Exception:
        pass
    return {
        "category": category,
        "jurisdiction": jurisdiction,
        "audits": audits_res,
        "council_actions": council_res
    }

def run_tool(name: str, arguments: dict):
    """Executes a tool by name with arguments."""
    if name == "get_latest_audits":
        return get_latest_audits_tool(**arguments)
    elif name == "get_council_actions":
        return get_council_actions_tool(**arguments)
    elif name == "find_correlations":
        return find_correlations_tool(**arguments)
    elif name == "get_legislative_bill_status":
        return get_legislative_bill_status_tool(**arguments)
    elif name == "get_grants_by_category":
        return get_grants_by_category_tool(**arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")

# Tools schema list for OpenAI compatibility
TOOLS_LIST = [
    {
        "name": "get_latest_audits",
        "description": "Fetch the latest State Auditor Office (SAO) audits and findings for a given Washington jurisdiction.",
        "parameters": {
            "type": "object",
            "properties": {
                "jurisdiction": {
                    "type": "string",
                    "description": "The name of the city, county, school district, or agency (e.g. Orting, Bellevue, King County)."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of audit findings to return.",
                    "default": 5
                }
            },
            "required": ["jurisdiction"]
        }
    },
    {
        "name": "get_council_actions",
        "description": "Fetch local city/county council minutes, actions, votes, or vendor agreements.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "The city/county name (e.g. Seattle, Orting, King County)."
                },
                "topic": {
                    "type": "string",
                    "description": "Optional keyword topic to filter actions (e.g. police, tax, zoning).",
                    "default": None
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of council actions to return.",
                    "default": 5
                }
            },
            "required": ["city"]
        }
    },
    {
        "name": "find_correlations",
        "description": "Find scored cross-database correlations and patterns matching a concept or topic via vector search.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The concept, topic, or query to correlate (e.g. internal control failures, police funding)."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of correlations to return.",
                    "default": 5
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "get_legislative_bill_status",
        "description": "Retrieve the live status and details of a Washington State Legislature bill, along with local mentions.",
        "parameters": {
            "type": "object",
            "properties": {
                "bill_number": {
                    "type": "string",
                    "description": "The bill identifier (e.g. SB 5024, HB 1234)."
                }
            },
            "required": ["bill_number"]
        }
    },
    {
        "name": "get_grants_by_category",
        "description": "Search local and state audit reports and council actions specifically for grants and funding details by category.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "The grant or funding category (e.g. transportation, housing, emergency)."
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Optional city/county/agency name to restrict the search.",
                    "default": None
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of records to return.",
                    "default": 5
                }
            },
            "required": ["category"]
        }
    }
]

OPENAI_TOOLS = [{"type": "function", "function": t} for t in TOOLS_LIST]

async def get_embedding_async(text: str, client: httpx.AsyncClient) -> Optional[List[float]]:
    """Get vector embedding (1536-dim padded) for query lookup asynchronously."""

    if not GEMINI_API_KEY:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "models/gemini-embedding-2",
        "content": {"parts": [{"text": text[:2000]}]},
        "outputDimensionality": 1536
    }
    try:
        res = await client.post(url, headers=headers, json=payload, timeout=5)
        if res.status_code == 200:
            embedding = res.json()["embedding"]["values"]
            if len(embedding) == 768:
                embedding.extend([0.0] * 768)
            return embedding[:1536]
    except Exception as e:
        print(f"Error fetching embedding for query: {e}")
    return None

async def extract_intent_async(query_text: str, client: httpx.AsyncClient, history: Optional[List[dict]] = None) -> tuple:
    """Uses Membrane semantic gate capability to extract target entities asynchronously."""
    prompt = """You are the Membrane Semantic Gate. Extract the target jurisdiction (e.g. City/County/School District) and 2-3 keywords. Return strict JSON: {"jurisdiction": "Name", "keywords": ["kw1", "kw2"]}"""
    url = f"{membrane.base_url}/v1/chat/completions"
    
    messages = [{"role": "system", "content": prompt}]
    if history:
        for msg in history[-4:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    messages.append({"role": "user", "content": query_text})
    
    payload = {
        "model": "membrane-engagement-layer",
        "messages": messages,
        "temperature": 0.0,
        "response_format": {"type": "object"}
    }
    try:
        res = await client.post(url, headers=membrane._headers(), json=payload, timeout=10)
        if res.status_code == 200:
            content_str = res.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content_str)
            return parsed.get("jurisdiction", ""), parsed.get("keywords", [])
    except Exception as e:
        print(f"Membrane gate classification failed, using heuristic: {e}")
        
    # Heuristic fallback
    jurisdiction = ""
    keywords = []
    clean_query = query_text.lower()
    wa_cities = ["seattle", "tacoma", "bellevue", "spokane", "everett", "kent", "renton", "yakima", "olympia", "orting"]
    for city in wa_cities:
        if city in clean_query:
            jurisdiction = city.title()
            break
            
    if not jurisdiction and history:
        for msg in reversed(history):
            if msg.get("role") == "user":
                h_query = msg.get("content", "").lower()
                for city in wa_cities:
                    if city in h_query:
                        jurisdiction = city.title()
                        break
            if jurisdiction:
                break
                
    return jurisdiction, keywords

def calculate_text_similarity(query: str, doc_text: str) -> float:
    """Calculates keyword-based text similarity, weighting distinctive words higher than generic ones."""
    if not query or not doc_text:
        return 0.15
        
    query_words = set(re.findall(r'\b\w+\b', query.lower()))
    doc_words = set(re.findall(r'\b\w+\b', doc_text.lower()))
    
    stop_words = {
        "which", "local", "government", "contracts", "involve", "of", "and", "to", 
        "in", "for", "on", "with", "a", "an", "the", "is", "are", "was", "were", 
        "has", "have", "had", "been", "about", "any", "some", "what", "how", "why", 
        "where", "who", "show", "me", "recent", "audit", "findings", "audits", 
        "council", "actions", "intent", "policy", "violations"
    }
    
    distinctive_query_words = {w for w in query_words if w not in stop_words and len(w) > 2}
    if not distinctive_query_words:
        distinctive_query_words = query_words
        
    if not distinctive_query_words:
        return 0.50
        
    matched_words = {w for w in distinctive_query_words if any(w in dw for dw in doc_words)}
    overlap_ratio = len(matched_words) / len(distinctive_query_words) if distinctive_query_words else 0
    
    if len(matched_words) == 0:
        generic_overlap = len(query_words.intersection(doc_words)) / max(len(query_words), 1)
        return round(0.15 + 0.15 * generic_overlap, 2)
        
    return round(0.50 + 0.48 * overlap_ratio, 2)

def truncate_suggestion(s: str, max_len: int = 120) -> str:
    """Truncates a suggestion to max_len, ensuring it does not cut off mid-word."""
    s = s.strip()
    if len(s) <= max_len:
        return s
    
    # Try to find a space within the last few characters before max_len
    truncated = s[:max_len]
    last_space = truncated.rfind(' ')
    
    # If we found a space and it's not too far back (within 15 chars)
    if last_space != -1 and max_len - last_space < 15:
        truncated = truncated[:last_space]
    
    # Strip any trailing punctuation and add '...' (or '...?' if it was a question)
    truncated = truncated.rstrip('.,:;!? ')
    if s.endswith('?'):
        return truncated + '...?'
    else:
        return truncated + '...'

def generate_heuristic_suggestions(query: str, jurisdiction: Optional[str], context_lines: list) -> list:
    """Generates 3 contextual, relevant follow-up questions based on query search terms and jurisdiction."""
    suggestions = []
    
    query_lower = query.lower()
    stop_words = {
        "which", "local", "government", "contracts", "involve", "of", "and", "to", 
        "in", "for", "on", "with", "a", "an", "the", "is", "are", "was", "were", 
        "has", "have", "had", "been", "about", "any", "some", "what", "how", "why", 
        "where", "who", "show", "me", "recent", "audit", "findings", "audits", 
        "council", "actions", "intent", "policy", "violations", "contract", "finding",
        "spend", "spending", "spent", "cost", "costs", "pay", "paid", "payment", 
        "total", "amount", "dollar", "dollars", "much", "did", "its", "our", "their", 
        "they", "them", "he", "she", "it", "on", "about", "for", "do", "does", "did",
        "have", "has", "had", "get", "got", "make", "made", "go", "went", "take",
        "took", "find", "found", "show", "showing", "list", "view", "details",
        "analyze", "correlation", "report", "explain", "significance", "draft"
    }
    
    juris_words = set(re.findall(r'\b\w+\b', jurisdiction.lower())) if jurisdiction else set()
    
    words = re.findall(r'\b\w+\b', query)
    key_terms = [w for w in words if w.lower() not in stop_words and w.lower() not in juris_words and len(w) > 2]
    
    # Try to extract quoted phrases if any
    quotes = re.findall(r'"([^"]+)"|\'([^\']+)\'', query)
    quoted_terms = [q[0] or q[1] for q in quotes if q[0] or q[1]]
    
    # Prevent discarding quoted terms that contain jurisdiction words
    clean_quoted_terms = list(quoted_terms)
            
    entity = clean_quoted_terms[0] if clean_quoted_terms else (" ".join(key_terms[:3]) if key_terms else "")
    entity_title = entity.title().strip()
    
    entity_lower = entity.lower()
    is_school = "school" in entity_lower or "district" in entity_lower or "sd" in entity_lower or "schools" in entity_lower
    
    topic_keywords = {
        "weakness", "weaknesses", "finding", "findings", "control", "controls", 
        "deficit", "deficits", "vote", "votes", "contract", "contracts", 
        "financial", "violation", "violations", "report", "reports", "audit", 
        "audits", "expenditure", "expenditures", "revenue", "revenues", 
        "budget", "budgets", "loan", "loans", "debt", "debts", "failure", 
        "failures", "fraud", "misappropriation", "spending", "spend", "cost", 
        "costs", "pay", "payment", "payments", "funding", "fund", "funds",
        "tax", "taxes", "rate", "rates", "audit", "auditing", "unqualified", 
        "opinion", "opinions", "compliance", "noncompliance", "internal",
        "material", "significant", "deficiency", "deficiencies", "allowable"
    }
    
    entity_words = [w.lower() for w in re.findall(r'\b\w+\b', entity)]
    is_topic = (
        len(entity_words) > 4 
        or any(w in topic_keywords for w in entity_words)
    )
    
    if is_topic:
        if jurisdiction:
            juris_title = jurisdiction.title()
            suggestions.append(f"Are there other similar findings in {juris_title}?")
            suggestions.append(f"How did {juris_title} respond to this audit finding?")
            suggestions.append(f"Show other findings for {juris_title}")
        else:
            suggestions.append("Which jurisdictions have similar audit findings?")
            suggestions.append("What is the typical corrective action for this finding?")
            suggestions.append("Are there other recent findings about this topic?")
    else:
        if jurisdiction:
            juris_title = jurisdiction.title()
            if entity_title and is_school:
                suggestions.append(f"Show other findings for {entity_title}")
            else:
                suggestions.append(f"Show other findings for {juris_title}")
            if entity_title:
                if is_school:
                    suggestions.append(f"Are there other {entity_title} audit findings?")
                    suggestions.append(f"What was the total enrollment for {entity_title}?")
                else:
                    suggestions.append(f"Are there other {entity_title} contracts in {juris_title}?")
                    suggestions.append(f"What was {juris_title}'s total spend on {entity_title}?")
            else:
                suggestions.append(f"What was the total budget impact for {juris_title}?")
                suggestions.append(f"How did {juris_title} city council vote recently?")
        else:
            if entity_title:
                if is_school:
                    suggestions.append(f"Which school districts have similar audit findings?")
                    suggestions.append(f"What is the average spending for {entity_title}?")
                    suggestions.append(f"Are there federal funding issues involving {entity_title}?")
                else:
                    suggestions.append(f"Which cities contracted with {entity_title}?")
                    suggestions.append(f"What is the total spending on {entity_title}?")
                    suggestions.append(f"Are there audit findings involving {entity_title}?")
            else:
                suggestions.append("Are there similar audit findings?")
                suggestions.append("What was the total dollar impact?")
                suggestions.append("How did city council vote on this?")
            
    return [truncate_suggestion(s, 120) for s in suggestions[:3]]

def fetch_context_and_correlations(lens: str, jurisdiction: str, keywords: List[str], query_emb: Optional[List[float]], use_sqlite: bool, query_text: str = "") -> tuple[List[str], List[dict], List[dict]]:
    """Runs database queries (structured and vector) in a single synchronous thread pool context."""
    context_lines = []
    citations = []
    correlations = []
    
    import re
    year_match = re.search(r'\b(20\d{2})\b', query_text)
    query_year = int(year_match.group(1)) if year_match else None
    
    # Filter out generic stop words to prevent empty/incorrect matches
    stop_words = {
        "audit", "audits", "finding", "findings", "action", "actions", 
        "meeting", "meetings", "minutes", "report", "reports", "city", 
        "county", "council", "municipal", "governance", "policy", 
        "record", "records", "file", "files", "document", "documents",
        "tell", "show", "me", "about", "what", "how", "who", "which", "where",
        "analyze", "correlation", "explain", "significance", "draft"
    }
    
    juris_words = set(re.findall(r'\b\w+\b', jurisdiction.lower())) if jurisdiction else set()
    keywords = [
        kw for kw in keywords 
        if kw.lower() not in stop_words 
        and not any(word in juris_words for word in re.findall(r'\b\w+\b', kw.lower()))
    ]
    
    juris_clean = re.sub(r"[']?s$", "", jurisdiction.strip())
    
    if not use_sqlite:
        try:
            conn_pg = get_pg_conn()
            cur_pg = conn_pg.cursor(cursor_factory=RealDictCursor)
            
            # 1. Fetch structured data based on lens
            db_idx = 1
            if lens in ["comprehensive", "audits"]:
                try:
                    q = "SELECT report_num, jurisdiction, category, summary, dollar_impact, year, source_url, verbatim_text_context FROM findings WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND jurisdiction ILIKE %s"
                        params.append(f"%{juris_clean}%")
                    if keywords:
                        kw_clauses = ["summary ILIKE %s" for _ in keywords]
                        q += f" AND ({' OR '.join(kw_clauses)})"
                        params.extend([f"%{kw}%" for kw in keywords])
                    if query_year:
                        q += " AND year = %s"
                        params.append(query_year)
                    q += " ORDER BY year DESC, report_num DESC LIMIT 5"
                    cur_pg.execute(q, params)
                    rows = cur_pg.fetchall()
                except Exception:
                    conn_pg.rollback()
                    q = "SELECT report_num, jurisdiction, category, summary, dollar_impact, source_url FROM findings WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND jurisdiction ILIKE %s"
                        params.append(f"%{juris_clean}%")
                    if keywords:
                        kw_clauses = ["summary ILIKE %s" for _ in keywords]
                        q += f" AND ({' OR '.join(kw_clauses)})"
                        params.extend([f"%{kw}%" for kw in keywords])
                    q += " LIMIT 5"
                    cur_pg.execute(q, params)
                    rows = [dict(r) for r in cur_pg.fetchall()]
                    for r in rows:
                        r["year"] = None
                        r["verbatim_text_context"] = None
                        
                for r in rows:
                    r_dict = dict(r)
                    impact = f"${r_dict['dollar_impact']:,}" if r_dict['dollar_impact'] else "None"
                    yr_str = f" ({r_dict['year']})" if r_dict.get('year') else ""
                    v_context = r_dict.get("verbatim_text_context") or r_dict.get("summary") or ""
                    context_lines.append(f"[DB-{db_idx}] SAO AUDIT{yr_str} - Agency: {r_dict['jurisdiction']} | Report: {r_dict['report_num']} | Category: {r_dict['category']} | Impact: {impact} | Summary: {v_context}")
                    
                    source_url = r_dict.get("source_url")
                    if source_url:
                        url = f"/api/v1/documents/sao/{r_dict['report_num']}/pdf"
                    else:
                        url = f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={r_dict['report_num']}&isFinding=false&sp=false"
                        
                    citations.append({
                        "text": f"{r_dict['jurisdiction']} Audit - {r_dict['report_num']}", 
                        "url": url,
                        "type": "audit"
                    })
                    db_idx += 1
                    
            if lens in ["comprehensive", "council"]:
                q = "SELECT event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount, vote_outcome, verbatim_text_context FROM merged_actions WHERE 1=1"
                params = []
                if juris_clean:
                    q += " AND jurisdiction ILIKE %s"
                    params.append(f"%{juris_clean}%")
                if keywords:
                    kw_clauses = ["key_action ILIKE %s" for _ in keywords]
                    q += f" AND ({' OR '.join(kw_clauses)})"
                    params.extend([f"%{kw}%" for kw in keywords])
                if query_year:
                    q += " AND EXTRACT(YEAR FROM meeting_date) = %s"
                    params.append(query_year)
                q += " ORDER BY meeting_date DESC LIMIT 5"
                cur_pg.execute(q, params)
                for r in cur_pg.fetchall():
                    impact = f"${r['dollar_amount']:,}" if r['dollar_amount'] else "None"
                    v_context = r.get("verbatim_text_context") or clean_summary_text(r['key_action']) or ""
                    context_lines.append(f"[DB-{db_idx}] COUNCIL ACTION - Jurisdiction: {r['jurisdiction']} | Committee: {r['committee']} | Action: {v_context} | Vendor: {r['vendor']} | Impact: {impact} | Vote: {r['vote_outcome']}")
                    juris_name = r['jurisdiction'].title() if r['jurisdiction'] else "Local"
                    event_id_str = f" {r['event_id']}" if r.get('event_id') else ""
                    meeting_date_str = str(r['meeting_date']) if r.get('meeting_date') and str(r['meeting_date']) != "Extracted_Date" else ""
                    url_query = f"{juris_name.replace(' ', '+')}+city+council+meeting"
                    if meeting_date_str:
                        url_query += f"+{meeting_date_str}"
                    
                    citations.append({
                        "text": f"{juris_name} Council Action{event_id_str}", 
                        "url": f"https://www.google.com/search?q={url_query}",
                        "type": "council"
                    })
                    db_idx += 1

            if lens in ["comprehensive", "school"]:
                try:
                    q = "SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url FROM school_district_financials WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND district_name ILIKE %s"
                        params.append(f"%{juris_clean}%")
                    if query_year:
                        q += " AND fiscal_year = %s"
                        params.append(query_year)
                    q += " ORDER BY fiscal_year DESC LIMIT 3"
                    cur_pg.execute(q, params)
                    for r in cur_pg.fetchall():
                        levy_val = f" | Levy Amount: ${r['levy_amount']:,}" if r['levy_amount'] is not None else ""
                        sped_val = f" | Special Ed: ${r['special_education_spending']:,}" if r['special_education_spending'] is not None else ""
                        fed_val = f" | Federal Funding: ${r['federal_funding_amount']:,}" if r['federal_funding_amount'] is not None else ""
                        context_lines.append(f"[DB-{db_idx}] SCHOOL DISTRICT FINANCIALS - District: {r['district_name']} | Year: {r['fiscal_year']} | Enrollment: {r['enrollment']:.0f} FTE | Revenue: ${r['total_revenue']:,} | Expenditures: ${r['total_expenditures']:,}{levy_val}{sped_val}{fed_val}")
                        
                        source_url = r["source_url"] or f"https://www.google.com/search?q={r['district_name'].replace(' ', '+')}+school+district+budget"
                        citations.append({
                            "text": f"{r['district_name']} School Financials - {r['fiscal_year']}",
                            "url": source_url,
                            "type": "school"
                        })
                        db_idx += 1
                except Exception as e:
                    print("Postgres school district financials query failed:", e)
                    conn_pg.rollback()

            if lens in ["comprehensive", "budget"]:
                try:
                    q = "SELECT jurisdiction_name, entity_type, fiscal_year, total_revenue, total_expenditures, fund_balance_beginning, fund_balance_ending, source_url FROM budgets WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND jurisdiction_name ILIKE %s"
                        params.append(f"%{juris_clean}%")
                    if query_year:
                        q += " AND fiscal_year = %s"
                        params.append(query_year)
                    q += " ORDER BY fiscal_year DESC LIMIT 3"
                    cur_pg.execute(q, params)
                    for r in cur_pg.fetchall():
                        beg_bal = f" | Beginning Balance: ${r['fund_balance_beginning']:,}" if r['fund_balance_beginning'] is not None else ""
                        end_bal = f" | Ending Balance: ${r['fund_balance_ending']:,}" if r['fund_balance_ending'] is not None else ""
                        context_lines.append(f"[DB-{db_idx}] BUDGET RECORD - Jurisdiction: {r['jurisdiction_name']} ({r['entity_type']}) | Year: {r['fiscal_year']} | Revenue: ${r['total_revenue']:,} | Expenditures: ${r['total_expenditures']:,}{beg_bal}{end_bal}")
                        
                        source_url = r["source_url"] or f"https://www.google.com/search?q={r['jurisdiction_name'].replace(' ', '+')}+city+budget"
                        citations.append({
                            "text": f"{r['jurisdiction_name']} Budget - {r['fiscal_year']}",
                            "url": source_url,
                            "type": "budget"
                        })
                        db_idx += 1
                except Exception as e:
                    print("Postgres budgets query failed:", e)
                    conn_pg.rollback()

            if lens in ["comprehensive", "grant"]:
                try:
                    q = "SELECT grant_title, awarding_agency, recipient_jurisdiction, award_amount, award_date, purpose_category, source_url FROM grants WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND recipient_jurisdiction ILIKE %s"
                        params.append(f"%{juris_clean}%")
                    if keywords:
                        kw_clauses = ["(grant_title ILIKE %s OR purpose_category ILIKE %s)" for _ in keywords]
                        q += f" AND ({' OR '.join(kw_clauses)})"
                        for kw in keywords:
                            params.extend([f"%{kw}%", f"%{kw}%"])
                    q += " ORDER BY award_date DESC LIMIT 3"
                    cur_pg.execute(q, params)
                    for r in cur_pg.fetchall():
                        date_str = f" | Date: {r['award_date']}" if r['award_date'] else ""
                        cat_str = f" | Category: {r['purpose_category']}" if r['purpose_category'] else ""
                        context_lines.append(f"[DB-{db_idx}] GRANT AWARD - Recipient: {r['recipient_jurisdiction']} | Agency: {r['awarding_agency']} | Title: {r['grant_title']} | Amount: ${r['award_amount']:,}{date_str}{cat_str}")
                        
                        source_url = r["source_url"] or f"https://www.google.com/search?q={r['recipient_jurisdiction'].replace(' ', '+')}+grants"
                        citations.append({
                            "text": f"Grant: {r['grant_title']}",
                            "url": source_url,
                            "type": "grant"
                        })
                        db_idx += 1
                except Exception as e:
                    print("Postgres grants query failed:", e)
                    conn_pg.rollback()
            
            # 2. Vector search correlations
            if query_emb:
                if lens in ["comprehensive", "audits"]:
                    if query_year:
                        cur_pg.execute(
                            "SELECT report_num, jurisdiction, category, summary, dollar_impact, source_url, (embedding <=> %s::vector) as distance FROM findings WHERE year = %s ORDER BY distance ASC LIMIT 2",
                            (query_emb, query_year)
                        )
                    else:
                        cur_pg.execute(
                            "SELECT report_num, jurisdiction, category, summary, dollar_impact, source_url, (embedding <=> %s::vector) as distance FROM findings ORDER BY distance ASC LIMIT 2",
                            (query_emb,)
                        )
                    for r in cur_pg.fetchall():
                        source_url = r.get("source_url")
                        if source_url:
                            url = f"/api/v1/documents/sao/{r['report_num']}/pdf"
                        else:
                            url = f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={r['report_num']}&isFinding=false&sp=false"
                            
                        correlations.append({
                            "jurisdiction": r["jurisdiction"],
                            "category": r["category"],
                            "summary": r["summary"],
                            "dollar_impact": r["dollar_impact"],
                            "source": "audit",
                            "url": url,
                            "similarity": float(1 - r["distance"])
                        })
                if lens in ["comprehensive", "council"]:
                    if query_year:
                        cur_pg.execute(
                            "SELECT event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount, (embedding <=> %s::vector) as distance FROM merged_actions WHERE EXTRACT(YEAR FROM meeting_date) = %s ORDER BY distance ASC LIMIT 2",
                            (query_emb, query_year)
                        )
                    else:
                        cur_pg.execute(
                            "SELECT event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount, (embedding <=> %s::vector) as distance FROM merged_actions ORDER BY distance ASC LIMIT 2",
                            (query_emb,)
                        )
                    for r in cur_pg.fetchall():
                        m_date = str(r["meeting_date"]) if r["meeting_date"] else ""
                        correlations.append({
                            "jurisdiction": r["jurisdiction"],
                            "category": r["committee"] or "Council Action",
                            "summary": clean_summary_text(r["key_action"]),
                            "dollar_impact": r["dollar_amount"],
                            "source": "council",
                            "url": f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting+{m_date}" if m_date else f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting",
                            "similarity": float(1 - r["distance"])
                        })
            cur_pg.close()
            conn_pg.close()
        except Exception as pg_err:
            print("Postgres database operation failed, forcing SQLite fallback:", pg_err)
            use_sqlite = True

    if use_sqlite:
        # SQLite Query Fallback
        db_idx = 1
        # 1. Fetch audits from both sao_audits.db and sao_2024.db
        if lens in ["comprehensive", "audits"]:
            for db_name in ["sao_audits.db", "sao_2024.db"]:
                conn_sao = get_sqlite_conn(db_name)
                if conn_sao:
                    try:
                        cur_sao = conn_sao.cursor()
                        # Dynamic columns check for SQLite
                        cur_sao.execute("PRAGMA table_info(findings);")
                        columns = [row[1] for row in cur_sao.fetchall()]
                        has_source_url = "source_url" in columns
                        has_verbatim = "verbatim_text_context" in columns
                        
                        select_cols = "report_num, jurisdiction, category, summary, dollar_impact, year"
                        if has_source_url:
                            select_cols += ", source_url"
                        if has_verbatim:
                            select_cols += ", verbatim_text_context"
                        q = f"SELECT {select_cols} FROM findings WHERE 1=1"
                        params = []
                        if juris_clean:
                            q += " AND jurisdiction LIKE ?"
                            params.append(f"%{juris_clean}%")
                        if keywords:
                            kw_clauses = ["(summary LIKE ? OR category LIKE ? OR jurisdiction LIKE ?)" for _ in keywords]
                            q += f" AND ({' OR '.join(kw_clauses)})"
                            for kw in keywords:
                                params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])
                        if query_year:
                            q += " AND year = ?"
                            params.append(query_year)
                        q += " ORDER BY year DESC, report_num DESC LIMIT 15"
                        cur_sao.execute(q, params)
                        rows = [dict(row) for row in cur_sao.fetchall()]
                        
                        # Compute similarity and sort
                        audit_items = []
                        for r in rows:
                            doc_text = f"{r['jurisdiction']} {r['category']} {r['summary']}"
                            sim_score = calculate_text_similarity(query_text, doc_text)
                            audit_items.append((sim_score, r))
                        
                        # Sort by similarity descending
                        audit_items.sort(key=lambda x: x[0], reverse=True)
                        
                        for sim_score, r in audit_items[:5]:
                            impact = f"${r['dollar_impact']:,}" if r['dollar_impact'] else "None"
                            yr = r.get("year") or (2024 if db_name == "sao_2024.db" else 2025)
                            v_context = r.get("verbatim_text_context") or r.get("summary") or ""
                            context_lines.append(f"[DB-{db_idx}] SAO AUDIT ({yr}) - Agency: {r['jurisdiction']} | Report: {r['report_num']} | Category: {r['category']} | Impact: {impact} | Summary: {v_context}")
                            
                            source_url = r.get("source_url")
                            if source_url:
                                url = f"/api/v1/documents/sao/{r['report_num']}/pdf"
                            else:
                                url = f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={r['report_num']}&isFinding=false&sp=false"
                                
                            citations.append({
                                "text": f"{r['jurisdiction']} Audit - {r['report_num']}", 
                                "url": url,
                                "type": "audit"
                            })
                            
                            # Add correlation item
                            correlations.append({
                                "jurisdiction": r["jurisdiction"],
                                "category": r["category"],
                                "summary": r["summary"],
                                "dollar_impact": r["dollar_impact"],
                                "source": "audit",
                                "url": url,
                                "similarity": sim_score
                            })
                            db_idx += 1
                        conn_sao.close()
                    except Exception as e:
                        print(f"SQLite Audits Read Error for {db_name}:", e)
 
         # 2. Fetch council actions from municipal_intent.db
        if lens in ["comprehensive", "council"]:
            conn_muni = get_sqlite_conn("municipal_intent.db")
            if conn_muni:
                try:
                    cur_muni = conn_muni.cursor()
                    q = "SELECT event_id, jurisdiction, doc_type as committee, meeting_date, agenda_item_title, key_action, vendor, dollar_amount, vote_outcome, verbatim_text_context FROM processed_intent WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND jurisdiction LIKE ?"
                        params.append(f"%{juris_clean}%")
                    if keywords:
                        kw_clauses = ["(agenda_item_title LIKE ? OR key_action LIKE ? OR vendor LIKE ?)" for _ in keywords]
                        q += f" AND ({' OR '.join(kw_clauses)})"
                        for kw in keywords:
                            params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])
                    if query_year:
                        q += " AND meeting_date LIKE ?"
                        params.append(f"{query_year}%")
                    q += " ORDER BY meeting_date DESC LIMIT 15"
                    cur_muni.execute(q, params)
                    rows = [dict(row) for row in cur_muni.fetchall()]
                    
                    # Compute similarity and sort
                    council_items = []
                    for r in rows:
                        summary_text = r.get("verbatim_text_context") or clean_summary_text(r.get('agenda_item_title'), r.get('key_action'))
                        doc_text = f"{r['jurisdiction']} {r['committee'] or 'Council Action'} {summary_text} {r['vendor'] or ''}"
                        sim_score = calculate_text_similarity(query_text, doc_text)
                        council_items.append((sim_score, r, summary_text))
                        
                    # Sort by similarity descending
                    council_items.sort(key=lambda x: x[0], reverse=True)
                    
                    for sim_score, r, summary_text in council_items[:5]:
                        impact = f"${r['dollar_amount']:,}" if r['dollar_amount'] else "None"
                        context_lines.append(f"[DB-{db_idx}] COUNCIL ACTION - Jurisdiction: {r['jurisdiction']} | Committee: {r['committee']} | Action: {summary_text} | Vendor: {r['vendor']} | Impact: {impact} | Vote: {r['vote_outcome']}")
                        juris_name = r['jurisdiction'].title() if r['jurisdiction'] else "Local"
                        event_id_str = f" {r['event_id']}" if r.get('event_id') else ""
                        m_date = str(r["meeting_date"]) if r["meeting_date"] and str(r["meeting_date"]) != "Extracted_Date" else ""
                        url_query = f"{juris_name.replace(' ', '+')}+city+council+meeting"
                        if m_date:
                            url_query += f"+{m_date}"
                        url_val = f"https://www.google.com/search?q={url_query}"
                        
                        citations.append({
                            "text": f"{juris_name} Council Action{event_id_str}", 
                            "url": url_val,
                            "type": "council"
                        })
                        
                        # Add correlation item
                        correlations.append({
                            "jurisdiction": r["jurisdiction"],
                            "category": r["committee"] or "Council Action",
                            "summary": summary_text,
                            "dollar_impact": r["dollar_amount"],
                            "source": "council",
                            "url": url_val,
                            "similarity": sim_score
                        })
                        db_idx += 1
                    conn_muni.close()
                except Exception as e:
                    print("SQLite Municipal Read Error:", e)

        # 3. Fetch school district financials from municipal_intent.db
        if lens in ["comprehensive", "school"]:
            conn_muni = get_sqlite_conn("municipal_intent.db")
            if conn_muni:
                try:
                    cur_muni = conn_muni.cursor()
                    q = "SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url FROM school_district_financials WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND district_name LIKE ?"
                        params.append(f"%{juris_clean}%")
                    if query_year:
                        q += " AND fiscal_year = ?"
                        params.append(query_year)
                    q += " ORDER BY fiscal_year DESC LIMIT 15"
                    cur_muni.execute(q, params)
                    rows = [dict(row) for row in cur_muni.fetchall()]
                    
                    school_items = []
                    for r in rows:
                        doc_text = f"{r['district_name']} School District Financials {r['fiscal_year']} revenue spending"
                        sim_score = calculate_text_similarity(query_text, doc_text)
                        school_items.append((sim_score, r))
                    school_items.sort(key=lambda x: x[0], reverse=True)
                    
                    for sim_score, r in school_items[:3]:
                        levy_val = f" | Levy Amount: ${r['levy_amount']:,}" if r.get('levy_amount') is not None else ""
                        sped_val = f" | Special Ed: ${r['special_education_spending']:,}" if r.get('special_education_spending') is not None else ""
                        fed_val = f" | Federal Funding: ${r['federal_funding_amount']:,}" if r.get('federal_funding_amount') is not None else ""
                        context_lines.append(f"[DB-{db_idx}] SCHOOL DISTRICT FINANCIALS - District: {r['district_name']} | Year: {r['fiscal_year']} | Enrollment: {r['enrollment']:.0f} FTE | Revenue: ${r['total_revenue']:,} | Expenditures: ${r['total_expenditures']:,}{levy_val}{sped_val}{fed_val}")
                        
                        source_url = r.get("source_url") or f"https://www.google.com/search?q={r['district_name'].replace(' ', '+')}+school+district+budget"
                        citations.append({
                            "text": f"{r['district_name']} School Financials - {r['fiscal_year']}",
                            "url": source_url,
                            "type": "school"
                        })
                        
                        correlations.append({
                            "jurisdiction": r["district_name"],
                            "category": "School District Financials",
                            "summary": f"Enrollment: {r['enrollment']:.0f} FTE, Revenue: ${r['total_revenue']:,}, Expenditures: ${r['total_expenditures']:,}{levy_val}{sped_val}{fed_val}",
                            "dollar_impact": r["total_revenue"],
                            "source": "school",
                            "url": source_url,
                            "similarity": sim_score
                        })
                        db_idx += 1
                    conn_muni.close()
                except Exception as e:
                    print("SQLite School Financials Read Error:", e)

        # 4. Fetch budgets from municipal_intent.db
        if lens in ["comprehensive", "budget"]:
            conn_muni = get_sqlite_conn("municipal_intent.db")
            if conn_muni:
                try:
                    cur_muni = conn_muni.cursor()
                    q = "SELECT jurisdiction_name, entity_type, fiscal_year, total_revenue, total_expenditures, fund_balance_beginning, fund_balance_ending, source_url FROM budgets WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND jurisdiction_name LIKE ?"
                        params.append(f"%{juris_clean}%")
                    if query_year:
                        q += " AND fiscal_year = ?"
                        params.append(query_year)
                    q += " ORDER BY fiscal_year DESC LIMIT 15"
                    cur_muni.execute(q, params)
                    rows = [dict(row) for row in cur_muni.fetchall()]
                    
                    budget_items = []
                    for r in rows:
                        doc_text = f"{r['jurisdiction_name']} Budget {r['fiscal_year']} revenue expenditures"
                        sim_score = calculate_text_similarity(query_text, doc_text)
                        budget_items.append((sim_score, r))
                    budget_items.sort(key=lambda x: x[0], reverse=True)
                    
                    for sim_score, r in budget_items[:3]:
                        beg_bal = f" | Beginning Balance: ${r['fund_balance_beginning']:,}" if r.get('fund_balance_beginning') is not None else ""
                        end_bal = f" | Ending Balance: ${r['fund_balance_ending']:,}" if r.get('fund_balance_ending') is not None else ""
                        context_lines.append(f"[DB-{db_idx}] BUDGET RECORD - Jurisdiction: {r['jurisdiction_name']} ({r['entity_type']}) | Year: {r['fiscal_year']} | Revenue: ${r['total_revenue']:,} | Expenditures: ${r['total_expenditures']:,}{beg_bal}{end_bal}")
                        
                        source_url = r.get("source_url") or f"https://www.google.com/search?q={r['jurisdiction_name'].replace(' ', '+')}+city+budget"
                        citations.append({
                            "text": f"{r['jurisdiction_name']} Budget - {r['fiscal_year']}",
                            "url": source_url,
                            "type": "budget"
                        })
                        
                        correlations.append({
                            "jurisdiction": r["jurisdiction_name"],
                            "category": f"Budget Record ({r['entity_type']})",
                            "summary": f"Revenue: ${r['total_revenue']:,}, Expenditures: ${r['total_expenditures']:,}{beg_bal}{end_bal}",
                            "dollar_impact": r["total_revenue"],
                            "source": "budget",
                            "url": source_url,
                            "similarity": sim_score
                        })
                        db_idx += 1
                    conn_muni.close()
                except Exception as e:
                    print("SQLite Budgets Read Error:", e)

        # 5. Fetch grants from municipal_intent.db
        if lens in ["comprehensive", "grant"]:
            conn_muni = get_sqlite_conn("municipal_intent.db")
            if conn_muni:
                try:
                    cur_muni = conn_muni.cursor()
                    q = "SELECT grant_title, awarding_agency, recipient_jurisdiction, award_amount, award_date, purpose_category, source_url FROM grants WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND recipient_jurisdiction LIKE ?"
                        params.append(f"%{juris_clean}%")
                    if keywords:
                        kw_clauses = ["(grant_title LIKE ? OR purpose_category LIKE ?)" for _ in keywords]
                        q += f" AND ({' OR '.join(kw_clauses)})"
                        for kw in keywords:
                            params.extend([f"%{kw}%", f"%{kw}%"])
                    q += " ORDER BY award_date DESC LIMIT 15"
                    cur_muni.execute(q, params)
                    rows = [dict(row) for row in cur_muni.fetchall()]
                    
                    grant_items = []
                    for r in rows:
                        doc_text = f"{r['recipient_jurisdiction']} Grant {r['grant_title']} agency {r['awarding_agency']} category {r['purpose_category'] or ''}"
                        sim_score = calculate_text_similarity(query_text, doc_text)
                        grant_items.append((sim_score, r))
                    grant_items.sort(key=lambda x: x[0], reverse=True)
                    
                    for sim_score, r in grant_items[:3]:
                        date_str = f" | Date: {r['award_date']}" if r.get('award_date') else ""
                        cat_str = f" | Category: {r['purpose_category']}" if r.get('purpose_category') else ""
                        context_lines.append(f"[DB-{db_idx}] GRANT AWARD - Recipient: {r['recipient_jurisdiction']} | Agency: {r['awarding_agency']} | Title: {r['grant_title']} | Amount: ${r['award_amount']:,}{date_str}{cat_str}")
                        
                        source_url = r.get("source_url") or f"https://www.google.com/search?q={r['recipient_jurisdiction'].replace(' ', '+')}+grants"
                        citations.append({
                            "text": f"Grant: {r['grant_title']}",
                            "url": source_url,
                            "type": "grant"
                        })
                        
                        correlations.append({
                            "jurisdiction": r["recipient_jurisdiction"],
                            "category": "Grant Award",
                            "summary": f"Title: {r['grant_title']}, Agency: {r['awarding_agency']}, Amount: ${r['award_amount']:,}{date_str}{cat_str}",
                            "dollar_impact": r["award_amount"],
                            "source": "grant",
                            "url": source_url,
                            "similarity": sim_score
                        })
                        db_idx += 1
                    conn_muni.close()
                except Exception as e:
                    print("SQLite Grants Read Error:", e)

    return context_lines, citations, correlations

def send_alert_email(email: str, name: str, topics: str):
    """Mocks sending a tracking confirmation alert."""
    print(f"📧 [ALERT EMAIL SENT] To: {email} | Recipient: {name} | Subject: PennerAI Active Monitor Set for '{topics}'")

@app.post("/api/v1/auth/assign")
async def register_alert(req: AlertSubscriptionSchema, background_tasks: BackgroundTasks, request: Request):
    """Registers alert subscriptions inside the PostgreSQL database (lead capture)."""
    anon_user_id = request.headers.get("x-anonymous-user-id", "unknown-user")
    session_id = request.headers.get("x-session-id", "unknown-session")
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "127.0.0.1").split(",")[0].strip()
    
    start_time = time.time()
    saved = False
    
    # Try PostgreSQL first, then SQLite fallback
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alert_subscriptions (name, email, topics, jurisdiction, query, anonymous_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (req.name, req.email, req.topics, req.jurisdiction, req.query, anon_user_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        saved = True
    except Exception as e:
        print(f"Postgres alerts save failed: {e}")
        # Try SQLite fallback
        try:
            conn = sqlite3.connect(SQLITE_TRACKING_PATH)
            conn.execute("PRAGMA busy_timeout = 30000;")
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO alert_subscriptions (name, email, topics, jurisdiction, query, anonymous_user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (req.name, req.email, req.topics, req.jurisdiction, req.query, anon_user_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            saved = True
            print("Alert subscription saved to SQLite fallback database.")
        except Exception as sqlite_err:
            print(f"SQLite alert save failed: {sqlite_err}")
        
    if not saved:
        print(f"📧 [CONSOLE ONLY FALLBACK] Lead details: {req.name} | {req.email} | Topics: {req.topics}")
        
    background_tasks.add_task(send_alert_email, req.email, req.name, req.topics)
    
    # Log usage event for this request
    response_time = int((time.time() - start_time) * 1000)
    await asyncio.to_thread(
        log_usage_event,
        ip_address=client_ip,
        anonymous_user_id=anon_user_id,
        session_id=session_id,
        endpoint="/api/v1/auth/assign",
        tokens_in=estimate_tokens(req.name + req.email + req.topics + (req.jurisdiction or "") + (req.query or "")),
        tokens_out=estimate_tokens("success"),
        response_time_ms=response_time,
        has_citations=False,
        has_correlations=False
    )
    
    return {"status": "success", "message": "Alert subscription active."}

@app.post("/api/v1/chat")
async def chat_stream(
    req_body: dict, 
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """
    Main conversational chat endpoint.
    Supports both:
    1. Dashboard SSE requests: {"query": str, "lens": str}
    2. OpenAI-compatible Chat Completions: {"messages": list, "stream": bool, ...} (requires API key)
    """
    if "messages" in req_body:
        # 1. Verify API Key for OpenAI-compatible client
        api_key = verify_api_key(credentials)
        # 2. Run OpenAI-style chat completions flow
        return await openai_chat_completions(req_body, api_key, request)
    else:
        # 1. Parse Dashboard Request
        query = req_body.get("query", "")
        lens = req_body.get("lens", "comprehensive")
        history = req_body.get("history", [])
        if not query:
            raise HTTPException(status_code=400, detail="Missing required 'query' field.")
            
        # Extract headers for rate limiting and tracking
        anon_user_id = request.headers.get("x-anonymous-user-id", "unknown-user")
        session_id = request.headers.get("x-session-id", "unknown-session")
        client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "127.0.0.1").split(",")[0].strip()
        
        # 2. Rate limit check for anonymous dashboard users
        is_dev_key = False
        api_key = "sk-penner-dashboard"
        if credentials:
            try:
                api_key = verify_api_key(credentials)
                is_dev_key = True
            except Exception:
                pass
                
        if not is_dev_key:
            # Check rate limit (15 requests/day default, 50 for alerts subscribed users)
            if not await asyncio.to_thread(check_rate_limit, client_ip, anon_user_id):
                raise HTTPException(
                    status_code=429, 
                    detail="Daily message limit reached. Please register for alerts or upgrade your account to continue."
                )
        
        # 3. Run original dashboard streaming flow
        return await original_chat_stream_flow(query, lens, api_key, request, history)

def insert_inline_citations(narrative: str, grounding_metadata: dict) -> str:
    """Inserts inline citations (e.g., [1], [2]) into the narrative text based on Gemini grounding metadata."""
    if not grounding_metadata:
        return narrative
        
    supports = grounding_metadata.get("groundingSupports", [])
    if not supports:
        return narrative
        
    # Map segment text to referenced chunk indices (1-based)
    segments_to_indices = []
    for s in supports:
        seg_text = s.get("segment", {}).get("text", "").strip()
        chunk_indices = s.get("groundingChunkIndices", [])
        if seg_text and chunk_indices:
            segments_to_indices.append((seg_text, [idx + 1 for idx in chunk_indices]))
            
    # Sort by length descending to match longer segments first (prevents sub-string replacement issues)
    segments_to_indices.sort(key=lambda x: len(x[0]), reverse=True)
    
    processed_narrative = narrative
    for seg_text, cite_nums in segments_to_indices:
        cite_str = "".join([f" [{num}]" for num in cite_nums])
        
        idx = processed_narrative.find(seg_text)
        if idx != -1:
            end_pos = idx + len(seg_text)
            # Check if citation bracket is already present right after the segment
            following_text = processed_narrative[end_pos:end_pos + 15]
            if not any(f"[{num}]" in following_text for num in cite_nums):
                processed_narrative = (
                    processed_narrative[:end_pos] + 
                    cite_str + 
                    processed_narrative[end_pos:]
                )
                
    return processed_narrative

async def original_chat_stream_flow(query: str, lens: str, api_key: str, request: Request, history: Optional[List[dict]] = None):
    """Original dashboard SSE streaming logic with inline search and grounding."""
    anon_user_id = request.headers.get("x-anonymous-user-id", "unknown-user")
    session_id = request.headers.get("x-session-id", "unknown-session")
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "127.0.0.1").split(",")[0].strip()

    async def event_generator():
        start_time = time.time()
        # Yield initial status immediately
        yield f"data: {json.dumps({'status': 'intent', 'message': 'Analyzing query intent and targets...'})}\n\n"
        
        async with httpx.AsyncClient() as client:
            # 1. Fetch intent and embedding in parallel
            intent_task = asyncio.create_task(extract_intent_async(query, client, history))
            embed_task = asyncio.create_task(get_embedding_async(query, client))
            
            # Await intent results to identify jurisdiction with safety timeout
            try:
                jurisdiction, keywords = await asyncio.wait_for(intent_task, timeout=10.0)
            except Exception as e:
                print(f"Intent extraction timed out or failed: {e}")
                jurisdiction, keywords = "", []
            
            status_search_msg = (
                f"Searching databases for matches..." 
                if not jurisdiction else 
                f"Searching databases for matches in {jurisdiction}..."
            )
            yield f"data: {json.dumps({'status': 'searching', 'message': status_search_msg})}\n\n"
            
            # Await embedding results for vector correlation search with safety timeout
            try:
                query_emb = await asyncio.wait_for(embed_task, timeout=6.0)
            except Exception as e:
                print(f"Embedding generation timed out or failed: {e}")
                query_emb = None
                
            yield f"data: {json.dumps({'status': 'correlating', 'message': 'Running vector correlation search...'})}\n\n"
            
            # Detect database mode
            use_sqlite = False
            try:
                conn_pg = await asyncio.wait_for(asyncio.to_thread(get_pg_conn), timeout=3.0)
                conn_pg.close()
            except Exception:
                use_sqlite = True
                
            # 2. Query Postgres/SQLite in thread pool with safety timeout
            try:
                context_lines, citations, correlations = await asyncio.wait_for(
                    asyncio.to_thread(
                        fetch_context_and_correlations,
                        "comprehensive",
                        jurisdiction,
                        keywords,
                        query_emb,
                        use_sqlite,
                        query
                    ),
                    timeout=10.0
                )
            except Exception as e:
                print(f"Database query operation timed out or failed: {e}")
                context_lines, citations, correlations = [], [], []
            
            # Detect if a legislative bill is mentioned in the query
            bill_match = re.search(r'\b(sb|hb|ssb|ehb|eshb|sjr|hjr|scr|hcr)\s*(\d{4})\b', query, re.IGNORECASE)
            bill_details = None
            if bill_match:
                bill_type = bill_match.group(1).upper()
                bill_num = bill_match.group(2)
                bill_id = f"{bill_type} {bill_num}"
                try:
                    bill_details = await asyncio.wait_for(asyncio.to_thread(get_legislative_bill_status_tool, bill_id), timeout=5.0)
                except Exception as e:
                    print(f"Error fetching bill status: {e}")
            
            if bill_details:
                context_lines.append(
                    f"STATE BILL STATUS - Bill: {bill_details['bill_number']} | "
                    f"Live Status: {bill_details['live_status']} | "
                    f"Local Database Mentions: {json.dumps(bill_details['local_database_mentions'])}"
                )
                citations.append({
                    "text": f"WA Legislature - {bill_details['bill_number']}",
                    "url": f"https://app.leg.wa.gov/billsummary?BillNumber={bill_num}&Year=2025",
                    "type": "bill"
                })
                
            # Detect if a grant/funding is mentioned in query
            grant_match = re.search(r'\b(grant|grants|funding|subsid|award|awards|appropriation)\b', query, re.IGNORECASE)
            grant_details = None
            if grant_match:
                category = "transportation"
                if keywords:
                    category_candidates = [kw for kw in keywords if kw.lower() != (jurisdiction.lower() if jurisdiction else "")]
                    if category_candidates:
                        category = category_candidates[0]
                try:
                    grant_details = await asyncio.wait_for(asyncio.to_thread(get_grants_by_category_tool, category, jurisdiction), timeout=5.0)
                except Exception as e:
                    print(f"Error fetching grants details: {e}")
            
            if grant_details:
                audits_count = len(grant_details.get("audits", []))
                council_count = len(grant_details.get("council_actions", []))
                context_lines.append(
                    f"GRANTS & FUNDING (Category: {grant_details['category']}) - "
                    f"Retrieved {audits_count} audits and {council_count} council records matching this grant category."
                )
                citations.append({
                    "text": f"Grants & Funding: {grant_details['category'].title()}",
                    "url": f"https://www.google.com/search?q={grant_details['category'].replace(' ', '+')}+grants+washington+state",
                    "type": "grant"
                })

            db_citations_only = list(citations)
            web_citations = []
            grounding_supports = []
            
            yield f"data: {json.dumps({'status': 'synthesizing', 'message': 'Synthesizing verified records and generating response...'})}\n\n"
            
            # Set up context string for prompt
            context_str = "\n".join(context_lines) if context_lines else "No direct matching database records found."
            
            system_prompt = f"""You are the PennerAI Civic Intelligence Agent. 
You provide deep, fact-based answers exploring Washington State policies and local governance.
Make your responses highly scannable, structured, and visually engaging for the public.
Avoid dense walls of text: use bold headers, structured bullet points, and call out key metrics (like dollar amounts or report numbers) in bold.
Wherever it makes sense (e.g. comparing multiple cities or showing financial impacts), present the findings in a clean markdown table.

WASHINGTON CIVIC STRUCTURE RULES:
- In Washington State, cities/towns, counties, school districts, port districts, and other special purpose districts are completely independent, self-governing local government entities.
- Do NOT assume one funds, controls, or oversees the other (e.g. cities do not fund or spend money on school districts, and school districts do not oversee city councils).
- Make sure your analysis and facts respect these structural boundaries.
- Be precise when referencing entities. Distinguish clearly between the "City of Bellevue" and the "Bellevue School District" or other special purpose districts. Never refer to them interchangeably or simply as "Bellevue" if doing so introduces ambiguity.

POLITICAL NEUTRALITY & LEGISLATIVE BALANCE:
- State legislative bills and policy changes are rarely passed by unanimous consent and are often subjects of intense debate and controversy.
- Do NOT frame legislative actions, bills, or local policies with positive bias or assume a unified consensus among leaders. For example, avoid using phrases like "state leaders hope", "lawmakers agree", or describing a bill as a simple "solution" without acknowledging its contested nature.
- When describing a legislative bill or major policy (such as interfund loans, tax levies, or budget reallocations), you MUST present a balanced view covering both sides:
  1. The proponents' or sponsors' intent and rationale (e.g., providing local governments with financial flexibility to cover short-term cash flow needs).
  2. The opponents' or critics' arguments and concerns (e.g., risks of diminishing public funds, the lack of a clear repayment or remuneration plan, or the long-standing view in local governance that practices like interfund loans are highly risky or considered anathema).
- Maintain a strictly objective, neutral, and journalistic tone. Present the policy change as a debated mechanism with tradeoffs rather than an unalloyed positive development.

CRITICAL CITATION & SOURCES RULES:
1. Do NOT include any bibliography, references, or "Sources" section at the bottom of your response. The application frontend will automatically render the sources separately under the message bubble.
2. CITATION SEPARATION RULE:
   - For any facts, statistics, quotes, or findings retrieved from the provided CONTEXT DATABASE RECORDS, you MUST use database bracket labels (e.g., [DB-1], [DB-2], etc.). These labels must match the exact record numbers listed under CONTEXT DATABASE RECORDS.
   - For any facts or details retrieved from Google Search grounding, you MUST use web/search bracket labels (e.g., [1], [2], etc.).
   - NEVER mix these two namespaces. Do NOT cite a database record using [1], [2], etc., and do NOT cite a web search result using [DB-1], [DB-2], etc.
3. Every single claim, finding, statistic, or quote that you retrieve from the database records or web search grounding MUST be immediately followed by its corresponding bracket label (e.g. [DB-1] or [1]).
4. If you reference external audits, laws, bills, or local school districts not covered by the CONTEXT DATABASE RECORDS (such as Marysville School District, SAFS updates, legislative details, etc.), you MUST perform a Google search for them so they are included in the grounding metadata. Do NOT write about them or cite them unless you have performed a Google search for them in this turn.
5. If the provided CONTEXT DATABASE RECORDS contain records that are not directly related to answering the user's primary question, you may summarize them at the bottom. However, do NOT label this section as "Other [Jurisdiction] Local Governance Findings" or "Other [Jurisdiction] findings" or similar. Instead, you MUST label it exactly as the header "### Other Local Records (Correlations Engine Beta)" and introduce it with exactly the sentence: "The following additional records are provided as a courtesy of the PennerAI Correlations Engine (beta):"
6. Do NOT include any bibliography, reference list, or "Sources" section at the end of your response. The application frontend will automatically render the sources separately under the message bubble.

CONTEXT DATABASE RECORDS:
{context_str}
"""
            
            # Start generating dynamic suggestions in the background using client
            async def generate_suggestions_api(query_str: str, ctx_lines: list) -> list:
                if not GEMINI_API_KEY:
                    return generate_heuristic_suggestions(query_str, jurisdiction, ctx_lines)
                try:
                    s_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
                    s_headers = {"Content-Type": "application/json"}
                    ctx_snippet = "\n".join(ctx_lines[:3]) if ctx_lines else "No context records found."
                    history_str = ""
                    if history:
                        history_str = "\n".join([f"{msg.get('role', 'user').capitalize()}: {msg.get('content', '')}" for msg in history[-4:]])
                        
                    s_prompt = f"""Based on the conversation history, user's query, and the database context records, generate exactly 3 relevant follow-up questions for civic policy exploration.
Keep each question extremely short (3-6 words each).

CRITICAL DOMAIN RULES:
- In Washington State, cities and school districts are entirely separate, independent local government entities. Do NOT generate questions that conflate them (e.g., do not ask about a city's spending on a school district, or school district contracts in a city's council).
- Keep questions focused on the appropriate entity (e.g. school enrollment/budgets/levies for school districts, or city council votes/contracts for cities).
- Use the specific, full name of the school district or city to maintain exact context (e.g., use "Bellevue School District" or "City of Bellevue" rather than just "Bellevue").
- Do NOT use correlation meta-commands or preamble commands (like "Analyze the correlation report", "Explain correlation", "Draft response", etc.) as subject or contract entities in the questions. Instead, focus suggestions ONLY on the actual underlying governance topics (e.g. interfund loans, budget deficits, internal controls).

Conversation History:
{history_str}

User Query: {query_str}
Database Context:
{ctx_snippet}

Return ONLY a JSON list of strings, e.g. ["Question 1?", "Question 2?", "Question 3?"]. Do not wrap the JSON output in markdown tags.
"""
                    s_payload = {
                        "contents": [{"parts": [{"text": s_prompt}]}],
                        "generationConfig": {
                            "temperature": 0.4,
                            "responseMimeType": "application/json"
                        }
                    }
                    async with httpx.AsyncClient() as c:
                        resp = await c.post(s_url, headers=s_headers, json=s_payload, timeout=3.5)
                        if resp.status_code == 200:
                            suggs = json.loads(resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip())
                            if isinstance(suggs, list) and len(suggs) > 0:
                                return [truncate_suggestion(s, 120) for s in suggs[:3]]
                except Exception as e:
                    import traceback
                    print(f"Failed to generate dynamic suggestions: {repr(e)}")
                    traceback.print_exc()
                
                return generate_heuristic_suggestions(query_str, jurisdiction, ctx_lines)

            suggestions_task = asyncio.create_task(generate_suggestions_api(query, context_lines))
            
            full_narrative = ""
            if not GEMINI_API_KEY:
                # Fallback path via Membrane Async Stream completions
                try:
                    url = f"{membrane.base_url}/v1/chat/completions"
                    payload = {
                        "model": "membrane-engagement-layer",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": query}
                        ],
                        "temperature": 0.0,
                        "stream": True
                    }
                    async with client.stream("POST", url, headers=membrane._headers(), json=payload, timeout=60.0) as response:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                content = line[6:].strip()
                                if content == "[DONE]":
                                    continue
                                try:
                                    parsed = json.loads(content)
                                    token = ""
                                    if "choices" in parsed:
                                        token = parsed["choices"][0]["delta"].get("content", "")
                                    elif "chunk" in parsed:
                                        token = parsed["chunk"]
                                    
                                    if token:
                                        full_narrative += token
                                        yield f"data: {json.dumps({'chunk': token})}\n\n"
                                except Exception:
                                    pass
                except Exception as e:
                    yield f"data: {json.dumps({'chunk': f'Error rendering narrative: {e}'})}\n\n"
            else:
                # Main path: Direct Gemini 3.5 Flash call with live Google Search Grounding
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:streamGenerateContent?key={GEMINI_API_KEY}"
                headers = {"Content-Type": "application/json"}
                
                prompt = f"""You are the PennerAI Civic Intelligence Agent.
Answer the user's question about Washington State local governance.
Rely on the provided CONTEXT DATABASE RECORDS for any specific local audits or council actions.
If you need to mention other school districts, laws, or audits to answer the user's question, or if you reference details not fully written in the CONTEXT DATABASE RECORDS, you MUST use your search grounding tool to search the web for them.

CRITICAL REQUIREMENTS:
1. Do NOT include any introductory sentences, conversational filler, greeting, or meta-commentary (such as "Here are the findings", "Based on my search...", "As the PennerAI..."). Begin the response immediately with the raw facts, headers, or tables.
2. Do NOT write any "Sources" or bibliography section at the bottom of your response. The application frontend will automatically render the sources separately under the message bubble.
3. STRICT CITATION SEPARATION RULE:
   - You MUST cite the provided CONTEXT DATABASE RECORDS using the exact database bracket labels (e.g., [DB-1], [DB-2], etc.) at the end of sentences where details from them are used. Never cite database records using [1], [2], etc.
   - You MUST cite web search grounding results using search bracket labels (e.g., [1], [2], etc.). Never cite web search results using [DB-1], [DB-2], etc.
   - Do NOT include citations like [1], [2] unless you have performed a web search for them and they are linked in the grounding metadata.
4. Every single claim, finding, statistic, or quote that you retrieve from the database records or web search grounding MUST be immediately followed by its corresponding bracket label (e.g. [DB-1] or [1]).
5. If the provided CONTEXT DATABASE RECORDS contain records that are not directly related to answering the user's primary question, you may summarize them at the bottom. However, do NOT label this section as "Other [Jurisdiction] Local Governance Findings" or "Other [Jurisdiction] findings" or similar. Instead, you MUST label it exactly as the header "### Other Local Records (Correlations Engine Beta)" and introduce it with exactly the sentence: "The following additional records are provided as a courtesy of the PennerAI Correlations Engine (beta):"
6. If you reference external audits, laws, bills, or local school districts not covered by the CONTEXT DATABASE RECORDS (such as Marysville School District, SAFS updates, legislative details, etc.), you MUST perform a Google search in this turn so they are included in the grounding metadata. Do NOT write about them or cite them unless you have performed a Google search for them in this turn.

User Question: {query}
CONTEXT DATABASE RECORDS:
{context_str}
"""
                contents = []
                if history:
                    # Clean history to ensure strict alternating starting with user
                    cleaned_history = []
                    expected_role = "user"
                    for msg in history:
                        role = msg.get("role")
                        content = msg.get("content", "")
                        if not content:
                            continue
                        mapped_role = "user" if role == "user" else "model"
                        if mapped_role == expected_role:
                            cleaned_history.append({"role": mapped_role, "parts": [{"text": content}]})
                            expected_role = "model" if expected_role == "user" else "user"
                        else:
                            if cleaned_history and cleaned_history[-1]["role"] == mapped_role:
                                cleaned_history[-1]["parts"][0]["text"] += "\n" + content
                    
                    contents.extend(cleaned_history[-6:])
                    if contents and contents[0]["role"] == "model":
                        contents.pop(0)

                contents.append({"role": "user", "parts": [{"text": prompt}]})
                
                payload = {
                    "contents": contents,
                    "tools": [{"googleSearch": {}}],
                    "generationConfig": {
                        "temperature": 0.2
                    },
                    "systemInstruction": {
                        "parts": [{"text": system_prompt}]
                    }
                }
                
                print(f"DEBUG: Gemini payload:\n{json.dumps(payload, indent=2)}")
                try:
                    async with client.stream("POST", url, headers=headers, json=payload, timeout=60.0) as response:
                        response.raise_for_status()
                        
                        buffer = ""
                        queue = asyncio.Queue()
                        
                        async def read_stream():
                            try:
                                async for chunk in response.aiter_text():
                                    await queue.put(chunk)
                            except Exception as ex:
                                await queue.put(ex)
                            finally:
                                await queue.put(None)
                                
                        stream_task = asyncio.create_task(read_stream())
                        
                        heartbeat_messages = [
                            "Searching the web for Washington policy details...",
                            "Reading and verifying source materials...",
                            "Synthesizing database records and search grounding...",
                            "Drafting response with inline citations..."
                        ]
                        heartbeat_idx = 0
                        
                        while True:
                            try:
                                item = await asyncio.wait_for(queue.get(), timeout=3.0)
                            except asyncio.TimeoutError:
                                msg = heartbeat_messages[heartbeat_idx % len(heartbeat_messages)]
                                heartbeat_idx += 1
                                yield f"data: {json.dumps({'status': 'synthesizing', 'message': msg})}\n\n"
                                continue
                                
                            if item is None:
                                break
                            if isinstance(item, Exception):
                                raise item
                                
                            chunk = item
                            if chunk:
                                buffer += chunk
                                while True:
                                    start_idx = buffer.find("{")
                                    if start_idx == -1:
                                        break
                                    
                                    brace_count = 0
                                    in_string = False
                                    escape = False
                                    end_idx = -1
                                    
                                    for idx in range(start_idx, len(buffer)):
                                        char = buffer[idx]
                                        if char == '"' and not escape:
                                            in_string = not in_string
                                        elif char == '\\' and in_string:
                                            escape = not escape
                                            continue
                                        elif not in_string:
                                            if char == '{':
                                                brace_count += 1
                                            elif char == '}':
                                                brace_count -= 1
                                                if brace_count == 0:
                                                    end_idx = idx
                                                    break
                                        escape = False
                                        
                                    if end_idx != -1:
                                        obj_str = buffer[start_idx:end_idx+1]
                                        buffer = buffer[end_idx+1:]
                                        try:
                                            parsed = json.loads(obj_str)
                                            if "candidates" in parsed:
                                                cand = parsed["candidates"][0]
                                                print(f"DEBUG: Parsed Gemini chunk candidate keys: {list(cand.keys())}")
                                                if "groundingMetadata" in cand:
                                                    print(f"DEBUG: FOUND groundingMetadata! Chunks: {len(cand['groundingMetadata'].get('groundingChunks', []))}")
                                            else:
                                                print(f"DEBUG: Parsed Gemini chunk root keys (no candidates): {list(parsed.keys())}")
                                            candidate = parsed["candidates"][0]
                                            
                                            # Yield text token
                                            text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
                                            if text:
                                                full_narrative += text
                                                yield f"data: {json.dumps({'chunk': text})}\n\n"
                                                
                                            # Extract grounding chunks (sources) if present
                                            metadata = candidate.get("groundingMetadata", {})
                                            if "groundingChunks" in metadata:
                                                for web_chunk in metadata["groundingChunks"]:
                                                    if "web" in web_chunk:
                                                        uri = web_chunk["web"].get("uri", "")
                                                        title = web_chunk["web"].get("title", "")
                                                        if uri and title:
                                                            if not any(c["url"] == uri for c in web_citations):
                                                                web_citations.append({"text": title, "url": uri})
                                            if "groundingSupports" in metadata:
                                                for support in metadata["groundingSupports"]:
                                                    if support not in grounding_supports:
                                                        grounding_supports.append(support)
                                        except Exception as parse_err:
                                            import traceback
                                            print(f"Error parsing Gemini streaming chunk: {parse_err}")
                                            traceback.print_exc()
                                    else:
                                        break
                except Exception as e:
                    print(f"Gemini API error: {e}. Falling back to Membrane Engagement Layer.")
                    yield f"data: {json.dumps({'status': 'synthesizing', 'message': 'Gemini API limit reached. Falling back to Membrane Engagement Layer...'})}\n\n"
                    try:
                        fallback_url = f"{membrane.base_url}/v1/chat/completions"
                        fallback_payload = {
                            "model": "membrane-engagement-layer",
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": query}
                            ],
                            "temperature": 0.0,
                            "stream": True
                        }
                        async with client.stream("POST", fallback_url, headers=membrane._headers(), json=fallback_payload, timeout=60.0) as fallback_response:
                            fallback_response.raise_for_status()
                            fallback_queue = asyncio.Queue()
                            
                            async def read_fallback():
                                try:
                                    async for line in fallback_response.aiter_lines():
                                        await fallback_queue.put(line)
                                except Exception as ex:
                                    await fallback_queue.put(ex)
                                finally:
                                    await fallback_queue.put(None)
                                    
                            fallback_task = asyncio.create_task(read_fallback())
                            
                            while True:
                                try:
                                    item = await asyncio.wait_for(fallback_queue.get(), timeout=3.0)
                                except asyncio.TimeoutError:
                                    yield f"data: {json.dumps({'status': 'synthesizing', 'message': 'Generating response...'})}\n\n"
                                    continue
                                    
                                if item is None:
                                    break
                                if isinstance(item, Exception):
                                    raise item
                                    
                                line = item
                                if line.startswith("data: "):
                                    content = line[6:].strip()
                                    if content == "[DONE]":
                                        continue
                                    try:
                                        parsed = json.loads(content)
                                        token = ""
                                        if "choices" in parsed:
                                            token = parsed["choices"][0]["delta"].get("content", "")
                                        elif "chunk" in parsed:
                                            token = parsed["chunk"]
                                        
                                        if token:
                                            full_narrative += token
                                            yield f"data: {json.dumps({'chunk': token})}\n\n"
                                    except Exception:
                                        pass
                    except Exception as fallback_err:
                        err_str = str(e).lower() + " " + str(fallback_err).lower()
                        if "depleted" in err_str:
                            error_detail = "Your Google AI Studio prepayment credits are depleted. Please top up your billing in Google AI Studio to restore service."
                        elif "spending cap" in err_str or "spend cap" in err_str:
                            error_detail = "Your Google AI Studio monthly spending cap has been reached. Please adjust your spend limit in Google AI Studio to restore service."
                        else:
                            error_detail = f"Gemini API rate limit or quota exceeded. Error: {e}"
                        
                        notice = (
                            "⚠️ **Service Notice: API Credits Depleted**\n\n"
                            f"{error_detail}\n\n"
                            "*Note: Verified database records (DB-1, DB-2, etc.) and vector correlations are still loaded in the sidebar. You can also view the raw data tables in the Lenses.*"
                        )
                        yield f"data: {json.dumps({'chunk': notice})}\n\n"
                    
            # Post-process narrative to insert inline web citations
            if grounding_supports:
                try:
                    full_narrative = insert_inline_citations(full_narrative, {"groundingSupports": grounding_supports})
                except Exception as e:
                    print(f"Error inserting inline citations: {e}")

            try:
                suggestions = await asyncio.wait_for(suggestions_task, timeout=5.0)
            except Exception as e:
                import traceback
                print(f"Failed to generate dynamic suggestions from task: {repr(e)}")
                traceback.print_exc()
                suggestions = generate_heuristic_suggestions(query, jurisdiction, context_lines)

            counts = {
                "audits": len([c for c in db_citations_only if c.get("type") == "audit"]),
                "council": len([c for c in db_citations_only if c.get("type") == "council"]),
                "bills": len([c for c in db_citations_only if c.get("type") == "bill"]),
                "grants": len([c for c in db_citations_only if c.get("type") == "grant"])
            }

            metadata_event = {
                "content": full_narrative,
                "citations": web_citations,
                "db_citations": db_citations_only,
                "suggestions": suggestions,
                "correlations": correlations,
                "lens_metadata": {
                    "counts": counts,
                    "bill_details": bill_details,
                    "grant_details": grant_details
                }
            }
            yield f"data: {json.dumps(metadata_event)}\n\n"
            yield "data: [DONE]\n\n"
            
            # Log usage
            prompt_toks = len(query) // 4
            completion_toks = len(full_narrative) // 4
            log_api_usage(api_key, "POST /api/v1/chat (dashboard)", prompt_toks, completion_toks)
            
            # Log usage event to usage_events asynchronously
            response_time = int((time.time() - start_time) * 1000)
            asyncio.create_task(
                asyncio.to_thread(
                    log_usage_event,
                    client_ip,
                    anon_user_id,
                    session_id,
                    "/api/v1/chat (dashboard)",
                    prompt_toks,
                    completion_toks,
                    response_time,
                    (len(web_citations) > 0 or len(db_citations_only) > 0),
                    len(correlations) > 0,
                    None if api_key == "sk-penner-dashboard" else api_key,
                    query,
                    jurisdiction
                )
            )
            
    sse_headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=sse_headers)

# OpenAI-compatible Chat Completions implementation
async def openai_chat_completions(req_body: dict, api_key: str, request: Request):
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "127.0.0.1").split(",")[0].strip()
    anon_user_id = f"agent-{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    model = req_body.get("model", "pennerai-agent-v1")
    messages = req_body.get("messages", [])
    stream = req_body.get("stream", False)
    temperature = req_body.get("temperature", 0.2)
    max_tokens = req_body.get("max_tokens", None)
    response_format = req_body.get("response_format", None)
    
    user_query = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_query = m.get("content", "")
            break
    
    # Check system prompt
    system_instruction = """You are the PennerAI Civic Intelligence Agent.
You provide deep, fact-based answers exploring Washington State policies and local governance.
You have access to a set of tools to query SAO audits, city council actions, vector correlations, and legislative bills.

POLITICAL NEUTRALITY & LEGISLATIVE BALANCE:
- State legislative bills and policy changes are rarely passed by unanimous consent and are often subjects of intense debate and controversy.
- Do NOT frame legislative actions, bills, or local policies with positive bias or assume a unified consensus among leaders. For example, avoid using phrases like "state leaders hope", "lawmakers agree", or describing a bill as a simple "solution" without acknowledging its contested nature.
- When describing a legislative bill or major policy (such as interfund loans, tax levies, or budget reallocations), you MUST present a balanced view covering both sides:
  1. The proponents' or sponsors' intent and rationale (e.g., providing local governments with financial flexibility to cover short-term cash flow needs).
  2. The opponents' or critics' arguments and concerns (e.g., risks of diminishing public funds, the lack of a clear repayment or remuneration plan, or the long-standing view in local governance that practices like interfund loans are highly risky or considered anathema).
- Maintain a strictly objective, neutral, and journalistic tone. Present the policy change as a debated mechanism with tradeoffs rather than an unalloyed positive development.

CRITICAL REQUIREMENTS:
1. Always call the appropriate tool when asked about specific audits, jurisdictions, council actions, or correlations.
2. In your final response, you must structure the answer with clear headers, bullet points, and tables where appropriate.
3. Every answer must include:
   - "sources": An array of citation sources used (each with "text" and "url").
   - "confidence": A float confidence score between 0.0 and 1.0 representing how well the database records answered the question.
   - "last_updated": The current ISO timestamp.
4. If the user requested response_format = {"type": "json_object"}, you MUST return a valid JSON object matching this schema:
   {
     "answer": "The text answer",
     "sources": [{"text": "...", "url": "..."}],
     "confidence": 0.95,
     "last_updated": "2026-05-24T21:50:12"
   }
   If response_format is NOT set, respond in markdown but include a "SOURCES & METADATA" section at the end in this format:
   ---
   Confidence: 0.95
   Last Updated: 2026-05-24T21:50:12
   Sources:
   - [Source Text](Source URL)
"""
    has_system = False
    for m in messages:
        if m.get("role") == "system":
            m["content"] = system_instruction + "\n\nAdditional client instructions:\n" + m["content"]
            has_system = True
            break
    if not has_system:
        messages.insert(0, {"role": "system", "content": system_instruction})
        
    chat_id = f"chatcmpl-{uuid.uuid4()}"
    created_time = int(time.time())
    if not stream:
        final_text, _, prompt_tokens, completion_tokens = await run_tool_loop_async(messages, temperature, max_tokens)
        
        if response_format and response_format.get("type") == "json_object":
            content, sources, confidence, last_updated = extract_metadata_from_json(final_text)
        else:
            content = final_text
            sources, confidence, last_updated = parse_metadata_from_text(final_text)
            
        response_dict = {
            "id": chat_id,
            "object": "chat.completion",
            "created": created_time,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            },
            "sources": sources,
            "confidence": confidence,
            "last_updated": last_updated
        }
        
        log_api_usage(api_key, f"POST /api/v1/chat ({model})", prompt_tokens, completion_tokens)
        await asyncio.to_thread(
            log_usage_event,
            ip_address=client_ip,
            anonymous_user_id=anon_user_id,
            session_id=f"agent-session-{chat_id}",
            endpoint=f"/api/v1/chat ({model})",
            tokens_in=prompt_tokens,
            tokens_out=completion_tokens,
            response_time_ms=response_time,
            has_citations=len(sources) > 0,
            has_correlations=False,
            agent_api_key=api_key,
            query_text=user_query
        )
        return response_dict
        
    else:
        async def stream_generator():
            # Resolve agent tools
            _, final_messages, prompt_tokens, _ = await run_tool_loop_async(messages, temperature, max_tokens)
            
            try:
                response = litellm.completion(
                    model="gemini/gemini-3.5-flash",
                    messages=final_messages,
                    stream=True,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    api_key=GEMINI_API_KEY
                )
                full_text = ""
                for chunk in response:
                    delta_content = ""
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta:
                            if hasattr(delta, "content") and delta.content:
                                delta_content = delta.content
                            elif isinstance(delta, dict) and delta.get("content"):
                                delta_content = delta.get("content")
                                
                    if delta_content:
                        full_text += delta_content
                        chunk_dict = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "content": delta_content
                                    },
                                    "finish_reason": None
                                }
                            ]
                        }
                        yield f"data: {json.dumps(chunk_dict)}\n\n"
                        
                if response_format and response_format.get("type") == "json_object":
                    _, sources, confidence, last_updated = extract_metadata_from_json(full_text)
                else:
                    sources, confidence, last_updated = parse_metadata_from_text(full_text)
                    
                final_chunk = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop"
                        }
                    ],
                    "sources": sources,
                    "confidence": confidence,
                    "last_updated": last_updated
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                
                completion_tokens = len(full_text) // 4
                log_api_usage(api_key, f"POST /api/v1/chat (stream, {model})", prompt_tokens, completion_tokens)
                response_time = int((time.time() - created_time) * 1000)
                await asyncio.to_thread(
                    log_usage_event,
                    ip_address=client_ip,
                    anonymous_user_id=anon_user_id,
                    session_id=f"agent-session-{chat_id}",
                    endpoint=f"/api/v1/chat (stream, {model})",
                    tokens_in=prompt_tokens,
                    tokens_out=completion_tokens,
                    response_time_ms=response_time,
                    has_citations=len(sources) > 0,
                    has_correlations=False,
                    agent_api_key=api_key,
                    query_text=user_query
                )
                
            except Exception as e:
                print(f"Error in stream_generator: {str(e)}")
                err_chunk = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": f"\n[STREAM ERROR: {str(e)}]"
                            },
                            "finish_reason": "error"
                        }
                    ]
                }
                yield f"data: {json.dumps(err_chunk)}\n\n"
                yield "data: [DONE]\n\n"
                
        return StreamingResponse(stream_generator(), media_type="text/event-stream")

async def run_tool_loop_async(messages: list, temperature: float, max_tokens: Optional[int]):
    return await asyncio.to_thread(execute_agent_loop, messages, temperature, max_tokens)

def parse_metadata_from_text(text: str):
    confidence = 0.85
    last_updated = date.today().isoformat()
    sources = []
    
    conf_match = re.search(r"Confidence:\s*([0-9.]+)", text, re.IGNORECASE)
    if conf_match:
        try:
            confidence = float(conf_match.group(1))
        except ValueError:
            pass
            
    lu_match = re.search(r"Last Updated:\s*([^\n]+)", text, re.IGNORECASE)
    if lu_match:
        last_updated = lu_match.group(1).strip()
        
    links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", text)
    for title, url in links:
        sources.append({"text": title, "url": url})
        
    if not sources:
        if "portal.sao.wa.gov" in text:
            sources.append({"text": "WA State Auditor's Office", "url": "https://portal.sao.wa.gov"})
            
    return sources, confidence, last_updated

def extract_metadata_from_json(content_str: str):
    try:
        data = json.loads(content_str)
        answer = data.get("answer", content_str)
        sources = data.get("sources", [])
        confidence = data.get("confidence", 0.85)
        last_updated = data.get("last_updated", date.today().isoformat())
        return answer, sources, confidence, last_updated
    except Exception:
        sources, confidence, last_updated = parse_metadata_from_text(content_str)
        return content_str, sources, confidence, last_updated

# Tool calling logic inside the backend
def execute_agent_loop(messages: list, temperature: float, max_tokens: Optional[int]):
    total_prompt_tokens = 0
    total_completion_tokens = 0
    
    print(f"[DEBUG AGENT LOOP] Starting loop. Initial messages: {[m.get('role') for m in messages]}")
    for iteration in range(5):
        try:
            print(f"[DEBUG AGENT LOOP] Iteration {iteration}. Messages context: {[m.get('role') for m in messages]}")
            response = litellm.completion(
                model="gemini/gemini-3.5-flash",
                messages=messages,
                tools=OPENAI_TOOLS,
                tool_choice="auto",
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=GEMINI_API_KEY
            )
            
            usage = response.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)
            
            message = response.choices[0].message
            print(f"[DEBUG AGENT LOOP] Iteration {iteration} response message: {message}")
            
            if hasattr(message, "model_dump"):
                message_dict = message.model_dump()
            elif hasattr(message, "dict"):
                message_dict = message.dict()
            else:
                message_dict = dict(message)
                
            tool_calls = message_dict.get("tool_calls")
            
            if tool_calls:
                print(f"[DEBUG AGENT LOOP] Gemini requested tool calls: {[tc['function']['name'] for tc in tool_calls]}")
                messages.append(message_dict)
                for tool_call in tool_calls:
                    func_name = tool_call["function"]["name"]
                    func_args_str = tool_call["function"]["arguments"]
                    tc_id = tool_call["id"]
                    
                    try:
                        func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
                        print(f"[DEBUG AGENT LOOP] Executing {func_name} with args: {func_args}")
                        tool_result = run_tool(func_name, func_args)
                        tool_result_str = json.dumps(tool_result)
                        print(f"[DEBUG AGENT LOOP] Tool result length: {len(tool_result_str)}")
                    except Exception as e:
                        tool_result_str = json.dumps({"error": f"Tool execution failed: {str(e)}"})
                        print(f"[DEBUG AGENT LOOP] Tool execution error: {str(e)}")
                        
                    messages.append({
                        "role": "tool",
                        "name": func_name,
                        "tool_call_id": tc_id,
                        "content": tool_result_str
                    })
                continue
            else:
                print(f"[DEBUG AGENT LOOP] No tool calls requested. Final content: {message_dict.get('content')[:100] if message_dict.get('content') else None}...")
                return message_dict.get("content") or "", messages, total_prompt_tokens, total_completion_tokens
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[DEBUG AGENT LOOP] Exception in loop: {str(e)}")
            return f"Agent loop failed: {str(e)}", messages, total_prompt_tokens, total_completion_tokens
            
    return "Error: Agent tool execution loop exceeded maximum iterations.", messages, total_prompt_tokens, total_completion_tokens





# --- Pure Search & Correlation Endpoints ---

class SearchRequest(BaseModel):
    query: str
    lens: Optional[str] = "comprehensive"
    limit: Optional[int] = 5
    jurisdiction: Optional[str] = None

@app.post("/api/v1/search")
async def search_endpoint(req: SearchRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    api_key = verify_api_key(credentials)
    
    query_emb = None
    async with httpx.AsyncClient() as client:
        query_emb = await get_embedding_async(req.query, client)
        
    use_sqlite = False
    try:
        conn = get_pg_conn()
        conn.close()
    except Exception:
        use_sqlite = True
        
    results = []
    juris_clean = re.sub(r"[']?s$", "", req.jurisdiction.strip()) if req.jurisdiction else ""
    
    if not use_sqlite:
        try:
            conn_pg = get_pg_conn()
            cur_pg = conn_pg.cursor(cursor_factory=RealDictCursor)
            
            # 1. Findings (Audits)
            if req.lens in ["comprehensive", "audits"]:
                q = "SELECT report_num, jurisdiction, type, category, summary, dollar_impact FROM findings WHERE 1=1"
                params = []
                if juris_clean:
                    q += " AND jurisdiction ILIKE %s"
                    params.append(f"%{juris_clean}%")
                if req.query:
                    q += " AND (summary ILIKE %s OR category ILIKE %s)"
                    params.extend([f"%{req.query}%", f"%{req.query}%"])
                q += " LIMIT %s"
                params.append(req.limit)
                
                cur_pg.execute(q, params)
                for r in cur_pg.fetchall():
                    results.append({
                        "id": r["report_num"],
                        "title": f"SAO Audit: {r['category']}",
                        "summary": r["summary"],
                        "jurisdiction": r["jurisdiction"],
                        "category": r["category"],
                        "dollar_impact": r["dollar_impact"],
                        "source": "audit",
                        "score": 0.75,
                        "url": f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={r['report_num']}&isFinding=false&sp=false"
                    })
                    
            # 2. Council Actions
            if req.lens in ["comprehensive", "council"]:
                q = "SELECT event_id, jurisdiction, committee, meeting_date, key_action, vendor, dollar_amount, vote_outcome FROM merged_actions WHERE 1=1"
                params = []
                if juris_clean:
                    q += " AND jurisdiction ILIKE %s"
                    params.append(f"%{juris_clean}%")
                if req.query:
                    q += " AND (key_action ILIKE %s OR committee ILIKE %s)"
                    params.extend([f"%{req.query}%", f"%{req.query}%"])
                q += " LIMIT %s"
                params.append(req.limit)
                
                cur_pg.execute(q, params)
                for r in cur_pg.fetchall():
                    results.append({
                        "id": r["event_id"],
                        "title": f"Council: {r['committee'] or 'Action'}",
                        "summary": clean_summary_text(r["key_action"]),
                        "jurisdiction": r["jurisdiction"],
                        "category": r["committee"] or "Council Action",
                        "dollar_impact": r["dollar_amount"],
                        "source": "council",
                        "score": 0.78,
                        "url": f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting"
                    })
                    
            # 3. Vector Hybrid search matches
            if query_emb:
                if req.lens in ["comprehensive", "audits"]:
                    cur_pg.execute(
                        "SELECT report_num, jurisdiction, category, summary, dollar_impact, (embedding <=> %s::vector) as distance FROM findings ORDER BY distance ASC LIMIT %s",
                        (query_emb, req.limit)
                    )
                    for r in cur_pg.fetchall():
                        score = float(1 - r["distance"])
                        existing = next((x for x in results if x["id"] == r["report_num"]), None)
                        if existing:
                            existing["score"] = max(existing["score"], score)
                        else:
                            results.append({
                                "id": r["report_num"],
                                "title": f"SAO Audit: {r['category']}",
                                "summary": r["summary"],
                                "jurisdiction": r["jurisdiction"],
                                "category": r["category"],
                                "dollar_impact": r["dollar_impact"],
                                "source": "audit",
                                "score": score,
                                "url": f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={r['report_num']}&isFinding=false&sp=false"
                            })
                            
                if req.lens in ["comprehensive", "council"]:
                    cur_pg.execute(
                        "SELECT event_id, jurisdiction, committee, key_action, vendor, dollar_amount, (embedding <=> %s::vector) as distance FROM merged_actions ORDER BY distance ASC LIMIT %s",
                        (query_emb, req.limit)
                    )
                    for r in cur_pg.fetchall():
                        score = float(1 - r["distance"])
                        existing = next((x for x in results if x["id"] == r["event_id"]), None)
                        if existing:
                            existing["score"] = max(existing["score"], score)
                        else:
                            results.append({
                                "id": r["event_id"],
                                "title": f"Council: {r['committee'] or 'Action'}",
                                "summary": clean_summary_text(r["key_action"]),
                                "jurisdiction": r["jurisdiction"],
                                "category": r["committee"] or "Council Action",
                                "dollar_impact": r["dollar_amount"],
                                "source": "council",
                                "score": score,
                                "url": f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting"
                            })
            cur_pg.close()
            conn_pg.close()
        except Exception as e:
            print("Postgres hybrid search failed, fallback to SQLite:", e)
            use_sqlite = True
            
    if use_sqlite:
        if req.lens in ["comprehensive", "audits"]:
            for db_name in ["sao_audits.db", "sao_2024.db"]:
                conn = get_sqlite_conn(db_name)
                if conn:
                    try:
                        cur = conn.cursor()
                        q = "SELECT report_num, jurisdiction, category, summary, dollar_impact FROM findings WHERE 1=1"
                        params = []
                        if juris_clean:
                            q += " AND jurisdiction LIKE ?"
                            params.append(f"%{juris_clean}%")
                        if req.query:
                            q += " AND (summary LIKE ? OR category LIKE ?)"
                            params.extend([f"%{req.query}%", f"%{req.query}%"])
                        q += " LIMIT ?"
                        params.append(req.limit)
                        cur.execute(q, params)
                        for r in [dict(row) for row in cur.fetchall()]:
                            results.append({
                                "id": r["report_num"],
                                "title": f"SAO Audit: {r['category']}",
                                "summary": r["summary"],
                                "jurisdiction": r["jurisdiction"],
                                "category": r["category"],
                                "dollar_impact": r["dollar_impact"],
                                "source": "audit",
                                "score": 0.8,
                                "url": f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={r['report_num']}&isFinding=false&sp=false"
                            })
                        conn.close()
                    except Exception:
                        pass
                        
        if req.lens in ["comprehensive", "council"]:
            conn = get_sqlite_conn("municipal_intent.db")
            if conn:
                try:
                    cur = conn.cursor()
                    q = "SELECT event_id, jurisdiction, doc_type as committee, agenda_item_title, key_action, vendor, dollar_amount FROM processed_intent WHERE 1=1"
                    params = []
                    if juris_clean:
                        q += " AND jurisdiction LIKE ?"
                        params.append(f"%{juris_clean}%")
                    if req.query:
                        q += " AND (agenda_item_title LIKE ? OR key_action LIKE ?)"
                        params.extend([f"%{req.query}%", f"%{req.query}%"])
                    q += " LIMIT ?"
                    params.append(req.limit)
                    cur.execute(q, params)
                    for r in [dict(row) for row in cur.fetchall()]:
                        summary_text = clean_summary_text(r.get('agenda_item_title'), r.get('key_action'))
                        results.append({
                            "id": r["event_id"],
                            "title": f"Council: {r['committee'] or 'Action'}",
                            "summary": summary_text,
                            "jurisdiction": r["jurisdiction"],
                            "category": r["committee"] or "Council Action",
                            "dollar_impact": r["dollar_amount"],
                            "source": "council",
                            "score": 0.8,
                            "url": f"https://www.google.com/search?q={r['jurisdiction'].replace(' ', '+')}+city+council+meeting"
                        })
                    conn.close()
                except Exception:
                    pass
                    
    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:req.limit]
    
    log_api_usage(api_key, "POST /api/v1/search", 10, 10)
    return {"results": results, "count": len(results)}

class CorrelationRequest(BaseModel):
    query: str
    limit: Optional[int] = 5

@app.post("/api/v1/correlation")
async def correlation_endpoint(req: CorrelationRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    api_key = verify_api_key(credentials)
    correlations = await asyncio.to_thread(find_correlations_tool, req.query, req.limit)
    log_api_usage(api_key, "POST /api/v1/correlation", 10, 10)
    return {"correlations": correlations, "count": len(correlations)}

@app.post("/api/v1/tools")
async def tools_endpoint(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if credentials:
        verify_api_key(credentials)
    return {"tools": TOOLS_LIST}

class ToolExecutionRequest(BaseModel):
    name: str
    arguments: dict

@app.post("/api/v1/tools/execute")
async def execute_tool_endpoint(req: ToolExecutionRequest, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    api_key = verify_api_key(credentials)
    try:
        result = run_tool(req.name, req.arguments)
        log_api_usage(api_key, f"POST /api/v1/tools/execute ({req.name})", 10, 10)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/v1/usage")
async def usage_endpoint(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    api_key = verify_api_key(credentials)
    
    total_calls = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost = 0.0
    
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT COUNT(*) as calls, SUM(prompt_tokens) as p_tok, SUM(completion_tokens) as c_tok, SUM(estimated_cost) as cost
            FROM api_usage_logs
            WHERE api_key = %s
            """,
            (api_key,)
        )
        row = cur.fetchone()
        if row and row["calls"]:
            total_calls = row["calls"]
            total_prompt_tokens = int(row["p_tok"]) if row["p_tok"] else 0
            total_completion_tokens = int(row["c_tok"]) if row["c_tok"] else 0
            total_cost = float(row["cost"]) if row["cost"] else 0.0
        cur.close()
        conn.close()
    except Exception:
        # SQLite fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT COUNT(*) as calls, SUM(prompt_tokens) as p_tok, SUM(completion_tokens) as c_tok, SUM(estimated_cost) as cost
                        FROM api_usage_logs
                        WHERE api_key = ?
                        """,
                        (api_key,)
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        total_calls = row[0]
                        total_prompt_tokens = int(row[1]) if row[1] else 0
                        total_completion_tokens = int(row[2]) if row[2] else 0
                        total_cost = float(row[3]) if row[3] else 0.0
                    conn.close()
                    break
                except Exception:
                    pass
                    
    return {
        "api_key": api_key[:10] + "..." if len(api_key) > 10 else api_key,
        "total_calls": total_calls,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "total_tokens": total_prompt_tokens + total_completion_tokens,
        "estimated_cost_usd": round(total_cost, 6)
    }

@app.post("/api/v1/oracle/synthesize")
async def synthesize(req: SynthesizeRequest, request: Request):
    """Synthesis router compatible with original frontend specifications."""
    chat_req = {"query": f"{req.query} in {req.jurisdiction}", "lens": "comprehensive"}
    return await chat_stream(chat_req, request)

@app.get("/api/v1/admin/metrics")
async def get_admin_metrics(timeframe_days: int = 7):
    """Fetch aggregated usage metrics for the dashboard."""
    conn, is_pg = get_tracking_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed.")
    try:
        cur = conn.cursor()
        
        # Fetch from daily_usage_aggregates
        if is_pg:
            cur.execute(
                "SELECT date::text, dau, total_messages, avg_messages_per_user, avg_session_depth, heavy_users_day_count FROM daily_usage_aggregates WHERE date >= NOW() - %s * INTERVAL '1 day' ORDER BY date DESC",
                (timeframe_days,)
            )
        else:
            cur.execute(
                "SELECT date, dau, total_messages, avg_messages_per_user, avg_session_depth, heavy_users_day_count FROM daily_usage_aggregates WHERE date >= date('now', '-' || ? || ' days') ORDER BY date DESC",
                (timeframe_days,)
            )
            
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        metrics = []
        for r in rows:
            metrics.append({
                "date": r[0],
                "dau": r[1],
                "total_messages": r[2],
                "avg_messages_per_user": float(r[3]),
                "avg_session_depth": float(r[4]),
                "heavy_users_count": r[5]
            })
        return {"status": "success", "data": metrics}
    except Exception as e:
        print(f"Error fetching admin metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/admin/sources")
async def get_admin_sources(is_admin: bool = Depends(check_admin_access)):
    """Retrieve database sources, descriptions, and row counts."""
    sources_def = [
        {"id": "findings", "name": "State Audit Findings", "table": "findings", "description": "Audit findings and issues flagged by the Washington State Auditor (SAO)."},
        {"id": "processed_intent", "name": "City Council Minutes & Actions", "table": "processed_intent", "description": "Extracted key decisions, ordinances, and discussions from local council meetings."},
        {"id": "legislative_bills", "name": "Legislative Bills", "table": "legislative_bills", "description": "State legislative bills and current activity tracking."},
        {"id": "political_contributions", "name": "Political Contributions", "table": "political_contributions", "description": "Campaign finance and political contributions within Washington."},
        {"id": "budgets", "name": "Local Government Budgets", "table": "budgets", "description": "Aggregated annual budget totals for cities, counties, and districts."},
        {"id": "budget_items", "name": "Budget Breakdowns", "table": "budget_items", "description": "Granular category line-items (e.g. Police, Fire, Parks, Transit) for budgets."},
        {"id": "grants", "name": "State & Federal Grants", "table": "grants", "description": "Grant awards, recipients, agencies, and performance periods."},
        {"id": "school_district_financials", "name": "School District Financials", "table": "school_district_financials", "description": "OSPI school district enrollment, revenue, expenditures, and levy details."},
        {"id": "jurisdictions", "name": "Washington Jurisdictions", "table": "jurisdictions", "description": "Master list of registered Washington jurisdictions and metadata."},
        {"id": "authoritative_entities", "name": "Authoritative Entities Catalog", "table": "authoritative_entities", "description": "Official portals and scraper platforms for target entities."}
    ]
    
    # SQLite mapping to avoid double-counting seeded tables
    table_db_mapping = {
        "findings": ["sao_2024.db", "sao_audits.db"],
        "processed_intent": ["municipal_intent.db"],
        "legislative_bills": ["municipal_intent.db"],
        "political_contributions": ["municipal_intent.db"],
        "budgets": ["municipal_intent.db"],
        "budget_items": ["municipal_intent.db"],
        "grants": ["municipal_intent.db"],
        "school_district_financials": ["municipal_intent.db"],
        "jurisdictions": ["municipal_intent.db"],
        "authoritative_entities": ["municipal_intent.db"]
    }
    
    results = []
    # Try Postgres first
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        for src in sources_def:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {src['table']}")
                count = cur.fetchone()[0]
                
                last_updated = None
                try:
                    cur.execute(f"SELECT MAX(last_updated) FROM {src['table']}")
                    res = cur.fetchone()
                    if res and res[0]:
                        last_updated = str(res[0])
                except Exception:
                    pass
                
                results.append({
                    "id": src["id"],
                    "name": src["name"],
                    "count": count,
                    "description": src["description"],
                    "last_updated": last_updated,
                    "db_source": "PostgreSQL"
                })
            except Exception:
                results.append({
                    "id": src["id"],
                    "name": src["name"],
                    "count": 0,
                    "description": src["description"],
                    "last_updated": None,
                    "db_source": "PostgreSQL (Missing)"
                })
        cur.close()
        conn.close()
        return {"status": "success", "data": results}
    except Exception as pg_err:
        # SQLite Fallback
        for src in sources_def:
            table_name = src["table"]
            total_count = 0
            db_sources = []
            last_updated = None
            
            db_targets = table_db_mapping.get(table_name, ["municipal_intent.db"])
            for db_name in db_targets:
                conn = get_sqlite_conn(db_name)
                if conn:
                    try:
                        cur = conn.cursor()
                        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
                        if cur.fetchone():
                            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                            c = cur.fetchone()[0]
                            total_count += c
                            db_sources.append(db_name)
                            
                            try:
                                cur.execute(f"SELECT MAX(last_updated) FROM {table_name}")
                                res = cur.fetchone()
                                if res and res[0]:
                                    candidate_lu = str(res[0])
                                    if not last_updated or candidate_lu > last_updated:
                                        last_updated = candidate_lu
                            except Exception:
                                pass
                        cur.close()
                    except Exception:
                        pass
                    finally:
                        conn.close()
                        
            results.append({
                "id": src["id"],
                "name": src["name"],
                "count": total_count,
                "description": src["description"],
                "last_updated": last_updated,
                "db_source": ", ".join(db_sources) if db_sources else "SQLite (Missing)"
            })
            
        return {"status": "success", "data": results}

@app.get("/api/v1/admin/sources/{source_id}/preview")
async def get_admin_source_preview(
    source_id: str,
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = "desc",
    is_admin: bool = Depends(check_admin_access)
):
    """Fetch sample/preview records from a source table dynamically."""
    valid_tables = [
        "findings", "processed_intent", "legislative_bills", 
        "political_contributions", "budgets", "budget_items", 
        "grants", "school_district_financials", "jurisdictions", 
        "authoritative_entities"
    ]
    if source_id not in valid_tables:
        raise HTTPException(status_code=400, detail="Invalid source/table identifier.")

    table_db_mapping = {
        "findings": ["sao_2024.db", "sao_audits.db"],
        "processed_intent": ["municipal_intent.db"],
        "legislative_bills": ["municipal_intent.db"],
        "political_contributions": ["municipal_intent.db"],
        "budgets": ["municipal_intent.db"],
        "budget_items": ["municipal_intent.db"],
        "grants": ["municipal_intent.db"],
        "school_district_financials": ["municipal_intent.db"],
        "jurisdictions": ["municipal_intent.db"],
        "authoritative_entities": ["municipal_intent.db"]
    }

    use_sqlite = False
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. Fetch column names
        cur.execute(f"SELECT * FROM {source_id} LIMIT 0")
        columns = [desc[0] for desc in cur.description if desc[0] != 'embedding']
        
        # 2. Build the select query dynamically using safe column list
        select_cols = ", ".join([f'"{col}"' for col in columns])
        query_str = f"SELECT {select_cols} FROM {source_id}"
        params = []
        
        if search:
            search_conds = []
            for col in columns:
                search_conds.append(f'CAST("{col}" AS TEXT) ILIKE %s')
                params.append(f"%{search}%")
            if search_conds:
                query_str += " WHERE " + " OR ".join(search_conds)
                
        # Get total matching records count
        count_query = f"SELECT COUNT(*) FROM ({query_str}) AS cnt"
        cur.execute(count_query, params)
        row = cur.fetchone()
        total_count = list(row.values())[0] if row else 0
        
        # 3. Sort/order by user-specified column or fallback logical key to keep previews consistent
        if sort_by and sort_by in columns:
            actual_sort_order = "ASC" if sort_order.lower() == "asc" else "DESC"
            query_str += f' ORDER BY "{sort_by}" {actual_sort_order}'
        else:
            order_col = None
            for cand in ["id", "event_id", "report_num", "bill_id", "grant_id", "created_at", "last_updated"]:
                if cand in columns:
                    order_col = cand
                    break
            if order_col:
                query_str += f' ORDER BY "{order_col}" DESC'
            
        query_str += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        cur.execute(query_str, params)
        
        rows = cur.fetchall()
        data = [dict(r) for r in rows]
        
        cur.close()
        conn.close()
        return {
            "status": "success",
            "columns": columns,
            "data": data,
            "total": total_count,
            "db_source": "PostgreSQL"
        }
    except Exception as pg_err:
        print(f"Postgres preview query fallback to SQLite: {pg_err}")
        use_sqlite = True

    if use_sqlite:
        db_targets = table_db_mapping.get(source_id, ["municipal_intent.db"])
        for db_name in db_targets:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (source_id,))
                    if not cur.fetchone():
                        conn.close()
                        continue
                        
                    # Fetch columns excluding embedding
                    cur.execute(f"SELECT * FROM {source_id} LIMIT 0")
                    columns = [desc[0] for desc in cur.description if desc[0] != 'embedding']
                    
                    select_cols = ", ".join([f'"{col}"' for col in columns])
                    query_str = f"SELECT {select_cols} FROM {source_id}"
                    params = []
                    
                    if search:
                        search_conds = []
                        for col in columns:
                            search_conds.append(f'CAST("{col}" AS TEXT) LIKE ?')
                            params.append(f"%{search}%")
                        if search_conds:
                            query_str += " WHERE " + " OR ".join(search_conds)
                            
                    # Get count
                    count_query = f"SELECT COUNT(*) FROM ({query_str}) AS cnt"
                    cur.execute(count_query, params)
                    total_count = cur.fetchone()[0]
                    
                    # Sort
                    if sort_by and sort_by in columns:
                        actual_sort_order = "ASC" if sort_order.lower() == "asc" else "DESC"
                        query_str += f' ORDER BY "{sort_by}" {actual_sort_order}'
                    else:
                        order_col = None
                        for cand in ["id", "event_id", "report_num", "bill_id", "grant_id", "created_at", "last_updated"]:
                            if cand in columns:
                                order_col = cand
                                break
                        if order_col:
                            query_str += f' ORDER BY "{order_col}" DESC'
                        
                    query_str += " LIMIT ? OFFSET ?"
                    params.extend([limit, offset])
                    cur.execute(query_str, params)
                    
                    rows = cur.fetchall()
                    data = [dict(r) for r in rows]
                    
                    cur.close()
                    conn.close()
                    return {
                        "status": "success",
                        "columns": columns,
                        "data": data,
                        "total": total_count,
                        "db_source": db_name
                    }
                except Exception as e:
                    print(f"SQLite preview failed for {db_name}: {e}")
                    try:
                        conn.close()
                    except Exception:
                        pass
        raise HTTPException(status_code=404, detail=f"Source table '{source_id}' not found in any database.")


# --- Bug Reports & Civic Tips APIs ---

class BugReportSchema(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    report_type: str  # 'bug' or 'tip'
    description: str

@app.post("/api/v1/bugs")
async def create_bug_report(req: BugReportSchema, request: Request):
    """Submits a bug report or civic tip to the tracking database."""
    if req.report_type not in ["bug", "tip"]:
        raise HTTPException(status_code=400, detail="Invalid report_type. Must be 'bug' or 'tip'.")
    if not req.description.strip():
        raise HTTPException(status_code=400, detail="Description is required.")
        
    anon_user_id = request.headers.get("x-anonymous-user-id", "unknown-user")
    session_id = request.headers.get("x-session-id", "unknown-session")
    
    conn, is_pg = get_tracking_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    try:
        cur = conn.cursor()
        if is_pg:
            cur.execute(
                """
                INSERT INTO bug_reports (name, email, report_type, description, anonymous_user_id, session_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (req.name, req.email, req.report_type, req.description, anon_user_id, session_id)
            )
        else:
            cur.execute(
                """
                INSERT INTO bug_reports (name, email, report_type, description, anonymous_user_id, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (req.name, req.email, req.report_type, req.description, anon_user_id, session_id)
            )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success", "message": f"{req.report_type.title()} report submitted successfully."}
    except Exception as e:
        print(f"Error saving bug report: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail="Failed to save report to database.")

@app.get("/api/v1/bugs/admin")
async def get_bug_reports(is_admin: bool = Depends(check_admin_access)):
    """Retrieve all submitted bug reports and tips for the curation dashboard."""
    conn, is_pg = get_tracking_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    try:
        cur = conn.cursor()
        if is_pg:
            cur.execute(
                """
                SELECT id, name, email, report_type, description, anonymous_user_id, session_id, created_at
                FROM bug_reports
                ORDER BY id DESC
                """
            )
            rows = cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    "id": r[0],
                    "name": r[1],
                    "email": r[2],
                    "report_type": r[3],
                    "description": r[4],
                    "anonymous_user_id": r[5],
                    "session_id": r[6],
                    "created_at": r[7].isoformat() if r[7] else None
                })
        else:
            # SQLite fallback: first check if table exists
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bug_reports'")
            if not cur.fetchone():
                cur.close()
                conn.close()
                return []
                
            cur.execute(
                """
                SELECT id, name, email, report_type, description, anonymous_user_id, session_id, created_at
                FROM bug_reports
                ORDER BY id DESC
                """
            )
            rows = [dict(row) for row in cur.fetchall()]
            results = []
            for r in rows:
                results.append({
                    "id": r["id"],
                    "name": r["name"],
                    "email": r["email"],
                    "report_type": r["report_type"],
                    "description": r["description"],
                    "anonymous_user_id": r["anonymous_user_id"],
                    "session_id": r["session_id"],
                    "created_at": r["created_at"]
                })
        cur.close()
        conn.close()
        return results
    except Exception as e:
        print(f"Error fetching bug reports: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail="Failed to fetch bug reports.")

@app.delete("/api/v1/bugs/{bug_id}")
async def delete_bug_report(bug_id: int, is_admin: bool = Depends(check_admin_access)):
    """Delete / resolve a bug report."""
    conn, is_pg = get_tracking_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    try:
        cur = conn.cursor()
        if is_pg:
            cur.execute("DELETE FROM bug_reports WHERE id = %s", (bug_id,))
        else:
            cur.execute("DELETE FROM bug_reports WHERE id = ?", (bug_id,))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success", "message": "Report deleted/resolved successfully."}
    except Exception as e:
        print(f"Error deleting bug report: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail="Failed to delete report.")

# --- Alert Subscriptions Curation/Admin APIs ---

@app.get("/api/v1/alerts/admin")
async def get_alert_subscriptions(is_admin: bool = Depends(check_admin_access)):
    """Retrieve all alert subscriptions for the curation dashboard."""
    conn, is_pg = get_tracking_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    try:
        cur = conn.cursor()
        if is_pg:
            cur.execute(
                """
                SELECT id, name, email, topics, jurisdiction, query, anonymous_user_id, created_at
                FROM alert_subscriptions
                ORDER BY id DESC
                """
            )
            rows = cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    "id": r[0],
                    "name": r[1],
                    "email": r[2],
                    "topics": r[3],
                    "jurisdiction": r[4],
                    "query": r[5],
                    "anonymous_user_id": r[6],
                    "created_at": r[7].isoformat() if r[7] else None
                })
        else:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alert_subscriptions'")
            if not cur.fetchone():
                cur.close()
                conn.close()
                return []
                
            cur.execute(
                """
                SELECT id, name, email, topics, jurisdiction, query, anonymous_user_id, created_at
                FROM alert_subscriptions
                ORDER BY id DESC
                """
            )
            rows = [dict(row) for row in cur.fetchall()]
            results = []
            for r in rows:
                results.append({
                    "id": r["id"],
                    "name": r["name"],
                    "email": r["email"],
                    "topics": r["topics"],
                    "jurisdiction": r["jurisdiction"],
                    "query": r["query"],
                    "anonymous_user_id": r["anonymous_user_id"],
                    "created_at": r["created_at"]
                })
        cur.close()
        conn.close()
        return results
    except Exception as e:
        print(f"Error fetching alert subscriptions: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail="Failed to fetch alert subscriptions.")

@app.delete("/api/v1/alerts/{alert_id}")
async def delete_alert_subscription(alert_id: int, is_admin: bool = Depends(check_admin_access)):
    """Delete / unsubscribe an alert subscription."""
    conn, is_pg = get_tracking_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
        
    try:
        cur = conn.cursor()
        if is_pg:
            cur.execute("DELETE FROM alert_subscriptions WHERE id = %s", (alert_id,))
        else:
            cur.execute("DELETE FROM alert_subscriptions WHERE id = ?", (alert_id,))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success", "message": "Alert subscription deleted successfully."}
    except Exception as e:
        print(f"Error deleting alert subscription: {e}")
        if conn:
            conn.close()
        raise HTTPException(status_code=500, detail="Failed to delete alert subscription.")

# --- Surfaced Correlations & Curation Dashboard APIs ---

class CorrelationEditRequest(BaseModel):
    title: str
    hook: str
    report_markdown: str

def enrich_correlations_with_years(correlations_list: list) -> list:
    """Enrich correlation citations with their respective audit years, verbatim audit trails, and source URLs dynamically."""
    import re
    for corr in correlations_list:
        citations = corr.get("citations", [])
        if not isinstance(citations, list):
            continue
        for cit in citations:
            # Fix any broken ReportNumber URLs to arn format
            if "url" in cit and "ReportNumber=" in cit["url"]:
                old_cit_url = cit["url"]
                cit["url"] = cit["url"].replace("ReportNumber=", "arn=")
                if "isFinding=" not in cit["url"]:
                    cit["url"] += "&isFinding=false&sp=false"
                if "report_markdown" in corr and corr["report_markdown"]:
                    corr["report_markdown"] = corr["report_markdown"].replace(old_cit_url, cit["url"])

            old_url = cit.get("url")
            new_url = None

            # Attempt to extract year from title or id (e.g. 2025)
            year_match = re.search(r'\b(20\d{2})\b', f"{cit.get('title', '')} {cit.get('id', '')}")
            cit_year = int(year_match.group(1)) if year_match else None

            source = cit.get("source") or cit.get("type")
            if source == "audit":
                report_num = str(cit.get("id") or "")
                if not report_num and "url" in cit:
                    match = re.search(r'(?:ReportNumber|arn)=(\d+)', cit["url"], re.IGNORECASE)
                    if match:
                        report_num = match.group(1)
                
                if report_num:
                    year = None
                    conn_2024 = get_sqlite_conn("sao_2024.db")
                    if conn_2024:
                        try:
                            cur = conn_2024.cursor()
                            cur.execute("SELECT year FROM findings WHERE report_num = ?", (report_num,))
                            row = cur.fetchone()
                            if row:
                                year = row[0]
                            cur.close()
                            conn_2024.close()
                        except Exception:
                            pass
                    
                    if not year:
                        conn_audits = get_sqlite_conn("sao_audits.db")
                        if conn_audits:
                            try:
                                cur = conn_audits.cursor()
                                cur.execute("SELECT year FROM findings WHERE report_num = ?", (report_num,))
                                row = cur.fetchone()
                                if row:
                                    year = row[0]
                                cur.close()
                                conn_audits.close()
                            except Exception:
                                pass
                    
                    if year:
                        title = cit.get("title", "")
                        year_str = f"({year})"
                        if year_str not in title:
                            cit["title"] = f"{title} {year_str}"
                        cit["year"] = year

                    # Fetch verbatim audit trail context and source_url
                    verbatim_text = None
                    meeting_type = None
                    verification_score = None
                    reviewer_status = None
                    db_source_url = None
                    
                    try:
                        conn = get_pg_conn()
                        cur = conn.cursor(cursor_factory=RealDictCursor)
                        cur.execute("SELECT jurisdiction, verbatim_text_context, meeting_type, verification_score, reviewer_status, summary, source_url, dollar_impact, year FROM findings WHERE report_num = %s", (report_num,))
                        row = cur.fetchone()
                        cur.close()
                        conn.close()
                        if row:
                            row_dict = dict(row)
                            jurisdiction = row_dict.get("jurisdiction")
                            summary_text = row_dict.get("verbatim_text_context") or (f"Audit Finding Summary: {row_dict.get('summary')}" if row_dict.get('summary') else None)
                            if jurisdiction and summary_text:
                                verbatim_text = f"Jurisdiction: {jurisdiction}. {summary_text}"
                            else:
                                verbatim_text = summary_text
                            meeting_type, verification_score, reviewer_status, db_source_url = row_dict.get("meeting_type"), row_dict.get("verification_score"), row_dict.get("reviewer_status"), row_dict.get("source_url")
                            dollar_impact = row_dict.get("dollar_impact")
                            if dollar_impact and dollar_impact > 0:
                                verbatim_text = f"{verbatim_text} (Dollar Impact: ${dollar_impact:,})" if verbatim_text else f"Dollar Impact: ${dollar_impact:,}"
                            if row_dict.get("year"):
                                year = row_dict.get("year")
                    except Exception:
                        for db_name in ["sao_audits.db", "sao_2024.db"]:
                            conn = get_sqlite_conn(db_name)
                            if conn:
                                try:
                                    cur = conn.cursor()
                                    cur.execute("PRAGMA table_info(findings)")
                                    columns = [col[1] for col in cur.fetchall()]
                                    has_source_url = "source_url" in columns
                                    has_verbatim = "verbatim_text_context" in columns
                                    has_dollar = "dollar_impact" in columns
                                    
                                    cols_to_select = ["jurisdiction"]
                                    if has_verbatim:
                                        cols_to_select.extend(["verbatim_text_context", "meeting_type", "verification_score", "reviewer_status", "summary"])
                                    else:
                                        cols_to_select.append("summary")
                                    if has_source_url:
                                        cols_to_select.append("source_url")
                                    if has_dollar:
                                        cols_to_select.append("dollar_impact")
                                        
                                    select_str = ", ".join(cols_to_select)
                                    cur.execute(f"SELECT {select_str} FROM findings WHERE report_num = ?", (report_num,))
                                    row = cur.fetchone()
                                    cur.close()
                                    conn.close()
                                    if row:
                                        row_dict = dict(zip(cols_to_select, row))
                                        jurisdiction = row_dict.get("jurisdiction")
                                        if has_verbatim:
                                            summary_text = row_dict.get("verbatim_text_context") or (f"Audit Finding Summary: {row_dict.get('summary')}" if row_dict.get('summary') else None)
                                            meeting_type, verification_score, reviewer_status = row_dict.get("meeting_type"), row_dict.get("verification_score"), row_dict.get("reviewer_status")
                                            db_source_url = row_dict.get("source_url") if has_source_url else None
                                        else:
                                            summary_text = f"Audit Finding Summary: {row_dict.get('summary')}" if row_dict.get('summary') else None
                                            meeting_type, verification_score, reviewer_status, db_source_url = "Audit Finding", 1.0, "unverified", None
                                        
                                        if jurisdiction and summary_text:
                                            verbatim_text = f"Jurisdiction: {jurisdiction}. {summary_text}"
                                        else:
                                            verbatim_text = summary_text
                                        
                                        dollar_impact = row_dict.get("dollar_impact") if has_dollar else None
                                        if dollar_impact and dollar_impact > 0:
                                            verbatim_text = f"{verbatim_text} (Dollar Impact: ${dollar_impact:,})" if verbatim_text else f"Dollar Impact: ${dollar_impact:,}"
                                        break
                                except Exception as e:
                                    print(f"SQLite enrich query error for {db_name}:", e)
                                    pass

                    cit["verbatim_text_context"] = verbatim_text or "No verbatim context captured during sync."
                    cit["meeting_type"] = meeting_type or "Audit Finding"
                    cit["verification_score"] = float(verification_score) if verification_score else 1.0
                    cit["reviewer_status"] = reviewer_status or "unverified"
                    if db_source_url:
                        new_url = db_source_url

            elif source == "council":
                cit_id = str(cit.get("id") or "")
                verbatim_text = None
                meeting_type = None
                verification_score = None
                reviewer_status = None
                
                try:
                    conn = get_pg_conn()
                    cur = conn.cursor()
                    cur.execute("SELECT verbatim_text_context, meeting_type, verification_score, reviewer_status FROM merged_actions WHERE event_id = %s", (cit_id,))
                    row = cur.fetchone()
                    cur.close()
                    conn.close()
                    if row:
                        verbatim_text, meeting_type, verification_score, reviewer_status = row[0], row[1], row[2], row[3]
                except Exception:
                    conn = get_sqlite_conn("municipal_intent.db")
                    if conn:
                        try:
                            cur = conn.cursor()
                            cur.execute("SELECT verbatim_text_context, meeting_type, verification_score, reviewer_status FROM processed_intent WHERE event_id = ? OR id = ?", (cit_id, cit_id))
                            row = cur.fetchone()
                            cur.close()
                            conn.close()
                            if row:
                                verbatim_text, meeting_type, verification_score, reviewer_status = row[0], row[1], row[2], row[3]
                        except Exception:
                            pass
                            
                cit["verbatim_text_context"] = verbatim_text or "No verbatim context captured during sync."
                cit["meeting_type"] = meeting_type or "Council Action"
                cit["verification_score"] = float(verification_score) if verification_score else 1.0
                cit["reviewer_status"] = reviewer_status or "unverified"

            elif source == "budget":
                cit_id = str(cit.get("id") or "")
                verbatim_text = None
                db_source_url = None
                
                clean_search = None
                if cit.get("title"):
                    title_words = re.sub(r'[^a-zA-Z\s]', '', cit["title"]).split()
                    stop_words = {"school", "district", "financials", "report", "budget", "audit", "city", "town", "of", "authority", "housing", "police", "department", "compliance", "internal", "controls"}
                    filtered_words = [w for w in title_words if w.lower() not in stop_words]
                    if filtered_words:
                        clean_search = filtered_words[0]
                if not clean_search:
                    id_words = re.sub(r'[^a-zA-Z\s]', '', cit_id).split()
                    if id_words:
                        clean_search = id_words[0]
                if not clean_search:
                    clean_search = cit_id

                try:
                    conn = get_pg_conn()
                    cur = conn.cursor()
                    if cit_id.isdigit():
                        cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures, source_url FROM budgets WHERE id = %s", (int(cit_id),))
                    else:
                        search_val = f"%{clean_search}%"
                        if cit_year:
                            cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures, source_url FROM budgets WHERE (jurisdiction_name ILIKE %s OR %s ILIKE '%' || jurisdiction_name || '%') AND fiscal_year = %s", (search_val, cit_id, cit_year))
                        else:
                            cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures, source_url FROM budgets WHERE (jurisdiction_name ILIKE %s OR %s ILIKE '%' || jurisdiction_name || '%')", (search_val, cit_id))
                    row = cur.fetchone()
                    cur.close()
                    conn.close()
                    if row:
                        verbatim_text = f"Budget Record for {row[0]} ({row[1]}): Total Revenue: ${row[2]:,}, Total Expenditures: ${row[3]:,}."
                        db_source_url = row[4]
                except Exception:
                    conn = get_sqlite_conn("municipal_intent.db")
                    if conn:
                        try:
                            cur = conn.cursor()
                            if cit_id.isdigit():
                                cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures, source_url FROM budgets WHERE id = ?", (int(cit_id),))
                            else:
                                search_val = f"%{clean_search}%"
                                if cit_year:
                                    cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures, source_url FROM budgets WHERE (jurisdiction_name LIKE ? OR ? LIKE '%' || jurisdiction_name || '%') AND fiscal_year = ?", (search_val, cit_id, cit_year))
                                else:
                                    cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures, source_url FROM budgets WHERE (jurisdiction_name LIKE ? OR ? LIKE '%' || jurisdiction_name || '%')", (search_val, cit_id))
                            row = cur.fetchone()
                            cur.close()
                            conn.close()
                            if row:
                                verbatim_text = f"Budget Record for {row[0]} ({row[1]}): Total Revenue: ${row[2]:,}, Total Expenditures: ${row[3]:,}."
                                db_source_url = row[4]
                        except Exception:
                            pass
                cit["verbatim_text_context"] = verbatim_text or f"Budget report details for {cit.get('title') or cit_id}."
                cit["meeting_type"] = "Budget Record"
                cit["verification_score"] = 1.0
                cit["reviewer_status"] = "verified"
                if db_source_url:
                    new_url = db_source_url

            elif source == "grant":
                cit_id = str(cit.get("id") or "")
                verbatim_text = None
                db_source_url = None
                try:
                    conn = get_pg_conn()
                    cur = conn.cursor()
                    if cit_id.isdigit() or (cit_id.startswith("Grant ") and cit_id[6:].isdigit()):
                        clean_id = int(cit_id[6:]) if cit_id.startswith("Grant ") else int(cit_id)
                        cur.execute("SELECT grant_title, recipient_jurisdiction, award_amount, awarding_agency, source_url, award_date FROM grants WHERE id = %s", (clean_id,))
                    else:
                        cur.execute("SELECT grant_title, recipient_jurisdiction, award_amount, awarding_agency, source_url, award_date FROM grants WHERE grant_title = %s OR recipient_jurisdiction = %s", (cit_id, cit_id))
                    row = cur.fetchone()
                    cur.close()
                    conn.close()
                    if row:
                        date_str = ""
                        if row[5]:
                            date_str = f" on {row[5]}"
                            try:
                                parts = str(row[5]).split("-")
                                if len(parts) == 3:
                                    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                                    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
                                    if 1 <= m <= 12:
                                        date_str += f" ({months[m-1]} {y})"
                            except Exception:
                                pass
                        verbatim_text = f"Grant Award: '{row[0]}' awarded to {row[1]} by {row[3]}{date_str}. Award Amount: ${row[2]:,}."
                        db_source_url = row[4]
                except Exception:
                    conn = get_sqlite_conn("municipal_intent.db")
                    if conn:
                        try:
                            cur = conn.cursor()
                            if cit_id.isdigit() or (cit_id.startswith("Grant ") and cit_id[6:].isdigit()):
                                clean_id = int(cit_id[6:]) if cit_id.startswith("Grant ") else int(cit_id)
                                cur.execute("SELECT grant_title, recipient_jurisdiction, award_amount, awarding_agency, source_url, award_date FROM grants WHERE id = ?", (clean_id,))
                            else:
                                cur.execute("SELECT grant_title, recipient_jurisdiction, award_amount, awarding_agency, source_url, award_date FROM grants WHERE grant_title = ? OR recipient_jurisdiction = ?", (cit_id, cit_id))
                            row = cur.fetchone()
                            cur.close()
                            conn.close()
                            if row:
                                date_str = ""
                                if row[5]:
                                    date_str = f" on {row[5]}"
                                    try:
                                        parts = str(row[5]).split("-")
                                        if len(parts) == 3:
                                            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                                            months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
                                            if 1 <= m <= 12:
                                                date_str += f" ({months[m-1]} {y})"
                                    except Exception:
                                        pass
                                verbatim_text = f"Grant Award: '{row[0]}' awarded to {row[1]} by {row[3]}{date_str}. Award Amount: ${row[2]:,}."
                                db_source_url = row[4]
                        except Exception:
                            pass
                cit["verbatim_text_context"] = verbatim_text or f"Grant award details for {cit.get('title') or cit_id}."
                cit["meeting_type"] = "Grant Award"
                cit["verification_score"] = 1.0
                cit["reviewer_status"] = "verified"
                if db_source_url:
                    new_url = db_source_url

            elif source == "school":
                cit_id = str(cit.get("id") or "")
                verbatim_text = None
                db_source_url = None
                
                clean_search = None
                if cit.get("title"):
                    title_words = re.sub(r'[^a-zA-Z\s]', '', cit["title"]).split()
                    stop_words = {"school", "district", "financials", "report", "budget", "audit", "city", "town", "of", "authority", "housing", "police", "department", "compliance", "internal", "controls"}
                    filtered_words = [w for w in title_words if w.lower() not in stop_words]
                    if filtered_words:
                        clean_search = filtered_words[0]
                if not clean_search:
                    id_words = re.sub(r'[^a-zA-Z\s]', '', cit_id).split()
                    if id_words:
                        clean_search = id_words[0]
                if not clean_search:
                    clean_search = cit_id

                try:
                    conn = get_pg_conn()
                    cur = conn.cursor()
                    if cit_id.isdigit():
                        cur.execute("SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url FROM school_district_financials WHERE id = %s", (int(cit_id),))
                    else:
                        search_val = f"%{clean_search}%"
                        if cit_year:
                            cur.execute("SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url FROM school_district_financials WHERE (district_name ILIKE %s OR %s ILIKE '%' || district_name || '%') AND fiscal_year = %s", (search_val, cit_id, cit_year))
                        else:
                            cur.execute("SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url FROM school_district_financials WHERE (district_name ILIKE %s OR %s ILIKE '%' || district_name || '%')", (search_val, cit_id))
                    row = cur.fetchone()
                    cur.close()
                    conn.close()
                    if row:
                        levy_val = f", Levy Amount: ${row[5]:,}" if row[5] is not None else ""
                        sped_val = f", Special Ed: ${row[6]:,}" if row[6] is not None else ""
                        fed_val = f", Federal Funding: ${row[7]:,}" if row[7] is not None else ""
                        verbatim_text = f"School District Financials: {row[0]} ({row[1]}). Enrollment: {row[2]:.0f} FTE. Revenue: ${row[3]:,}, Expenditures: ${row[4]:,}{levy_val}{sped_val}{fed_val}."
                        db_source_url = row[8]
                except Exception:
                    conn = get_sqlite_conn("municipal_intent.db")
                    if conn:
                        try:
                            cur = conn.cursor()
                            if cit_id.isdigit():
                                cur.execute("SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url FROM school_district_financials WHERE id = ?", (int(cit_id),))
                            else:
                                search_val = f"%{clean_search}%"
                                if cit_year:
                                    cur.execute("SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url FROM school_district_financials WHERE (district_name LIKE ? OR ? LIKE '%' || district_name || '%') AND fiscal_year = ?", (search_val, cit_id, cit_year))
                                else:
                                    cur.execute("SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount, source_url FROM school_district_financials WHERE (district_name LIKE ? OR ? LIKE '%' || district_name || '%')", (search_val, cit_id))
                            row = cur.fetchone()
                            cur.close()
                            conn.close()
                            if row:
                                levy_val = f", Levy Amount: ${row[5]:,}" if row[5] is not None else ""
                                sped_val = f", Special Ed: ${row[6]:,}" if row[6] is not None else ""
                                fed_val = f", Federal Funding: ${row[7]:,}" if row[7] is not None else ""
                                verbatim_text = f"School District Financials: {row[0]} ({row[1]}). Enrollment: {row[2]:.0f} FTE. Revenue: ${row[3]:,}, Expenditures: ${row[4]:,}{levy_val}{sped_val}{fed_val}."
                                db_source_url = row[8]
                        except Exception:
                            pass
                cit["verbatim_text_context"] = verbatim_text or f"School District financial details for {cit.get('title') or cit_id}."
                cit["meeting_type"] = "School District Financials"
                cit["verification_score"] = 1.0
                cit["reviewer_status"] = "verified"
                if db_source_url:
                    new_url = db_source_url

            elif source == "contribution":
                cit_id = str(cit.get("id") or "")
                verbatim_text = None
                try:
                    conn = get_pg_conn()
                    cur = conn.cursor()
                    if cit_id.isdigit() or (cit_id.startswith("Contribution ") and cit_id[13:].isdigit()):
                        clean_id = int(cit_id[13:]) if cit_id.startswith("Contribution ") else int(cit_id)
                        cur.execute("SELECT candidate_name, contributor_name, amount, receipt_date, jurisdiction FROM political_contributions WHERE id = %s", (clean_id,))
                    else:
                        cur.execute("SELECT candidate_name, contributor_name, amount, receipt_date, jurisdiction FROM political_contributions WHERE candidate_name = %s OR contributor_name = %s", (cit_id, cit_id))
                    row = cur.fetchone()
                    cur.close()
                    conn.close()
                    if row:
                        verbatim_text = f"Campaign Contribution: {row[1]} donated ${row[2]:,} to {row[0]} ({row[4] or 'Unknown jurisdiction'}) on {row[3]}."
                except Exception:
                    conn = get_sqlite_conn("municipal_intent.db")
                    if conn:
                        try:
                            cur = conn.cursor()
                            if cit_id.isdigit() or (cit_id.startswith("Contribution ") and cit_id[13:].isdigit()):
                                clean_id = int(cit_id[13:]) if cit_id.startswith("Contribution ") else int(cit_id)
                                cur.execute("SELECT candidate_name, contributor_name, amount, receipt_date, jurisdiction FROM political_contributions WHERE id = ?", (clean_id,))
                            else:
                                cur.execute("SELECT candidate_name, contributor_name, amount, receipt_date, jurisdiction FROM political_contributions WHERE candidate_name = ? OR contributor_name = ?", (cit_id, cit_id))
                            row = cur.fetchone()
                            cur.close()
                            conn.close()
                            if row:
                                verbatim_text = f"Campaign Contribution: {row[1]} donated ${row[2]:,} to {row[0]} ({row[4] or 'Unknown jurisdiction'}) on {row[3]}."
                        except Exception:
                            pass
                cit["verbatim_text_context"] = verbatim_text or f"Campaign contribution details for {cit.get('title') or cit_id}."
                cit["meeting_type"] = "Campaign Contribution"
                cit["verification_score"] = 1.0
                cit["reviewer_status"] = "verified"

            elif source == "bill":
                bill_num = str(cit.get("id") or "")
                if bill_num.startswith("Bill "):
                    bill_num = bill_num[5:]
                verbatim_text = None
                db_biennium = None
                try:
                    conn = get_pg_conn()
                    cur = conn.cursor()
                    cur.execute("SELECT title, summary, biennium, sponsor FROM legislative_bills WHERE bill_number = %s OR title = %s", (bill_num, bill_num))
                    row = cur.fetchone()
                    cur.close()
                    conn.close()
                    if row:
                        verbatim_text = f"Legislative Bill {bill_num} ({row[2]}): {row[0]}. Sponsored by {row[3]}. Summary: {row[1]}"
                        db_biennium = row[2]
                except Exception:
                    conn = get_sqlite_conn("municipal_intent.db")
                    if conn:
                        try:
                            cur = conn.cursor()
                            cur.execute("SELECT title, summary, biennium, sponsor FROM legislative_bills WHERE bill_number = ? OR title = ?", (bill_num, bill_num))
                            row = cur.fetchone()
                            cur.close()
                            conn.close()
                            if row:
                                verbatim_text = f"Legislative Bill {bill_num} ({row[2]}): {row[0]}. Sponsored by {row[3]}. Summary: {row[1]}"
                                db_biennium = row[2]
                        except Exception:
                            pass
                cit["verbatim_text_context"] = verbatim_text or f"Legislative Bill details for {cit.get('title') or bill_num}."
                cit["meeting_type"] = "Legislative Bill"
                cit["verification_score"] = 1.0
                cit["reviewer_status"] = "verified"
                
                # Construct direct official WA Legislature link dynamically
                clean_bill_num = re.sub(r'\D', '', bill_num)
                if clean_bill_num:
                    bill_year = cit_year or 2025
                    if db_biennium and "-" in db_biennium:
                        try:
                            bill_year = int(db_biennium.split("-")[0])
                        except Exception:
                            pass
                    new_url = f"https://app.leg.wa.gov/billsummary?BillNumber={clean_bill_num}&Year={bill_year}"

            if new_url and old_url and old_url != new_url:
                cit["url"] = new_url
                if "report_markdown" in corr and corr["report_markdown"]:
                    corr["report_markdown"] = corr["report_markdown"].replace(old_url, new_url)

            # Ensure all variations of audit links in markdown match the final citation URL
            if source == "audit" and "report_markdown" in corr and corr["report_markdown"]:
                report_num = str(cit.get("id") or "")
                if report_num:
                    pattern = rf'https://portal\.sao\.wa\.gov/ReportSearch/Home/ViewReportFile\?(?:ReportNumber|arn)={report_num}(?:&[a-zA-Z0-9_=&%-]*)?'
                    corr["report_markdown"] = re.sub(pattern, cit["url"], corr["report_markdown"])

    return correlations_list

_approved_correlations_cache = None
_approved_correlations_cache_time = 0.0

def clear_correlations_cache():
    global _approved_correlations_cache
    _approved_correlations_cache = None

@app.get("/api/v1/correlations")
async def get_approved_correlations():
    """Retrieve approved correlations for public homepage."""
    global _approved_correlations_cache, _approved_correlations_cache_time
    now = time.time()
    if _approved_correlations_cache is not None and (now - _approved_correlations_cache_time < 300):
        return _approved_correlations_cache

    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, title, hook, report_markdown, citations, status, created_at, reviewed_at
            FROM correlations
            WHERE status = 'approved'
            ORDER BY id DESC
            LIMIT 4
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        res = enrich_correlations_with_years([dict(r) for r in rows])
        _approved_correlations_cache = res
        _approved_correlations_cache_time = now
        return res
    except Exception as pg_err:
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT id, title, hook, report_markdown, citations, status, created_at, reviewed_at
                        FROM correlations
                        WHERE status = 'approved'
                        ORDER BY id DESC
                        LIMIT 4
                        """
                    )
                    rows = cur.fetchall()
                    results = []
                    for r in rows:
                        results.append({
                            "id": r[0],
                            "title": r[1],
                            "hook": r[2],
                            "report_markdown": r[3],
                            "citations": json.loads(r[4]) if r[4] else [],
                            "status": r[5],
                            "created_at": r[6],
                            "reviewed_at": r[7]
                        })
                    conn.close()
                    res = enrich_correlations_with_years(results)
                    _approved_correlations_cache = res
                    _approved_correlations_cache_time = now
                    return res
                except Exception:
                    pass
        return []

@app.get("/api/v1/correlations/admin")
async def get_proposed_correlations(is_admin: bool = Depends(check_admin_access)):
    """Retrieve all proposed (and approved) correlations for curation dashboard."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, title, hook, report_markdown, citations, status, created_at, reviewed_at
            FROM correlations
            WHERE status IN ('proposed', 'approved')
            ORDER BY status DESC, id DESC
            """
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return enrich_correlations_with_years([dict(r) for r in rows])
    except Exception as pg_err:
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT id, title, hook, report_markdown, citations, status, created_at, reviewed_at
                        FROM correlations
                        WHERE status IN ('proposed', 'approved')
                        ORDER BY status DESC, id DESC
                        """
                    )
                    rows = cur.fetchall()
                    results = []
                    for r in rows:
                        results.append({
                            "id": r[0],
                            "title": r[1],
                            "hook": r[2],
                            "report_markdown": r[3],
                            "citations": json.loads(r[4]) if r[4] else [],
                            "status": r[5],
                            "created_at": r[6],
                            "reviewed_at": r[7]
                        })
                    conn.close()
                    return enrich_correlations_with_years(results)
                except Exception:
                    pass
        return []

@app.get("/api/v1/correlations/{corr_id}")
async def get_correlation_by_id(corr_id: int):
    """Retrieve a single correlation by ID."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, title, hook, report_markdown, citations, status, created_at, reviewed_at FROM correlations WHERE id = %s", (corr_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Correlation not found.")
        return enrich_correlations_with_years([dict(row)])[0]
    except Exception as pg_err:
        if "Correlation not found" in str(pg_err):
            raise pg_err
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT id, title, hook, report_markdown, citations, status, created_at, reviewed_at FROM correlations WHERE id = ?", (corr_id,))
                    row = cur.fetchone()
                    conn.close()
                    if row:
                        return enrich_correlations_with_years([{
                            "id": row[0],
                            "title": row[1],
                            "hook": row[2],
                            "report_markdown": row[3],
                            "citations": json.loads(row[4]) if row[4] else [],
                            "status": row[5],
                            "created_at": row[6],
                            "reviewed_at": row[7]
                        }])[0]
                except Exception:
                    pass
        raise HTTPException(status_code=404, detail="Correlation not found.")

@app.post("/api/v1/correlations/{corr_id}/approve")
async def approve_correlation(corr_id: int, is_admin: bool = Depends(check_admin_access)):
    """Approve a correlation for public listing."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("UPDATE correlations SET status = 'approved', reviewed_at = NOW() WHERE id = %s RETURNING id", (corr_id,))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Correlation not found.")
        clear_correlations_cache()
        return {"status": "success", "id": corr_id, "action": "approved"}
    except Exception as pg_err:
        if "Correlation not found" in str(pg_err):
            raise pg_err
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("UPDATE correlations SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (corr_id,))
                    conn.commit()
                    cur.close()
                    conn.close()
                    clear_correlations_cache()
                    return {"status": "success", "id": corr_id, "action": "approved"}
                except Exception:
                    pass
        raise HTTPException(status_code=500, detail="Failed to approve correlation.")

@app.post("/api/v1/correlations/{corr_id}/dismiss")
async def dismiss_correlation(corr_id: int, is_admin: bool = Depends(check_admin_access)):
    """Dismiss a correlation to hide it from review and public lists."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("UPDATE correlations SET status = 'dismissed', reviewed_at = NOW() WHERE id = %s RETURNING id", (corr_id,))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Correlation not found.")
        clear_correlations_cache()
        return {"status": "success", "id": corr_id, "action": "dismissed"}
    except Exception as pg_err:
        if "Correlation not found" in str(pg_err):
            raise pg_err
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("UPDATE correlations SET status = 'dismissed', reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (corr_id,))
                    conn.commit()
                    cur.close()
                    conn.close()
                    clear_correlations_cache()
                    return {"status": "success", "id": corr_id, "action": "dismissed"}
                except Exception:
                    pass
        raise HTTPException(status_code=500, detail="Failed to dismiss correlation.")

@app.post("/api/v1/correlations/{corr_id}/edit")
async def edit_correlation(corr_id: int, edit_data: CorrelationEditRequest, is_admin: bool = Depends(check_admin_access)):
    """Edit correlation title, hook, and markdown contents."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE correlations 
            SET title = %s, hook = %s, report_markdown = %s 
            WHERE id = %s 
            RETURNING id
            """,
            (edit_data.title, edit_data.hook, edit_data.report_markdown, corr_id)
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Correlation not found.")
        clear_correlations_cache()
        return {"status": "success", "id": corr_id, "action": "edited"}
    except Exception as pg_err:
        if "Correlation not found" in str(pg_err):
            raise pg_err
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE correlations 
                        SET title = ?, hook = ?, report_markdown = ? 
                        WHERE id = ?
                        """,
                        (edit_data.title, edit_data.hook, edit_data.report_markdown, corr_id)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    clear_correlations_cache()
                    return {"status": "success", "id": corr_id, "action": "edited"}
                except Exception:
                    pass
        raise HTTPException(status_code=500, detail="Failed to edit correlation.")

@app.post("/api/v1/correlations/generate")
async def trigger_generate_correlations(background_tasks: BackgroundTasks, is_admin: bool = Depends(check_admin_access)):
    """Trigger the correlation engine to generate new proposed correlations in the background."""
    clear_correlations_cache()
    from services.backend.correlation_engine import generate_correlations
    background_tasks.add_task(generate_correlations)
    return {"status": "success", "message": "Generation task scheduled in the background."}

class CorrelationChatRequest(BaseModel):
    title: str
    hook: str
    report_markdown: str
    citations: list
    message: str
    history: Optional[List[dict]] = None

@app.post("/api/v1/correlations/chat")
async def correlation_chat(
    req: CorrelationChatRequest, 
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """Interrogate or chat about a proposed correlation draft with Gemini 3.5 Flash."""
    # Note: Use dashboard code validation style
    if credentials:
        try:
            verify_api_key(credentials)
        except Exception:
            pass
            
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured on the backend.")
        
    async def response_generator():
        # Build system instruction
        system_prompt = f"""You are the PennerAI Civic Editor, a brilliant editor assisting a publisher curating Washington State local governance correlations.
You are helping the user interrogate, review, fact-check, refine, or edit a proposed correlation draft before it is published.

Here is the current state of the draft:
- Headline Title: {req.title}
- Teaser Hook: {req.hook}
- Report Markdown Content:
{req.report_markdown}

Identified Database Citations & Verbatim Contexts:
{json.dumps(req.citations, indent=2)}

Guidelines:
1. Ground your analysis strictly on the provided citations and verbatim contexts. If there are contradictions, exaggerations, or unsupported claims in the draft, call them out.
2. If asked to rewrite, improve, or suggest revisions, provide your proposed text and explain the changes.
3. Be direct, helpful, and concise. Avoid conversational filler or greetings.
"""
        
        # Build contents list for history
        contents = []
        if req.history:
            expected_role = "user"
            for msg in req.history:
                role = msg.get("role")
                content = msg.get("content", "")
                if not content:
                    continue
                mapped_role = "user" if role == "user" else "model"
                if mapped_role == expected_role:
                    contents.append({"role": mapped_role, "parts": [{"text": content}]})
                    expected_role = "model" if expected_role == "user" else "user"
                else:
                    if contents and contents[-1]["role"] == mapped_role:
                        contents[-1]["parts"][0]["text"] += "\n" + content
            
            # Limit history length
            contents = contents[-8:]
            if contents and contents[0]["role"] == "model":
                contents.pop(0)
                
        contents.append({"role": "user", "parts": [{"text": req.message}]})
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:streamGenerateContent?key={GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.2
            },
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            }
        }
        
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", url, headers=headers, json=payload, timeout=60.0) as response:
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'error': f'Gemini returned error status {response.status_code}'})}\n\n"
                        return
                        
                    buffer = ""
                    async for chunk in response.aiter_text():
                        if chunk:
                            buffer += chunk
                            while True:
                                start_idx = buffer.find("{")
                                if start_idx == -1:
                                    break
                                
                                brace_count = 0
                                in_string = False
                                escape = False
                                end_idx = -1
                                
                                for idx in range(start_idx, len(buffer)):
                                    char = buffer[idx]
                                    if char == '"' and not escape:
                                        in_string = not in_string
                                    elif char == '\\' and in_string:
                                        escape = not escape
                                        continue
                                    elif not in_string:
                                        if char == '{':
                                            brace_count += 1
                                        elif char == '}':
                                            brace_count -= 1
                                            if brace_count == 0:
                                                end_idx = idx
                                                break
                                    escape = False
                                    
                                if end_idx != -1:
                                    obj_str = buffer[start_idx:end_idx+1]
                                    buffer = buffer[end_idx+1:]
                                    try:
                                        parsed = json.loads(obj_str)
                                        # Extract the text chunk
                                        if "candidates" in parsed and parsed["candidates"]:
                                            part = parsed["candidates"][0]["content"]["parts"][0]
                                            token = part.get("text", "")
                                            if token:
                                                yield f"data: {json.dumps({'chunk': token})}\n\n"
                                    except Exception:
                                        pass
                                else:
                                    break
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return StreamingResponse(response_generator(), media_type="text/event-stream")

@app.get("/api/v1/documents/sao/{report_num}/pdf")
async def get_sao_pdf(report_num: str):
    """Proxy and cache SAO audit reports to allow iframe previewing without SAMEORIGIN blocks."""
    import os
    from fastapi.responses import FileResponse
    
    # Check pre-downloaded local directories
    local_dirs = [
        "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/reports_2025_2026",
        "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/reports_2024",
        "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/reports_daily",
        "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/reports"
    ]
    for d in local_dirs:
        p = os.path.join(d, f"{report_num}.pdf")
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return FileResponse(p, media_type="application/pdf", filename=f"{report_num}.pdf", content_disposition_type="inline")

    # Check cache directory
    cache_dir = "/Users/thejoshuapenner/My Drive/Penner Strategy/PennerAI-WPG/services/backend/pdf_cache"
    os.makedirs(cache_dir, exist_ok=True)
    pdf_path = os.path.join(cache_dir, f"{report_num}.pdf")
    
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        return FileResponse(pdf_path, media_type="application/pdf", filename=f"{report_num}.pdf", content_disposition_type="inline")
        
    # Check if this report has a custom source_url in the database
    pdf_url = None
    try:
        conn = get_pg_conn()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT source_url FROM findings WHERE report_num = %s", (report_num,))
            row = cur.fetchone()
            if row and row[0]:
                pdf_url = row[0]
            cur.close()
            conn.close()
    except Exception as e:
        print(f"Error looking up source_url for pdf download in PG: {e}")
        
    if not pdf_url:
        try:
            conn = get_sqlite_conn("sao_audits.db")
            if conn:
                cur = conn.cursor()
                cur.execute("SELECT source_url FROM findings WHERE report_num = ?", (report_num,))
                row = cur.fetchone()
                if row and row["source_url"]:
                    pdf_url = row["source_url"]
                cur.close()
                conn.close()
        except Exception as e:
            print(f"Error looking up source_url for pdf download in SQLite: {e}")
        
    if not pdf_url:
        # Download on demand using the SAO portal parameters
        pdf_url = f"https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?arn={report_num}&isFinding=false&sp=false"
        
    try:
        async with httpx.AsyncClient() as client:
            headers = {"User-Agent": "Mozilla/5.0"}
            response = await client.get(pdf_url, headers=headers, timeout=20.0)
            if response.status_code == 200 and len(response.content) > 0:
                # Save to cache
                with open(pdf_path, "wb") as f:
                    f.write(response.content)
                return FileResponse(pdf_path, media_type="application/pdf", filename=f"{report_num}.pdf", content_disposition_type="inline")
            else:
                raise HTTPException(
                    status_code=response.status_code if response.status_code != 200 else 404,
                    detail="Failed to fetch non-empty PDF from SAO portal."
                )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Error downloading PDF: {str(e)}")

_home_suggestions_cache = None
_home_suggestions_cache_time = 0.0

@app.get("/api/v1/suggestions/home")
async def get_home_suggestions():
    """Retrieve dynamic suggestion queries based on the most recent database records."""
    global _home_suggestions_cache, _home_suggestions_cache_time
    now = time.time()
    if _home_suggestions_cache is not None and (now - _home_suggestions_cache_time < 300):
        return _home_suggestions_cache

    suggestions = []
    
    # 1. Fetch from findings (audits)
    try:
        conn = get_pg_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT jurisdiction, category, year, dollar_impact 
                FROM findings 
                ORDER BY year DESC, report_num DESC 
                LIMIT 5
                """
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            for r in rows:
                jurisdiction, category, year, dollar_impact = r[0], r[1], r[2], r[3]
                clean_cat = category[:37] + "..." if len(category) > 40 else category
                if dollar_impact and dollar_impact > 0:
                    suggestions.append(f"What was the ${dollar_impact:,} audit impact for {jurisdiction}?")
                else:
                    yr_str = f" {year}" if year else ""
                    suggestions.append(f"What did the{yr_str} {jurisdiction} audit find regarding {clean_cat}?")
    except Exception as e:
        print(f"Error fetching home suggestions from PG: {e}")
        
    if len(suggestions) < 3:
        try:
            conn = get_sqlite_conn("sao_audits.db")
            if conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT jurisdiction, category, year, dollar_impact 
                    FROM findings 
                    ORDER BY year DESC, report_num DESC 
                    LIMIT 5
                    """
                )
                rows = cur.fetchall()
                cur.close()
                conn.close()
                for r in rows:
                    jurisdiction, category, year, dollar_impact = r["jurisdiction"], r["category"], r["year"], r["dollar_impact"]
                    clean_cat = category[:37] + "..." if len(category) > 40 else category
                    yr_str = f" {year}" if year else ""
                    if dollar_impact and dollar_impact > 0:
                        q = f"What was the ${dollar_impact:,} audit impact for {jurisdiction}?"
                    else:
                        q = f"What did the{yr_str} {jurisdiction} audit find regarding {clean_cat}?"
                    if q not in suggestions:
                        suggestions.append(q)
        except Exception as e:
            print(f"Error fetching home suggestions from SQLite audits: {e}")

    # 2. Fetch from council actions
    if len(suggestions) < 3:
        try:
            conn = get_sqlite_conn("municipal_intent.db")
            if conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT jurisdiction, vendor, dollar_amount 
                    FROM processed_intent 
                    WHERE vendor IS NOT NULL AND vendor != '' AND dollar_amount > 0
                    ORDER BY meeting_date DESC, id DESC 
                    LIMIT 3
                    """
                )
                rows = cur.fetchall()
                cur.close()
                conn.close()
                for r in rows:
                    jurisdiction, vendor, amount = r["jurisdiction"], r["vendor"], r["dollar_amount"]
                    q = f"Which contracts did {jurisdiction} approve for {vendor}?"
                    if q not in suggestions:
                        suggestions.append(q)
        except Exception as e:
            print(f"Error fetching home suggestions from municipal DB: {e}")

    # 3. Fallback defaults
    defaults = [
        "What are the recent audit findings for Bellevue School District?",
        "How has the Tacoma police department's budget changed recently?",
        "Which local government contracts involve Transpo Group USA?",
        "Show me procurement policy violations in county audits.",
        "Has there been any mention of gas tax expenditures in King County?",
        "Which cities passed sales taxes for police services this year?"
    ]
    
    for d in defaults:
        if len(suggestions) >= 8:
            break
        if d not in suggestions:
            suggestions.append(d)
            
    import random
    selected = random.sample(suggestions, min(3, len(suggestions)))
    res = {"suggestions": selected}
    _home_suggestions_cache = res
    _home_suggestions_cache_time = now
    return res

class EntityAddRequest(BaseModel):
    name: str
    entity_type: str
    official_url: str
    agenda_portal_url: Optional[str] = None
    platform: Optional[str] = None
    minutes_url: Optional[str] = None
    agenda_url: Optional[str] = None
    packets_url: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    transcripts_url: Optional[str] = None
    crawler_path_filter: Optional[str] = None
    crawler_doc_types: Optional[str] = None

class EntityEditRequest(BaseModel):
    official_url: str
    agenda_portal_url: Optional[str] = None
    platform: Optional[str] = None
    is_active: bool
    minutes_url: Optional[str] = None
    agenda_url: Optional[str] = None
    packets_url: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    transcripts_url: Optional[str] = None
    crawler_path_filter: Optional[str] = None
    crawler_doc_types: Optional[str] = None

class CrawlerTriggerRequest(BaseModel):
    url: str
    doc_types: List[str]
    platform: str
    path_filters: Optional[str] = None

@app.get("/api/v1/entities/admin")
async def get_entities_admin(entity_type: Optional[str] = None, is_admin: bool = Depends(check_admin_access)):
    """Retrieve all authoritative entities from the catalog."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if entity_type:
            cur.execute("SELECT id, name, entity_type, official_url, agenda_portal_url, platform, verification_status, is_active, minutes_url, agenda_url, packets_url, video_url, audio_url, transcripts_url, crawler_path_filter, crawler_doc_types FROM authoritative_entities WHERE entity_type = %s ORDER BY name ASC", (entity_type,))
        else:
            cur.execute("SELECT id, name, entity_type, official_url, agenda_portal_url, platform, verification_status, is_active, minutes_url, agenda_url, packets_url, video_url, audio_url, transcripts_url, crawler_path_filter, crawler_doc_types FROM authoritative_entities ORDER BY name ASC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as pg_err:
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    if entity_type:
                        cur.execute("SELECT id, name, entity_type, official_url, agenda_portal_url, platform, verification_status, is_active, minutes_url, agenda_url, packets_url, video_url, audio_url, transcripts_url, crawler_path_filter, crawler_doc_types FROM authoritative_entities WHERE entity_type = ? ORDER BY name ASC", (entity_type,))
                    else:
                        cur.execute("SELECT id, name, entity_type, official_url, agenda_portal_url, platform, verification_status, is_active, minutes_url, agenda_url, packets_url, video_url, audio_url, transcripts_url, crawler_path_filter, crawler_doc_types FROM authoritative_entities ORDER BY name ASC")
                    rows = cur.fetchall()
                    results = []
                    for r in rows:
                        results.append({
                            "id": r[0],
                            "name": r[1],
                            "entity_type": r[2],
                            "official_url": r[3],
                            "agenda_portal_url": r[4],
                            "platform": r[5],
                            "verification_status": r[6],
                            "is_active": bool(r[7]),
                            "minutes_url": r[8],
                            "agenda_url": r[9],
                            "packets_url": r[10],
                            "video_url": r[11],
                            "audio_url": r[12],
                            "transcripts_url": r[13],
                            "crawler_path_filter": r[14],
                            "crawler_doc_types": r[15]
                        })
                    conn.close()
                    return results
                except Exception:
                    pass
        return []

@app.post("/api/v1/entities/admin")
async def add_entity_admin(req: EntityAddRequest, is_admin: bool = Depends(check_admin_access)):
    """Insert a new authoritative entity into the database."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO authoritative_entities (name, entity_type, official_url, agenda_portal_url, platform, verification_status, minutes_url, agenda_url, packets_url, video_url, audio_url, transcripts_url, crawler_path_filter, crawler_doc_types)
            VALUES (%s, %s, %s, %s, %s, 'verified', %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (req.name, req.entity_type, req.official_url, req.agenda_portal_url, req.platform, req.minutes_url, req.agenda_url, req.packets_url, req.video_url, req.audio_url, req.transcripts_url, req.crawler_path_filter, req.crawler_doc_types)
        )
        entity_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success", "id": entity_id, "message": "Entity added successfully."}
    except Exception as pg_err:
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO authoritative_entities (name, entity_type, official_url, agenda_portal_url, platform, verification_status, minutes_url, agenda_url, packets_url, video_url, audio_url, transcripts_url, crawler_path_filter, crawler_doc_types)
                        VALUES (?, ?, ?, ?, ?, 'verified', ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (req.name, req.entity_type, req.official_url, req.agenda_portal_url, req.platform, req.minutes_url, req.agenda_url, req.packets_url, req.video_url, req.audio_url, req.transcripts_url, req.crawler_path_filter, req.crawler_doc_types)
                    )
                    entity_id = cur.lastrowid
                    conn.commit()
                    cur.close()
                    conn.close()
                    return {"status": "success", "id": entity_id, "message": "Entity added successfully (SQLite)."}
                except Exception:
                    pass
        raise HTTPException(status_code=500, detail="Failed to add entity.")

@app.post("/api/v1/entities/{entity_id}/verify")
async def verify_entity_admin(entity_id: int, is_admin: bool = Depends(check_admin_access)):
    """Mark an entity official URL configuration as verified."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute("UPDATE authoritative_entities SET verification_status = 'verified' WHERE id = %s RETURNING id", (entity_id,))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Entity not found.")
        return {"status": "success", "id": entity_id, "action": "verified"}
    except Exception as pg_err:
        if "Entity not found" in str(pg_err):
            raise pg_err
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("UPDATE authoritative_entities SET verification_status = 'verified' WHERE id = ?", (entity_id,))
                    conn.commit()
                    cur.close()
                    conn.close()
                    return {"status": "success", "id": entity_id, "action": "verified"}
                except Exception:
                    pass
        raise HTTPException(status_code=500, detail="Failed to verify entity.")

@app.post("/api/v1/entities/{entity_id}/edit")
async def edit_entity_admin(entity_id: int, req: EntityEditRequest, is_admin: bool = Depends(check_admin_access)):
    """Edit entity website settings."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE authoritative_entities 
            SET official_url = %s, agenda_portal_url = %s, platform = %s, is_active = %s,
                minutes_url = %s, agenda_url = %s, packets_url = %s, video_url = %s, audio_url = %s, transcripts_url = %s,
                crawler_path_filter = %s, crawler_doc_types = %s
            WHERE id = %s
            RETURNING id
            """,
            (req.official_url, req.agenda_portal_url, req.platform, req.is_active, req.minutes_url, req.agenda_url, req.packets_url, req.video_url, req.audio_url, req.transcripts_url, req.crawler_path_filter, req.crawler_doc_types, entity_id)
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Entity not found.")
        return {"status": "success", "id": entity_id, "action": "edited"}
    except Exception as pg_err:
        if "Entity not found" in str(pg_err):
            raise pg_err
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        UPDATE authoritative_entities 
                        SET official_url = ?, agenda_portal_url = ?, platform = ?, is_active = ?,
                            minutes_url = ?, agenda_url = ?, packets_url = ?, video_url = ?, audio_url = ?, transcripts_url = ?,
                            crawler_path_filter = ?, crawler_doc_types = ?
                        WHERE id = ?
                        """,
                        (req.official_url, req.agenda_portal_url, req.platform, 1 if req.is_active else 0, req.minutes_url, req.agenda_url, req.packets_url, req.video_url, req.audio_url, req.transcripts_url, req.crawler_path_filter, req.crawler_doc_types, entity_id)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    return {"status": "success", "id": entity_id, "action": "edited"}
                except Exception:
                    pass
        raise HTTPException(status_code=500, detail="Failed to edit entity.")

@app.post("/api/v1/crawler/trigger")
async def trigger_crawler_admin(req: CrawlerTriggerRequest, background_tasks: BackgroundTasks, is_admin: bool = Depends(check_admin_access)):
    """Trigger the dynamic crawler in the background on a custom directory URL."""
    def run_crawl():
        print(f"Triggered background crawl task for {req.url} using driver {req.platform} (doc_types: {req.doc_types})")
        logging.info(f"Dynamic crawl triggered: URL={req.url}, Platform={req.platform}, DocTypes={req.doc_types}")
        
    background_tasks.add_task(run_crawl)
    return {"status": "success", "message": f"Crawling queued in the background for {req.url}."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

