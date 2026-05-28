import os
import sys
import json
import psycopg2
import sqlite3
from psycopg2.extras import RealDictCursor
import litellm
from dotenv import load_dotenv

# Add parent of services folder to sys.path to support standalone execution
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.membrane import MembraneClient

load_dotenv()

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:penner_secret_password_2026@localhost:5432/penner_governance_db"
)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

from typing import Optional

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

from psycopg2.pool import ThreadedConnectionPool
import time

_pg_pool = None
_postgres_available = True
_last_postgres_check_time = 0.0
_postgres_check_cooldown = 30.0

def get_pool():
    global _pg_pool, _postgres_available, _last_postgres_check_time
    now = time.time()
    if _pg_pool is None:
        if not _postgres_available and (now - _last_postgres_check_time < _postgres_check_cooldown):
            return None
        try:
            _pg_pool = ThreadedConnectionPool(1, 20, dsn=POSTGRES_URL, connect_timeout=2)
            _postgres_available = True
            _last_postgres_check_time = now
        except Exception as e:
            _postgres_available = False
            _last_postgres_check_time = now
            print(f"Failed to initialize correlation Postgres pool: {e}")
            _pg_pool = None
    return _pg_pool

class PooledConnectionWrapper:
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        
    def __getattr__(self, name):
        return getattr(self._conn, name)
        
    def close(self):
        if self._conn and self._pool:
            try:
                self._pool.putconn(self._conn)
            except Exception as e:
                print(f"Error returning correlation connection to pool: {e}")
            finally:
                self._conn = None
                self._pool = None
                
    def __del__(self):
        self.close()

def get_pg_conn():
    global _postgres_available, _last_postgres_check_time
    pool = get_pool()
    if not pool:
        raise psycopg2.OperationalError(
            "Postgres is down. Circuit breaker active."
        )
    try:
        conn = pool.getconn()
        return PooledConnectionWrapper(pool, conn)
    except Exception as e:
        _postgres_available = False
        _last_postgres_check_time = time.time()
        raise e

def get_sqlite_conn(db_name: str):
    sqlite_dir = os.environ.get("SQLITE_DIR", "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper")
    db_path = os.path.join(sqlite_dir, db_name)
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn
    # Try local root folder as fallback
    fallback_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", db_name))
    if os.path.exists(fallback_path):
        conn = sqlite3.connect(fallback_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        return conn
    return None

def make_diverse(records: list, limit: int = 25, max_per_jurisdiction: int = 2, jurisdiction_key: str = "jurisdiction") -> list:
    """Takes a list of records and returns a diverse subset containing at most
    max_per_jurisdiction records from any single jurisdiction, up to the limit."""
    diverse_records = []
    j_counts = {}
    for r in records:
        jur = r.get(jurisdiction_key)
        if not jur:
            continue
        jur_clean = str(jur).lower().strip()
        if j_counts.get(jur_clean, 0) < max_per_jurisdiction:
            diverse_records.append(r)
            j_counts[jur_clean] = j_counts.get(jur_clean, 0) + 1
        if len(diverse_records) >= limit:
            break
    return diverse_records

def get_already_cited_records() -> dict:
    """Returns a dict mapping source types to sets of cited IDs, e.g.
    {'audit': {'1039555', ...}, 'bill': {'SSB 5412', ...}}
    """
    cited = {}
    
    # Try PostgreSQL first
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        # Verify correlations table exists in Postgres
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'correlations'
            )
        """)
        table_exists = cur.fetchone()[0]
        if table_exists:
            cur.execute("SELECT citations FROM correlations")
            rows = cur.fetchall()
            for r in rows:
                citations_raw = r[0]
                if not citations_raw:
                    continue
                if isinstance(citations_raw, str):
                    try:
                        citations = json.loads(citations_raw)
                    except Exception:
                        citations = []
                else:
                    citations = citations_raw
                for cit in citations:
                    src = cit.get("source")
                    cid = str(cit.get("id") or "")
                    if src and cid:
                        cited.setdefault(src, set()).add(cid)
        cur.close()
        conn.close()
        return cited
    except Exception as e:
        print("PG fetch citations failed, falling back to SQLite:", e)
        
    # SQLite fallback
    for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
        conn = get_sqlite_conn(db_name)
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='correlations'")
                if cur.fetchone():
                    cur.execute("SELECT citations FROM correlations")
                    rows = cur.fetchall()
                    for r in rows:
                        citations_raw = r[0]
                        if not citations_raw:
                            continue
                        try:
                            citations = json.loads(citations_raw)
                        except Exception:
                            citations = []
                        for cit in citations:
                            src = cit.get("source")
                            cid = str(cit.get("id") or "")
                            if src and cid:
                                cited.setdefault(src, set()).add(cid)
                cur.close()
                conn.close()
            except Exception as sq_err:
                print(f"SQLite fetch citations failed for {db_name}:", sq_err)
                
    return cited

def fetch_recent_data():
    """Fetch diverse findings, council actions, budgets, grants, and school financials from PostgreSQL or SQLite."""
    findings_pool = []
    actions_pool = []
    budgets_pool = []
    grants_pool = []
    school_financials_pool = []
    contributions_pool = []
    bills_pool = []
    
    # Try PostgreSQL first
    try:
        conn = get_pg_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cur.execute(
                """
                SELECT report_num, jurisdiction, category, summary, dollar_impact, year 
                FROM findings 
                ORDER BY report_num DESC 
                LIMIT 100
                """
            )
            findings_pool = [dict(r) for r in cur.fetchall()]
        except Exception:
            # Fallback if 'year' column does not exist yet in PostgreSQL findings table
            conn.rollback()
            cur.execute(
                """
                SELECT report_num, jurisdiction, category, summary, dollar_impact 
                FROM findings 
                ORDER BY report_num DESC 
                LIMIT 100
                """
            )
            for r in cur.fetchall():
                d = dict(r)
                d["year"] = 2025  # safe default
                findings_pool.append(d)
        
        try:
            cur.execute(
                """
                SELECT event_id, jurisdiction, committee, meeting_date, key_action, dollar_amount 
                FROM merged_actions 
                WHERE meeting_date != 'Extracted_Date'
                  AND lower(key_action) NOT LIKE '%call to order%'
                  AND lower(key_action) NOT LIKE '%roll call%'
                  AND lower(key_action) NOT LIKE '%approval of minutes%'
                  AND lower(key_action) NOT LIKE '%public comment%'
                  AND lower(key_action) NOT LIKE '%adjourn%'
                ORDER BY meeting_date DESC 
                LIMIT 150
                """
            )
            actions_pool = []
            for r in cur.fetchall():
                row_dict = dict(r)
                row_dict["key_action"] = clean_summary_text(row_dict.get("key_action"))
                actions_pool.append(row_dict)
        except Exception:
            conn.rollback()

        # Fetch budgets
        try:
            cur.execute(
                """
                SELECT b.id, b.source_url, b.jurisdiction_name, b.entity_type, b.fiscal_year, b.total_revenue, b.total_expenditures, b.fund_balance_beginning, b.fund_balance_ending,
                       bi.major_category, bi.amount as item_amount
                FROM budgets b
                LEFT JOIN budget_items bi ON b.id = bi.budget_id
                ORDER BY b.fiscal_year DESC, b.id DESC
                LIMIT 100
                """
            )
            budgets_pool = [dict(r) for r in cur.fetchall()]
        except Exception:
            conn.rollback()

        # Fetch grants
        try:
            cur.execute(
                """
                SELECT id, source_url, grant_title, awarding_agency, recipient_jurisdiction, award_amount, award_date, purpose_category, funding_source
                FROM grants
                ORDER BY award_date DESC NULLS LAST, id DESC
                LIMIT 100
                """
            )
            grants_pool = [dict(r) for r in cur.fetchall()]
        except Exception:
            conn.rollback()

        # Fetch school district financials
        try:
            cur.execute(
                """
                SELECT id, source_url, district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount
                FROM school_district_financials
                ORDER BY fiscal_year DESC, id DESC
                LIMIT 100
                """
            )
            school_financials_pool = [dict(r) for r in cur.fetchall()]
        except Exception:
            conn.rollback()

        # Fetch political contributions
        try:
            cur.execute(
                """
                SELECT id, source_url, candidate_name, contributor_name, contributor_employer, amount, receipt_date, jurisdiction
                FROM political_contributions
                WHERE amount >= 1000
                ORDER BY receipt_date DESC NULLS LAST, id DESC
                LIMIT 150
                """
            )
            contributions_pool = [dict(r) for r in cur.fetchall()]
        except Exception:
            conn.rollback()

        # Fetch legislative bills
        try:
            cur.execute(
                """
                SELECT bill_number, title, biennium, sponsor, passed_date, summary, policy_category
                FROM legislative_bills
                ORDER BY passed_date DESC NULLS LAST, bill_number DESC
                LIMIT 100
                """
            )
            bills_pool = [dict(r) for r in cur.fetchall()]
        except Exception:
            conn.rollback()
        
        cur.close()
        conn.close()
    except Exception as e:
        print("PG fetch failed for engine, checking SQLite:", e)
        # SQLite fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        SELECT report_num, jurisdiction, category, summary, dollar_impact, year 
                        FROM findings 
                        ORDER BY report_num DESC 
                        LIMIT 100
                        """
                    )
                    rows = [dict(row) for row in cur.fetchall()]
                    for r in rows:
                        findings_pool.append({
                            "report_num": r["report_num"],
                            "jurisdiction": r["jurisdiction"],
                            "category": r["category"],
                            "summary": r["summary"],
                            "dollar_impact": r["dollar_impact"],
                            "year": r.get("year") or (2024 if db_name == "sao_2024.db" else 2025)
                        })
                    conn.close()
                except Exception as sq_err:
                    print(f"SQLite fetch failed for {db_name}:", sq_err)
                    
        conn = get_sqlite_conn("municipal_intent.db")
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT event_id, jurisdiction, doc_type as committee, meeting_date, agenda_item_title, key_action, dollar_amount 
                    FROM processed_intent 
                    WHERE meeting_date != 'Extracted_Date'
                      AND (agenda_item_title IS NULL OR (
                          lower(agenda_item_title) NOT LIKE '%call to order%'
                          AND lower(agenda_item_title) NOT LIKE '%roll call%'
                          AND lower(agenda_item_title) NOT LIKE '%approval of minutes%'
                          AND lower(agenda_item_title) NOT LIKE '%public comment%'
                          AND lower(agenda_item_title) NOT LIKE '%excuse%'
                          AND lower(agenda_item_title) NOT LIKE '%adjourn%'
                      ))
                    ORDER BY meeting_date DESC 
                    LIMIT 150
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]
                for r in rows:
                    actions_pool.append({
                        "event_id": r["event_id"],
                        "jurisdiction": r["jurisdiction"],
                        "committee": r["committee"],
                        "meeting_date": str(r["meeting_date"]),
                        "key_action": clean_summary_text(r.get('agenda_item_title'), r.get('key_action')),
                        "dollar_amount": r["dollar_amount"]
                    })
                
                # SQLite Budgets
                try:
                    cur.execute(
                        """
                        SELECT b.id, b.source_url, b.jurisdiction_name, b.entity_type, b.fiscal_year, b.total_revenue, b.total_expenditures, b.fund_balance_beginning, b.fund_balance_ending,
                               bi.major_category, bi.amount as item_amount
                        FROM budgets b
                        LEFT JOIN budget_items bi ON b.id = bi.budget_id
                        ORDER BY b.fiscal_year DESC
                        LIMIT 100
                        """
                    )
                    budgets_pool = [dict(r) for r in cur.fetchall()]
                except Exception:
                    pass

                # SQLite Grants
                try:
                    cur.execute(
                        """
                        SELECT id, source_url, grant_title, awarding_agency, recipient_jurisdiction, award_amount, award_date, purpose_category, funding_source
                        FROM grants
                        ORDER BY award_date DESC
                        LIMIT 100
                        """
                    )
                    grants_pool = [dict(r) for r in cur.fetchall()]
                except Exception:
                    pass

                # SQLite School district financials
                try:
                    cur.execute(
                        """
                        SELECT id, source_url, district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount
                        FROM school_district_financials
                        ORDER BY fiscal_year DESC
                        LIMIT 100
                        """
                    )
                    school_financials_pool = [dict(r) for r in cur.fetchall()]
                except Exception:
                    pass

                # SQLite Campaign Contributions
                try:
                    cur.execute(
                        """
                        SELECT id, source_url, candidate_name, contributor_name, contributor_employer, amount, receipt_date, jurisdiction
                        FROM political_contributions
                        WHERE amount >= 1000
                        ORDER BY receipt_date DESC, id DESC
                        LIMIT 150
                        """
                    )
                    contributions_pool = [dict(r) for r in cur.fetchall()]
                except Exception:
                    pass

                # SQLite Legislative Bills
                try:
                    cur.execute(
                        """
                        SELECT bill_number, title, biennium, sponsor, passed_date, summary, policy_category
                        FROM legislative_bills
                        ORDER BY passed_date DESC, bill_number DESC
                        LIMIT 100
                        """
                    )
                    bills_pool = [dict(r) for r in cur.fetchall()]
                except Exception:
                    pass
                
                conn.close()
            except Exception:
                pass

    # Load all cited records to filter them out of candidates
    try:
        cited = get_already_cited_records()
    except Exception as ec:
        print("Failed to get already cited records, using empty set:", ec)
        cited = {}

    # Filter out already-cited records from pools
    findings_pool = [f for f in findings_pool if str(f.get("report_num")) not in cited.get("audit", set())]
    actions_pool = [a for a in actions_pool if str(a.get("event_id")) not in cited.get("council", set())]
    budgets_pool = [b for b in budgets_pool if str(b.get("id")) not in cited.get("budget", set())]
    grants_pool = [g for g in grants_pool if str(g.get("id")) not in cited.get("grant", set())]
    school_financials_pool = [s for s in school_financials_pool if str(s.get("id")) not in cited.get("school", set())]
    contributions_pool = [c for c in contributions_pool if str(c.get("id")) not in cited.get("contribution", set())]
    bills_pool = [b for b in bills_pool if str(b.get("bill_number")) not in cited.get("bill", set())]

    # De-duplicate findings by report_num
    unique_findings = []
    seen_findings = set()
    for f in findings_pool:
        if f["report_num"] not in seen_findings:
            seen_findings.add(f["report_num"])
            unique_findings.append(f)

    # Perform diversity filtering to ensure broad jurisdiction coverage (data discovery)
    findings = make_diverse(unique_findings, limit=30, max_per_jurisdiction=2, jurisdiction_key="jurisdiction")
    actions = make_diverse(actions_pool, limit=30, max_per_jurisdiction=2, jurisdiction_key="jurisdiction")
    budgets = make_diverse(budgets_pool, limit=20, max_per_jurisdiction=2, jurisdiction_key="jurisdiction_name")
    grants = make_diverse(grants_pool, limit=20, max_per_jurisdiction=2, jurisdiction_key="recipient_jurisdiction")
    school_financials = make_diverse(school_financials_pool, limit=20, max_per_jurisdiction=2, jurisdiction_key="district_name")
    contributions = make_diverse(contributions_pool, limit=25, max_per_jurisdiction=3, jurisdiction_key="jurisdiction")
    bills = make_diverse(bills_pool, limit=25, max_per_jurisdiction=3, jurisdiction_key="policy_category")
                
    return findings, actions, budgets, grants, school_financials, contributions, bills

def save_correlation(correlation: dict) -> int:
    """Save a correlation draft to PostgreSQL or SQLite."""
    title = correlation.get("title", "Untitled Correlation")
    hook = correlation.get("hook", "")
    report_markdown = correlation.get("report_markdown", "")
    citations = json.dumps(correlation.get("citations", []))
    status = "proposed"
    
    # Try PostgreSQL
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO correlations (title, hook, report_markdown, citations, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (title, hook, report_markdown, citations, status)
        )
        row_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return row_id
    except Exception as e:
        print("PG save correlation failed, saving to SQLite fallback:", e)
        # SQLite Fallback
        for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        INSERT INTO correlations (title, hook, report_markdown, citations, status)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (title, hook, report_markdown, citations, status)
                    )
                    conn.commit()
                    row_id = cur.lastrowid
                    cur.close()
                    conn.close()
                    return row_id
                except Exception as sq_e:
                    print(f"SQLite save correlation failed for {db_name}:", sq_e)
    return -1

def get_fallback_correlations():
    """Returns realistic mock correlations for Washington state governance."""
    return [
        {
            "title": "Small Towns Update Systems to Meet Police Training Record Standards (2025)",
            "hook": "Several small cities in Washington are updating their record systems to keep up with state guidelines for tracking officer training and background checks.",
            "report_markdown": """### Paper Records vs. State Requirements
During recent 2025 checks, the Washington State Auditor's Office noted that some small police departments, including Orting and Enumclaw, had incomplete paperwork. The issues were mainly related to tracking training hours and background checks. This happened after new state laws in 2023 increased the details cities must record for police certifications. These findings were detailed in the [Orting Police Department Internal Controls Audit (2025)](https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber=1034562) and the [Enumclaw Police Department Compliance Audit (2025)](https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber=1034981).

### Upgrading the Systems
These small towns did not fail records checks on purpose. Instead, their office staff was overwhelmed by the new paperwork requirements. Traditionally, these smaller cities kept record files on paper, which makes it harder to organize and check during reviews. Proponents of digital transitions argue that centralized systems prevent certification lapses.

### Moving Forward
To solve this problem, towns are starting to use modern tracking software. By moving to digital records and training their office staff, these cities are making sure they meet state rules. For instance, the Orting City Council approved a new record tracking contract as noted in the [Orting City Council Meeting Minutes (May 2025)](https://www.google.com/search?q=Orting+city+council+meeting+police+record+tracking). While some local officials raise concerns over the upfront costs of software licenses for small budgets, the digital transition is expected to help local departments run more efficiently and avoid potential legal issues.
""",
            "citations": [
                {
                    "id": "1034562",
                    "source": "audit",
                    "title": "Orting Police Department - Internal Controls Audit 2025",
                    "url": "https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber=1034562"
                },
                {
                    "id": "1034981",
                    "source": "audit",
                    "title": "Enumclaw Police Department - Compliance Audit 2025",
                    "url": "https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber=1034981"
                },
                {
                    "id": "evt_orting_102",
                    "source": "council",
                    "title": "Orting City Council Meeting - Police Record Tracking Contract (May 2025)",
                    "url": "https://www.google.com/search?q=Orting+city+council+meeting+police+record+tracking"
                }
            ]
        },
        {
            "title": "State Grants Help Local Schools and Cities Fund Clean Energy Projects (2025)",
            "hook": "School districts and cities across Western Washington are winning state grants to upgrade buildings with solar panels and energy-saving systems.",
            "report_markdown": """### Funding Green Upgrades
Local governments and school districts are successfully teaming up with state agencies to fund clean energy upgrades. In 2025, school districts like Bellevue and Snohomish received grants to install solar panels, replace old heating units, and make classroom lighting more efficient. These initiatives were supported by the [Bellevue School District Energy Upgrade Grant (2025)](https://mrsc.org/explore-topics/government-organization) and the [Snohomish School District Clean Energy Project (2025)](https://mrsc.org/explore-topics/government-organization).

### Saving Local Tax Dollars
These clean energy projects are funded by state grants rather than local property taxes. By utilizing these grants, schools and cities can lower their electricity bills. The money saved on utilities can then be kept in classrooms or general city services. However, critics point out that state-funded grants still represent taxpayer spending at the state level and require significant administrative oversight to track compliance.

### Successful Partnerships
School boards and city councils have approved contracts to begin these projects. For example, the school board approved a solar installation project during the [Bellevue School Board Meeting (2025)](https://www.google.com/search?q=Bellevue+school+board+emergency+fleet). This shows how state-level grants can help local schools and cities modernize their buildings, save money, and lower their carbon footprint, though local implementation requires careful planning to ensure the long-term maintenance of the newly installed clean energy systems is sustainable.
""",
            "citations": [
                {
                    "id": "1035122",
                    "source": "grant",
                    "title": "Bellevue School District - Energy Upgrade Grant 2025",
                    "url": "https://mrsc.org/explore-topics/government-organization"
                },
                {
                    "id": "1035340",
                    "source": "school",
                    "title": "Snohomish School District - Clean Energy Project 2025",
                    "url": "https://mrsc.org/explore-topics/government-organization"
                },
                {
                    "id": "evt_bell_403",
                    "source": "council",
                    "title": "Bellevue School Board - Solar Installation Contract 2025",
                    "url": "https://www.google.com/search?q=Bellevue+school+board+emergency+fleet"
                }
            ]
        }
    ]

def get_verbatim_context_for_citation(cit: dict) -> str:
    import re
    source = cit.get("source")
    cit_id = str(cit.get("id") or "").strip()
    
    # Strip common prefixes from IDs to prevent mismatches
    if cit_id.lower().startswith("audit "):
        cit_id = cit_id[6:].strip()
    elif cit_id.lower().startswith("budget "):
        cit_id = cit_id[7:].strip()
    elif cit_id.lower().startswith("school "):
        cit_id = cit_id[7:].strip()
    elif cit_id.lower().startswith("grant "):
        cit_id = cit_id[6:].strip()
    elif cit_id.lower().startswith("contribution "):
        cit_id = cit_id[13:].strip()
    elif cit_id.lower().startswith("bill "):
        cit_id = cit_id[5:].strip()
    elif cit_id.lower().startswith("event "):
        cit_id = cit_id[6:].strip()
    
    if source == "audit":
        for db_name in ["sao_audits.db", "sao_2024.db"]:
            conn = get_sqlite_conn(db_name)
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT jurisdiction, summary, verbatim_text_context, dollar_impact, year FROM findings WHERE report_num = ?", (cit_id,))
                    row = cur.fetchone()
                    cur.close()
                    conn.close()
                    if row:
                        row_dict = dict(zip(["jurisdiction", "summary", "verbatim_text_context", "dollar_impact", "year"], row))
                        summary_text = row_dict.get("verbatim_text_context") or row_dict.get("summary") or ""
                        jurisdiction = row_dict.get("jurisdiction")
                        year = row_dict.get("year")
                        verbatim = f"Jurisdiction: {jurisdiction} (Year: {year}). {summary_text}"
                        dollar = row_dict.get("dollar_impact")
                        if dollar and dollar > 0:
                            verbatim += f" (Dollar Impact: ${dollar:,})"
                        return verbatim
                except Exception:
                    pass
                    
    elif source == "council":
        conn = get_sqlite_conn("municipal_intent.db")
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT verbatim_text_context, jurisdiction, meeting_date FROM processed_intent WHERE event_id = ? OR id = ?", (cit_id, cit_id))
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row:
                    return f"Jurisdiction: {row[1]} Meeting Date: {row[2]}. Verbatim Action: {row[0]}"
            except Exception:
                pass
                
    elif source == "budget":
        conn = get_sqlite_conn("municipal_intent.db")
        if conn:
            try:
                cur = conn.cursor()
                if cit_id.isdigit():
                    # Try budget item ID first
                    cur.execute(
                        """
                        SELECT b.jurisdiction_name, b.fiscal_year, b.total_revenue, b.total_expenditures,
                               bi.major_category, bi.amount, bi.description
                        FROM budget_items bi
                        JOIN budgets b ON bi.budget_id = b.id
                        WHERE bi.id = ?
                        """,
                        (int(cit_id),)
                    )
                    row = cur.fetchone()
                    if row:
                        val = f"Budget for {row[0]} ({row[1]}) - {row[4]}: {row[6] or 'Allocation'}. Item Amount: ${row[5]:,}. (Total Revenue: ${row[2]:,}, Total Expenditures: ${row[3]:,})"
                        cur.close()
                        conn.close()
                        return val
                    
                    # Fallback to entire budget ID
                    cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures FROM budgets WHERE id = ?", (int(cit_id),))
                    row = cur.fetchone()
                    if row:
                        val = f"Budget Record for {row[0]} ({row[1]}): Total Revenue: ${row[2]:,}, Total Expenditures: ${row[3]:,}."
                        cur.close()
                        conn.close()
                        return val
                else:
                    clean_search = re.sub(r'[^a-zA-Z\s]', '', cit_id).split()
                    search_val = f"%{clean_search[0]}%" if clean_search else f"%{cit_id}%"
                    cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures FROM budgets WHERE jurisdiction_name LIKE ? OR ? LIKE '%' || jurisdiction_name || '%'", (search_val, cit_id))
                    row = cur.fetchone()
                    if row:
                        val = f"Budget Record for {row[0]} ({row[1]}): Total Revenue: ${row[2]:,}, Total Expenditures: ${row[3]:,}."
                        cur.close()
                        conn.close()
                        return val
                cur.close()
                conn.close()
            except Exception:
                pass
                
    elif source == "grant":
        conn = get_sqlite_conn("municipal_intent.db")
        if conn:
            try:
                cur = conn.cursor()
                if cit_id.isdigit() or (cit_id.startswith("Grant ") and cit_id[6:].isdigit()):
                    clean_id = int(cit_id[6:]) if cit_id.startswith("Grant ") else int(cit_id)
                    cur.execute("SELECT grant_title, recipient_jurisdiction, award_amount, awarding_agency, award_date FROM grants WHERE id = ?", (clean_id,))
                else:
                    cur.execute("SELECT grant_title, recipient_jurisdiction, award_amount, awarding_agency, award_date FROM grants WHERE grant_title = ? OR recipient_jurisdiction = ?", (cit_id, cit_id))
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row:
                    date_str = f" on {row[4]}" if row[4] else ""
                    if row[4]:
                        try:
                            parts = str(row[4]).split("-")
                            if len(parts) == 3:
                                months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
                                m = int(parts[1])
                                if 1 <= m <= 12:
                                    date_str += f" ({months[m-1]} {parts[0]})"
                        except Exception:
                            pass
                    return f"Grant Award: '{row[0]}' awarded to {row[1]} by {row[3]}{date_str}. Award Amount: ${row[2]:,}."
            except Exception:
                pass
                
    elif source == "school":
        conn = get_sqlite_conn("municipal_intent.db")
        if conn:
            try:
                cur = conn.cursor()
                if cit_id.isdigit():
                    cur.execute("SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount FROM school_district_financials WHERE id = ?", (int(cit_id),))
                else:
                    clean_search = re.sub(r'[^a-zA-Z\s]', '', cit_id).split()
                    search_val = f"%{clean_search[0]}%" if clean_search else f"%{cit_id}%"
                    cur.execute("SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount FROM school_district_financials WHERE district_name LIKE ? OR ? LIKE '%' || district_name || '%'", (search_val, cit_id))
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row:
                    levy_val = f", Levy Amount: ${row[5]:,}" if row[5] is not None else ""
                    sped_val = f", Special Ed: ${row[6]:,}" if row[6] is not None else ""
                    fed_val = f", Federal Funding: ${row[7]:,}" if row[7] is not None else ""
                    return f"School District Financials: {row[0]} ({row[1]}). Enrollment: {row[2]:.0f} FTE. Revenue: ${row[3]:,}, Expenditures: ${row[4]:,}{levy_val}{sped_val}{fed_val}."
            except Exception:
                pass
                
    elif source == "contribution":
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
                    return f"Campaign Contribution: {row[1]} donated ${row[2]:,} to {row[0]} ({row[4] or 'Unknown jurisdiction'}) on {row[3]}."
            except Exception:
                pass
                
    elif source == "bill":
        conn = get_sqlite_conn("municipal_intent.db")
        if conn:
            try:
                cur = conn.cursor()
                if cit_id.startswith("Bill "):
                    cit_id = cit_id[5:]
                cur.execute("SELECT title, summary, biennium, sponsor FROM legislative_bills WHERE bill_number = ? OR title = ?", (cit_id, cit_id))
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row:
                    return f"Legislative Bill {cit_id} ({row[2]}): {row[0]}. Sponsored by {row[3]}. Summary: {row[1]}"
            except Exception:
                pass
                
    return f"Details for {source} citation with ID {cit_id}."

def fetch_pivots(conn, limit=5):
    """
    Fetches recent records from findings, merged_actions, grants to use as seed pivots.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    pivots = []
    
    internal_limit = 30
    
    # 1. Recent findings
    try:
        cur.execute(
            """
            SELECT 'audit' as pivot_type, report_num as id, jurisdiction, summary as text, embedding, year
            FROM findings
            WHERE embedding IS NOT NULL
            ORDER BY report_num DESC
            LIMIT %s
            """,
            (internal_limit,)
        )
        pivots.extend([dict(r) for r in cur.fetchall()])
    except Exception as e:
        print("Error fetching audit pivots:", e)
        conn.rollback()
        
    # 2. Recent merged_actions
    try:
        cur.execute(
            """
            SELECT 'council' as pivot_type, event_id as id, jurisdiction, key_action as text, embedding, meeting_date
            FROM merged_actions
            WHERE embedding IS NOT NULL AND meeting_date != 'Extracted_Date'
              AND lower(key_action) NOT LIKE '%call to order%'
              AND lower(key_action) NOT LIKE '%roll call%'
              AND lower(key_action) NOT LIKE '%approval of minutes%'
              AND lower(key_action) NOT LIKE '%public comment%'
              AND lower(key_action) NOT LIKE '%adjourn%'
            ORDER BY meeting_date DESC, event_id DESC
            LIMIT %s
            """,
            (internal_limit,)
        )
        pivots.extend([dict(r) for r in cur.fetchall()])
    except Exception as e:
        print("Error fetching council pivots:", e)
        conn.rollback()

    # 3. Recent grants
    try:
        cur.execute(
            """
            SELECT 'grant' as pivot_type, id, recipient_jurisdiction as jurisdiction, grant_title as text, embedding, award_date
            FROM grants
            WHERE embedding IS NOT NULL
            ORDER BY award_date DESC NULLS LAST, id DESC
            LIMIT %s
            """,
            (internal_limit,)
        )
        pivots.extend([dict(r) for r in cur.fetchall()])
    except Exception as e:
        print("Error fetching grant pivots:", e)
        conn.rollback()

    import random
    random.shuffle(pivots)
    return pivots[:limit]

def fetch_semantic_candidates_for_pivot(embedding, jurisdiction_name, conn, limit=3, threshold=0.28):
    """
    Given a pivot's embedding and jurisdiction, queries all other tables for
    semantically similar records.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    matches = {}
    
    # Clean jurisdiction name for ILIKE searches (e.g. "Seattle" instead of "City of Seattle")
    jur_clean = jurisdiction_name.upper().replace("CITY OF", "").replace("COUNTY", "").strip()
    jur_pattern = f"%{jur_clean}%" if jur_clean else "%"
    
    # 1. findings
    try:
        cur.execute(
            """
            SELECT report_num, jurisdiction, category, summary, dollar_impact, year,
                   (embedding <=> %s::vector) as distance
            FROM findings
            WHERE jurisdiction ILIKE %s AND (embedding <=> %s::vector) < %s
            ORDER BY distance ASC
            LIMIT %s
            """,
            (embedding, jur_pattern, embedding, threshold, limit)
        )
        matches["audit"] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print("Error fetching semantic audits:", e)
        conn.rollback()

    # 2. merged_actions (council)
    try:
        cur.execute(
            """
            SELECT event_id, jurisdiction, committee, meeting_date, key_action, dollar_amount,
                   (embedding <=> %s::vector) as distance
            FROM merged_actions
            WHERE jurisdiction ILIKE %s AND (embedding <=> %s::vector) < %s
              AND meeting_date != 'Extracted_Date'
              AND lower(key_action) NOT LIKE '%call to order%'
              AND lower(key_action) NOT LIKE '%roll call%'
              AND lower(key_action) NOT LIKE '%approval of minutes%'
              AND lower(key_action) NOT LIKE '%public comment%'
              AND lower(key_action) NOT LIKE '%adjourn%'
            ORDER BY distance ASC
            LIMIT %s
            """,
            (embedding, jur_pattern, embedding, threshold, limit)
        )
        matches["council"] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print("Error fetching semantic council actions:", e)
        conn.rollback()

    # 3. budgets / budget_items
    try:
        cur.execute(
            """
            SELECT bi.id, b.jurisdiction_name, b.entity_type, b.fiscal_year, b.total_revenue, b.total_expenditures,
                   bi.major_category, bi.amount as item_amount, bi.description,
                   (bi.embedding <=> %s::vector) as distance
            FROM budget_items bi
            JOIN budgets b ON bi.budget_id = b.id
            WHERE b.jurisdiction_name ILIKE %s AND (bi.embedding <=> %s::vector) < %s
            ORDER BY distance ASC
            LIMIT %s
            """,
            (embedding, jur_pattern, embedding, threshold, limit)
        )
        matches["budget"] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print("Error fetching semantic budget items:", e)
        conn.rollback()

    # 4. grants
    try:
        cur.execute(
            """
            SELECT id, source_url, grant_title, awarding_agency, recipient_jurisdiction, award_amount, award_date, purpose_category, funding_source,
                   (embedding <=> %s::vector) as distance
            FROM grants
            WHERE recipient_jurisdiction ILIKE %s AND (embedding <=> %s::vector) < %s
            ORDER BY distance ASC
            LIMIT %s
            """,
            (embedding, jur_pattern, embedding, threshold, limit)
        )
        matches["grant"] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print("Error fetching semantic grants:", e)
        conn.rollback()

    # 5. school_district_financials (school)
    try:
        cur.execute(
            """
            SELECT id, source_url, district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount,
                   (embedding <=> %s::vector) as distance
            FROM school_district_financials
            WHERE district_name ILIKE %s AND (embedding <=> %s::vector) < %s
            ORDER BY distance ASC
            LIMIT %s
            """,
            (embedding, jur_pattern, embedding, threshold, limit)
        )
        matches["school"] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print("Error fetching semantic school financials:", e)
        conn.rollback()

    return matches

def fetch_contributions_for_jurisdiction(jurisdiction_name, conn, limit=5):
    """
    Fetch significant campaign contributions for a given jurisdiction.
    """
    cur = conn.cursor(cursor_factory=RealDictCursor)
    jur_clean = jurisdiction_name.upper().replace("CITY OF", "").replace("COUNTY", "").strip()
    jur_pattern = f"%{jur_clean}%" if jur_clean else "%"
    try:
        cur.execute(
            """
            SELECT id, candidate_name, contributor_name, contributor_employer, amount, receipt_date, jurisdiction, source_url
            FROM political_contributions
            WHERE (jurisdiction ILIKE %s OR candidate_name ILIKE %s)
              AND amount >= 1000
            ORDER BY receipt_date DESC NULLS LAST, id DESC
            LIMIT %s
            """,
            (jur_pattern, jur_pattern, limit)
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print("Error fetching contributions for jurisdiction:", e)
        conn.rollback()
    return []

def fetch_relevant_bills(pivot_text, conn, limit=3):
    """
    Find legislative bills that match terms in the pivot text.
    """
    import re
    cur = conn.cursor(cursor_factory=RealDictCursor)
    keywords = [w for w in re.sub(r'[^a-zA-Z\s]', '', pivot_text).split() if len(w) > 4][:5]
    if not keywords:
        keywords = ["Administration"]
        
    like_clauses = " OR ".join(["title ILIKE %s" for _ in keywords])
    params = [f"%{w}%" for w in keywords]
    
    try:
        cur.execute(
            f"""
            SELECT bill_number, title, biennium, sponsor, passed_date, summary, policy_category
            FROM legislative_bills
            WHERE {like_clauses}
            ORDER BY passed_date DESC NULLS LAST, bill_number DESC
            LIMIT %s
            """,
            (*params, limit)
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print("Error fetching relevant bills:", e)
        conn.rollback()
    return []

def get_keywords(text: str):
    import re
    if not text:
        return []
    words = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower()).split()
    stop_words = {
        "the", "and", "a", "for", "to", "of", "with", "that", "this", "on", "in", "at", "by", 
        "from", "an", "is", "was", "were", "are", "be", "been", "have", "has", "had", "do", 
        "does", "did", "but", "or", "as", "if", "then", "else", "when", "where", "why", "how", 
        "not", "no", "yes", "our", "their", "your", "its", "about", "which", "who", "whom", 
        "orting", "enumclaw", "tacoma", "seattle", "spokane", "olympia", "washington", "state",
        "county", "city", "district", "meeting", "minutes", "council", "board", "committee",
        "action", "passed", "failed", "agenda", "item", "report", "finding"
    }
    keywords = [w for w in words if w not in stop_words and len(w) > 4]
    return sorted(list(set(keywords)), key=len, reverse=True)[:5]

def search_audits_sqlite(jur_pattern, keywords, limit=3):
    results = []
    for db_name in ["sao_audits.db", "sao_2024.db"]:
        conn = get_sqlite_conn(db_name)
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT report_num, jurisdiction, category, summary, dollar_impact, year, verbatim_text_context, source_url
                    FROM findings
                    WHERE jurisdiction LIKE ?
                    """,
                    (jur_pattern,)
                )
                rows = [dict(r) for r in cur.fetchall()]
                results.extend(rows)
                conn.close()
            except Exception as e:
                print(f"Error searching audits in SQLite {db_name}: {e}")
    
    scored = []
    for r in results:
        score = 0
        summary = ((r.get("summary") or "") + " " + (r.get("category") or "")).lower()
        for kw in keywords:
            if kw in summary:
                score += 1
        scored.append((score, r))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]

def search_council_sqlite(jur_pattern, keywords, limit=3):
    conn = get_sqlite_conn("municipal_intent.db")
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT event_id, jurisdiction, doc_type as committee, meeting_date, key_action, agenda_item_title, dollar_amount, verbatim_text_context
            FROM processed_intent
            WHERE jurisdiction LIKE ?
              AND meeting_date != 'Extracted_Date'
              AND key_action IS NOT NULL
              AND (agenda_item_title IS NULL OR (
                  lower(agenda_item_title) NOT LIKE '%call to order%'
                  AND lower(agenda_item_title) NOT LIKE '%roll call%'
                  AND lower(agenda_item_title) NOT LIKE '%approval of minutes%'
                  AND lower(agenda_item_title) NOT LIKE '%public comment%'
                  AND lower(agenda_item_title) NOT LIKE '%excuse%'
                  AND lower(agenda_item_title) NOT LIKE '%adjourn%'
              ))
            """,
            (jur_pattern,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        
        scored = []
        for r in rows:
            score = 0
            text = ((r.get("key_action") or "") + " " + (r.get("agenda_item_title") or "")).lower()
            for kw in keywords:
                if kw in text:
                    score += 1
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        
        final_rows = []
        for item in scored[:limit]:
            r = item[1]
            r["key_action"] = clean_summary_text(r.get("agenda_item_title"), r.get("key_action"))
            final_rows.append(r)
        return final_rows
    except Exception as e:
        print(f"Error searching council in SQLite: {e}")
        return []

def search_budgets_sqlite(jur_pattern, keywords, limit=3):
    conn = get_sqlite_conn("municipal_intent.db")
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT bi.id, b.jurisdiction_name, b.entity_type, b.fiscal_year, b.total_revenue, b.total_expenditures,
                   bi.major_category, bi.amount as item_amount, bi.description
            FROM budget_items bi
            JOIN budgets b ON bi.budget_id = b.id
            WHERE b.jurisdiction_name LIKE ?
            """,
            (jur_pattern,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        
        scored = []
        for r in rows:
            score = 0
            desc = ((r.get("description") or "") + " " + (r.get("major_category") or "")).lower()
            for kw in keywords:
                if kw in desc:
                    score += 1
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]
    except Exception as e:
        print(f"Error searching budgets in SQLite: {e}")
        return []

def search_grants_sqlite(jur_pattern, keywords, limit=3):
    conn = get_sqlite_conn("municipal_intent.db")
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, source_url, grant_title, awarding_agency, recipient_jurisdiction, award_amount, award_date, purpose_category, funding_source
            FROM grants
            WHERE recipient_jurisdiction LIKE ?
            """,
            (jur_pattern,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        
        scored = []
        for r in rows:
            score = 0
            title = (r.get("grant_title") or "").lower()
            for kw in keywords:
                if kw in title:
                    score += 1
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]
    except Exception as e:
        print(f"Error searching grants in SQLite: {e}")
        return []

def search_schools_sqlite(jur_clean, keywords, limit=3):
    conn = get_sqlite_conn("municipal_intent.db")
    if not conn:
        return []
    try:
        cur = conn.cursor()
        pattern = f"%{jur_clean}%"
        cur.execute(
            """
            SELECT id, source_url, district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount
            FROM school_district_financials
            WHERE district_name LIKE ?
            """,
            (pattern,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        
        scored = []
        for r in rows:
            score = 0
            name = (r.get("district_name") or "").lower()
            for kw in keywords:
                if kw in name:
                    score += 1
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]
    except Exception as e:
        print(f"Error searching school financials in SQLite: {e}")
        return []

def fetch_pivots_sqlite(limit=5):
    """
    Fetches recent records from findings, processed_intent, grants in SQLite to use as seed pivots,
    filtering out already cited ones.
    """
    try:
        cited = get_already_cited_records()
    except Exception:
        cited = {}
        
    audit_pivots = []
    council_pivots = []
    grant_pivots = []
    
    # 1. Recent findings from sao_audits.db and sao_2024.db
    for db_name in ["sao_audits.db", "sao_2024.db"]:
        conn = get_sqlite_conn(db_name)
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT 'audit' as pivot_type, report_num as id, jurisdiction, summary as text, year
                    FROM findings
                    ORDER BY year DESC, report_num DESC
                    LIMIT 100
                    """
                )
                rows = [dict(r) for r in cur.fetchall()]
                for r in rows:
                    if str(r["id"]) not in cited.get("audit", set()):
                        audit_pivots.append(r)
                conn.close()
            except Exception as e:
                print(f"Error fetching audit pivots from SQLite {db_name}: {e}")

    # Deduplicate audit pivots by ID
    unique_audit = []
    seen_audit = set()
    for ap in audit_pivots:
        if ap["id"] not in seen_audit:
            seen_audit.add(ap["id"])
            unique_audit.append(ap)
    audit_pivots = unique_audit[:30]

    # 2. Recent council actions from municipal_intent.db (processed_intent)
    conn = get_sqlite_conn("municipal_intent.db")
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT 'council' as pivot_type, event_id as id, jurisdiction, key_action as text, meeting_date
                FROM processed_intent
                WHERE meeting_date != 'Extracted_Date'
                  AND key_action IS NOT NULL
                  AND (agenda_item_title IS NULL OR (
                      lower(agenda_item_title) NOT LIKE '%call to order%'
                      AND lower(agenda_item_title) NOT LIKE '%roll call%'
                      AND lower(agenda_item_title) NOT LIKE '%approval of minutes%'
                      AND lower(agenda_item_title) NOT LIKE '%public comment%'
                      AND lower(agenda_item_title) NOT LIKE '%excuse%'
                      AND lower(agenda_item_title) NOT LIKE '%adjourn%'
                  ))
                ORDER BY meeting_date DESC
                LIMIT 200
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if str(r["id"]) not in cited.get("council", set()):
                    council_pivots.append(r)
            
            # Deduplicate council pivots by ID (since multiple rows share event_id)
            unique_council = []
            seen_council = set()
            for cp in council_pivots:
                if cp["id"] not in seen_council:
                    seen_council.add(cp["id"])
                    unique_council.append(cp)
            council_pivots = unique_council[:30]

            # 3. Recent grants from municipal_intent.db (grants)
            cur.execute(
                """
                SELECT 'grant' as pivot_type, id, recipient_jurisdiction as jurisdiction, grant_title as text, award_date
                FROM grants
                ORDER BY award_date DESC
                LIMIT 100
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if str(r["id"]) not in cited.get("grant", set()):
                    grant_pivots.append(r)
            grant_pivots = grant_pivots[:30]
            
            conn.close()
        except Exception as e:
            print("Error fetching council/grant pivots from SQLite municipal_intent.db:", e)
            
    # Combine and return a diverse slice of pivots
    pivots = []
    pivots.extend(audit_pivots)
    pivots.extend(council_pivots)
    pivots.extend(grant_pivots)
    import random
    random.shuffle(pivots)
    return pivots[:limit]

def fetch_candidates_for_pivot_sqlite(pivot, limit=3):
    """
    Given a pivot's text and jurisdiction, queries SQLite tables for
    semantically/geographically matching records using keyword overlap.
    """
    jurisdiction_name = pivot.get("jurisdiction") or ""
    pivot_text = pivot.get("text") or ""
    
    jur_clean = jurisdiction_name.upper().replace("CITY OF", "").replace("COUNTY", "").strip()
    jur_pattern = f"%{jur_clean}%" if jur_clean else "%"
    
    keywords = get_keywords(pivot_text)
    print(f"    SQLite candidate search keywords: {keywords}")
    
    matches = {
        "audit": search_audits_sqlite(jur_pattern, keywords, limit),
        "council": search_council_sqlite(jur_pattern, keywords, limit),
        "budget": search_budgets_sqlite(jur_pattern, keywords, limit),
        "grant": search_grants_sqlite(jur_pattern, keywords, limit),
        "school": search_schools_sqlite(jur_clean, keywords, limit)
    }
    return matches

def fetch_contributions_for_jurisdiction_sqlite(jurisdiction_name, limit=5):
    conn = get_sqlite_conn("municipal_intent.db")
    if not conn:
        return []
    jur_clean = jurisdiction_name.upper().replace("CITY OF", "").replace("COUNTY", "").strip()
    jur_pattern = f"%{jur_clean}%" if jur_clean else "%"
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, candidate_name, contributor_name, contributor_employer, amount, receipt_date, jurisdiction
            FROM political_contributions
            WHERE (jurisdiction LIKE ? OR candidate_name LIKE ?)
              AND amount >= 1000
            ORDER BY receipt_date DESC, id DESC
            LIMIT ?
            """,
            (jur_pattern, jur_pattern, limit)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print("Error fetching contributions for jurisdiction in SQLite:", e)
        return []

def fetch_relevant_bills_sqlite(pivot_text, limit=3):
    import re
    conn = get_sqlite_conn("municipal_intent.db")
    if not conn:
        return []
    keywords = [w for w in re.sub(r'[^a-zA-Z\s]', '', pivot_text).split() if len(w) > 4][:5]
    if not keywords:
        keywords = ["Administration"]
        
    like_clauses = " OR ".join(["title LIKE ?" for _ in keywords])
    params = [f"%{w}%" for w in keywords]
    
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT bill_number, title, biennium, sponsor, passed_date, summary, policy_category
            FROM legislative_bills
            WHERE {like_clauses}
            ORDER BY passed_date DESC, bill_number DESC
            LIMIT ?
            """,
            (*params, limit)
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print("Error fetching relevant bills in SQLite:", e)
        return []

def generate_correlations():
    """Generates 2-3 correlation reports using semantic vector-matching and a skeptical critic evaluator loop."""
    print("🤖 Starting Upgraded Intelligent Semantic Correlation Generation...")
    
    if not GEMINI_API_KEY:
        print("  GEMINI_API_KEY missing. Seeding fallback mock correlations.")
        fallbacks = get_fallback_correlations()
        ids = [save_correlation(f) for f in fallbacks]
        return {"status": "success", "source": "mock_fallbacks", "generated_ids": ids}

    # Try to connect to PostgreSQL
    try:
        conn = get_pg_conn()
        use_postgres = True
        print("  Connected to PostgreSQL database.")
    except Exception as e:
        print("  Postgres connection failed for upgraded engine. Falling back to live SQLite database:", e)
        use_postgres = False
        conn = None

    # 1. Fetch seed pivots
    if use_postgres:
        pivots = fetch_pivots(conn, limit=5)
        print(f"  Retrieved {len(pivots)} seed pivots from PostgreSQL.")
    else:
        pivots = fetch_pivots_sqlite(limit=5)
        print(f"  Retrieved {len(pivots)} seed pivots from SQLite.")
    
    if not pivots:
        print("  No pivots found.")
        if conn:
            conn.close()
        return {"status": "success", "source": "no_pivots", "generated_ids": []}

    membrane = MembraneClient()
    validated_correlations = []
    generated_count = 0
    target_count = 2 # Generate 2 high-quality correlations

    # Load already-cited records to avoid duplicate correlations
    try:
        cited = get_already_cited_records()
    except Exception:
        cited = {}

    for pivot in pivots:
        if generated_count >= target_count:
            break
            
        pivot_type = pivot["pivot_type"]
        pivot_id = str(pivot["id"])
        
        # Skip if pivot was already cited
        if pivot_id in cited.get(pivot_type, set()):
            continue
            
        print(f"\n  === Processing Pivot: {pivot_type} ID: {pivot_id} ({pivot['jurisdiction']}) ===")
        
        # 2. Query other tables for semantic matches
        if use_postgres:
            matches = fetch_semantic_candidates_for_pivot(pivot["embedding"], pivot["jurisdiction"], conn)
        else:
            matches = fetch_candidates_for_pivot_sqlite(pivot, limit=3)
        
        # Format candidate matches
        findings_text = ""
        actions_text = ""
        budgets_text = ""
        grants_text = ""
        schools_text = ""
        
        audit_matches = [f for f in matches.get("audit", []) if str(f["report_num"]) != pivot_id]
        for f in audit_matches:
            findings_text += f"- [Audit {f['report_num']}] Jurisdiction: {f['jurisdiction']} | Year: {f['year']} | Category: {f['category']} | Summary: {f['summary']} | Impact: ${f['dollar_impact']:,} | URL: https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber={f['report_num']}\n"
            
        council_matches = [a for a in matches.get("council", []) if str(a["event_id"]) != pivot_id]
        for a in council_matches:
            actions_text += f"- [Event {a['event_id']}] Jurisdiction: {a['jurisdiction']} | Committee: {a['committee']} | Description: {a['key_action']} | Amount: ${a['dollar_amount']:,} | URL: {a.get('source_url') or 'https://municipal-intent-search'}\n"
            
        for b in matches.get("budget", []):
            budgets_text += f"- [Budget {b['id']}] Jurisdiction: {b['jurisdiction_name']} | Year: {b['fiscal_year']} | Revenue: ${b['total_revenue']:,} | Expenditures: ${b['total_expenditures']:,} | {b['major_category']}: ${b['item_amount']:,} | URL: {b.get('source_url') or 'https://portal.sao.wa.gov/ReportSearch'}\n"
            
        grant_matches = [g for g in matches.get("grant", []) if str(g["id"]) != pivot_id]
        for g in grant_matches:
            grants_text += f"- [Grant {g['id']}] Recipient: {g['recipient_jurisdiction']} | Title: {g['grant_title']} | Amount: ${g['award_amount']:,} | Date: {g['award_date']} | Agency: {g['awarding_agency']} | Purpose: {g['purpose_category']} | URL: {g.get('source_url') or 'https://www.usaspending.gov'}\n"
            
        for s in matches.get("school", []):
            schools_text += f"- [School {s['id']}] District: {s['district_name']} | Year: {s['fiscal_year']} | Enrollment: {s['enrollment']:.0f} FTE | Rev: ${s['total_revenue']:,} | Exp: ${s['total_expenditures']:,} | Levy: ${s['levy_amount']:,} | SpEd Exp: ${s['special_education_spending']:,} | URL: {s.get('source_url') or 'https://data.wa.gov'}\n"

        # Check total number of semantic matches
        total_semantic_matches = len(audit_matches) + len(council_matches) + len(matches.get("budget", [])) + len(grant_matches) + len(matches.get("school", []))
        if total_semantic_matches == 0:
            print("    No semantic matches found for this pivot. Skipping.")
            continue

        # 3. Fetch contributions and legislative bills
        if use_postgres:
            contributions = fetch_contributions_for_jurisdiction(pivot["jurisdiction"], conn)
            bills = fetch_relevant_bills(pivot["text"], conn)
        else:
            contributions = fetch_contributions_for_jurisdiction_sqlite(pivot["jurisdiction"])
            bills = fetch_relevant_bills_sqlite(pivot["text"])

        contributions_text = ""
        for c in contributions:
            contributions_text += f"- [Contribution {c['id']}] Candidate: {c['candidate_name']} | Contributor: {c['contributor_name']} ({c['contributor_employer'] or 'No Employer info'}) | Amount: ${c['amount']:,} | Date: {c['receipt_date']} | Jurisdiction: {c['jurisdiction'] or 'Statewide/Unknown'} | URL: {c.get('source_url') or 'https://www.pdc.wa.gov'}\n"
            
        bills_text = ""
        for b in bills:
            passed_str = f" | Passed: {b['passed_date']}" if b.get("passed_date") else ""
            summary_str = f" | Summary: {b['summary']}" if b.get("summary") else ""
            bills_text += f"- [Bill {b['bill_number']}] Title: {b['title']} | Biennium: {b['biennium']} | Sponsor: {b['sponsor'] or 'Unknown'} | Category: {b['policy_category'] or 'General'}{passed_str}{summary_str} | URL: https://app.leg.wa.gov/billsummary?BillNumber={b['bill_number']}\n"

        # Format target pivot info
        pivot_text = f"--- TARGET PIVOT RECORD ({pivot_type.upper()}) ---\n"
        if pivot_type == "audit":
            pivot_text += f"- [Audit {pivot_id}] Jurisdiction: {pivot['jurisdiction']} | Year: {pivot.get('year', '2025')} | Summary: {pivot['text']}\n"
        elif pivot_type == "council":
            pivot_text += f"- [Event {pivot_id}] Jurisdiction: {pivot['jurisdiction']} | Action: {pivot['text']}\n"
        elif pivot_type == "grant":
            pivot_text += f"- [Grant {pivot_id}] Recipient: {pivot['jurisdiction']} | Title: {pivot['text']}\n"

        # 4. Draft correlation report (Writer Agent)
        writer_system_prompt = """You are an expert investigative civic analyst specializing in tracking public finance, political accountability, and downstream policy outcomes in Washington State.
Your objective is to conduct deep, rigorous civic investigations and highlight analytical correlations.
Specifically, prioritize tracing sequences of influence, policy, and subsequent results: e.g. Influence (campaign contributions) -> Law/Policy (council action/legislative bill) -> Downstream Outcome (audit finding/expenditures).

CRITICAL REQUIREMENT: 
You MUST ONLY reference and cite the specific records provided in the inputs below. 
Do NOT invent, assume, or hallucinate any other audits, council meetings, grants, budgets, campaign contributions, or legislative bills. 
If a section of inputs is empty or says "None", you must NOT refer to or cite any records of that type. 
Every citation ID in your output's "citations" list MUST exactly match one of the IDs provided in the brackets (e.g. `1034964`, `evt_orting_102`, etc.) in the inputs. 
Never make up your own citation IDs.

Every key fact, budget figure, or audit finding MUST be directly cited inline using standard markdown links with a descriptive anchor text (e.g. `[Aberdeen Audit (2024)](url)`).
All URLs MUST exactly match the URLs provided in the database inputs.

Format your output strictly as a JSON object matching this schema:
{
  "title": "Analytical connection title",
  "hook": "Teaser string",
  "report_markdown": "Full analysis report in Markdown format",
  "citations": [
    {
      "id": "The cited ID",
      "source": "audit" | "council" | "budget" | "grant" | "school" | "contribution" | "bill",
      "title": "Citation title including the year",
      "url": "Provide the exact matching URL from the inputs"
    }
  ]
}
Ensure all double quotes inside JSON string values are escaped as \\\"."""

        writer_prompt = f"""Draft a correlation report connecting the following target pivot record with the related semantic and geographical context:

{pivot_text}

--- RELATED SEMANTIC AUDIT FINDINGS ---
{findings_text or "None"}

--- RELATED SEMANTIC COUNCIL ACTIONS ---
{actions_text or "None"}

--- RELATED SEMANTIC BUDGETS ---
{budgets_text or "None"}

--- RELATED SEMANTIC GRANTS ---
{grants_text or "None"}

--- RELATED SEMANTIC SCHOOL DISTRICT FINANCIALS ---
{schools_text or "None"}

--- GEOGRAPHIC CAMPAIGN CONTRIBUTIONS ---
{contributions_text or "None"}

--- RELEVANT LEGISLATIVE BILLS ---
{bills_text or "None"}
"""
        print("    Drafting correlation...")
        try:
            response = membrane.chat_completion(
                model="membrane-engagement-layer",
                messages=[
                    {"role": "system", "content": writer_system_prompt},
                    {"role": "user", "content": writer_prompt}
                ],
                temperature=0.0
            )
            if isinstance(response, dict):
                content = response["choices"][0]["message"]["content"].strip()
            else:
                content = response.choices[0].message.content.strip()
                
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()
                
            current_corr = json.loads(content)
            # Auto-normalize domain typos in report_markdown and citations
            if "report_markdown" in current_corr and isinstance(current_corr["report_markdown"], str):
                current_corr["report_markdown"] = current_corr["report_markdown"].replace("sao.wa.wa.gov", "sao.wa.gov")
            if "citations" in current_corr and isinstance(current_corr["citations"], list):
                for cit in current_corr["citations"]:
                    if "url" in cit and isinstance(cit["url"], str):
                        cit["url"] = cit["url"].replace("sao.wa.wa.gov", "sao.wa.gov")
        except Exception as e:
            print("    Error drafting correlation:", e)
            continue

        # 5. Skeptical Critic & Relevance Evaluator Loop
        critic_system_prompt = """You are a highly skeptical senior investigative editor reviewing civic governance correlations for PennerAI.
Your role is to act as a healthy skeptic, evaluating if the proposed correlation is genuinely meaningful, logically sound, and non-trivial, or if it is just a forced, coincidental alignment.

Evaluate the draft on the following:
1. RELEVANCE & CIVIC INTEREST (Score 1.0 to 10.0): Is the connection interesting, non-obvious, and highly relevant? (e.g. connecting campaign donations to vendor contract wins, or a specific policy change to a subsequent audit finding). If it just states the obvious or links trivial things (e.g., "Seattle Police spent money on policing and had a standard police audit"), score it < 7.0 and REJECT it.
2. SPURIOUS LINKS: Did the writer invent or imply a false causal connection between unrelated programs just because they are in the same city? (e.g. claiming a housing grant caused an audit issue in the fire department). If so, score it < 7.0 and REJECT.
3. CHRONOLOGICAL SANITY: Does the timeline make sense? (A cause must precede an effect chronologically).

Return your response strictly as a JSON object:
{
  "status": "APPROVED" | "REJECTED" | "REQUIRES_REWRITE",
  "score": 1.0 to 10.0,
  "criticism": "Detailed explanation of your reasoning. Highlight any forced causality or triviality."
}
Ensure all double quotes inside JSON string values are escaped as \\\"."""

        print(f"    Skeptical Critic evaluating correlation: '{current_corr.get('title')}'...")
        try:
            critic_response = membrane.chat_completion(
                model="membrane-engagement-layer",
                messages=[
                    {"role": "system", "content": critic_system_prompt},
                    {"role": "user", "content": json.dumps(current_corr)}
                ],
                temperature=0.0
            )
            if isinstance(critic_response, dict):
                critic_content = critic_response["choices"][0]["message"]["content"].strip()
            else:
                critic_content = critic_response.choices[0].message.content.strip()
                
            if critic_content.startswith("```"):
                lines = critic_content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                critic_content = "\n".join(lines).strip()
                
            critic_data = json.loads(critic_content)
            print(f"      Critic Score: {critic_data.get('score')} | Status: {critic_data.get('status')}")
            
            if critic_data.get("status") == "REJECTED" or float(critic_data.get("score", 0)) < 7.0:
                print(f"      ❌ Rejected by Critic: {critic_data.get('criticism')}")
                continue
            elif critic_data.get("status") == "REQUIRES_REWRITE":
                print(f"      ⚠️ Rewrite required: {critic_data.get('criticism')}. Requesting correction...")
                # Request rewrite from Writer with critic's feedback
                rewrite_prompt = f"""You are the correlation generator. The proposed correlation requires a rewrite based on the senior editor's critique.
                
Proposed Correlation:
{json.dumps(current_corr, indent=2)}

Editor Critique:
{critic_data.get('criticism')}

Rewrite the correlation to resolve the issues. Return the rewritten correlation strictly as a JSON object with keys 'title', 'hook', 'report_markdown', 'citations'."""
                rewrite_response = membrane.chat_completion(
                    model="membrane-engagement-layer",
                    messages=[
                        {"role": "system", "content": writer_system_prompt},
                        {"role": "user", "content": rewrite_prompt}
                    ],
                    temperature=0.0
                )
                if isinstance(rewrite_response, dict):
                    rewrite_content = rewrite_response["choices"][0]["message"]["content"].strip()
                else:
                    rewrite_content = rewrite_response.choices[0].message.content.strip()
                if rewrite_content.startswith("```"):
                    lines = rewrite_content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines[-1].startswith("```"):
                        lines = lines[:-1]
                    rewrite_content = "\n".join(lines).strip()
                current_corr = json.loads(rewrite_content)
        except Exception as e:
            print("    Error during critic evaluation/rewrite:", e)
            continue

        # 6. Fact-Checking and Verification Loop
        attempts = 0
        max_attempts = 2
        fact_check_passed = False
        
        while attempts < max_attempts:
            citations_with_context = []
            for cit in current_corr.get("citations", []):
                verbatim = get_verbatim_context_for_citation(cit)
                citations_with_context.append({
                    "id": cit.get("id"),
                    "source": cit.get("source"),
                    "title": cit.get("title"),
                    "url": cit.get("url"),
                    "verbatim_text_context": verbatim
                })
            
            from datetime import datetime
            current_date_str = datetime.now().strftime("%B %d, %Y")
            fact_check_prompt = f"""You are a strict, objective fact checker. Review the following correlation report draft against the verbatim contexts of its citations.
            
Proposed Correlation:
Headline Title: {current_corr.get('title')}
Teaser Hook: {current_corr.get('hook')}
Report Markdown Content:
{current_corr.get('report_markdown')}

Citations & Verbatim Contexts:
{json.dumps(citations_with_context, indent=2)}

Guidelines:
1. Ensure every metric, date, dollar amount, and factual claim is 100% supported by the verbatim contexts.
2. Ensure there are no temporal contradictions. Note that today's date is {current_date_str}. Therefore, audits, council meetings, or grants from 2024, 2025, or 2026 (up to {current_date_str}) are in the PAST/PRESENT, not the future. Do NOT flag them as temporal contradictions or future events.
3. Ensure there are no fabricated details.
4. Ensure all URLs in markdown links exactly match the citation URLs.
5. If there are ANY discrepancies, output a list of issues.
6. If the report is 100% factually accurate, chronologically correct, and URLs match perfectly, output ONLY the word 'PASS'.
"""
            print(f"    Fact-checking (Attempt {attempts + 1})...")
            try:
                check_response = membrane.chat_completion(
                    model="membrane-engagement-layer",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": fact_check_prompt}
                    ],
                    temperature=0.0
                )
                if isinstance(check_response, dict):
                    check_text = check_response["choices"][0]["message"]["content"].strip()
                else:
                    check_text = check_response.choices[0].message.content.strip()
                
                if check_text == "PASS" or "PASS" in check_text.splitlines():
                    print("    ✅ Correlation passed fact-check!")
                    fact_check_passed = True
                    validated_correlations.append(current_corr)
                    break
                else:
                    print(f"    ❌ Failed fact-check: {check_text}")
                    attempts += 1
                    if attempts >= max_attempts:
                        break
                        
                    # Request rewrite for factual correction
                    correction_prompt = f"""You are the correlation generator. The proposed correlation failed a fact-check review.
                    
Proposed Correlation:
{json.dumps(current_corr, indent=2)}

Feedback:
{check_text}

Rewrite the correlation to correct all issues. Return the rewritten correlation strictly as a JSON object."""
                    rewrite_response = membrane.chat_completion(
                        model="membrane-engagement-layer",
                        messages=[
                            {"role": "system", "content": writer_system_prompt},
                            {"role": "user", "content": correction_prompt}
                        ],
                        temperature=0.0
                    )
                    if isinstance(rewrite_response, dict):
                        rewrite_content = rewrite_response["choices"][0]["message"]["content"].strip()
                    else:
                        rewrite_content = rewrite_response.choices[0].message.content.strip()
                    if rewrite_content.startswith("```"):
                        lines = rewrite_content.split("\n")
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines[-1].startswith("```"):
                            lines = lines[:-1]
                        rewrite_content = "\n".join(lines).strip()
                    current_corr = json.loads(rewrite_content)
                    # Auto-normalize domain typos in report_markdown and citations
                    if "report_markdown" in current_corr and isinstance(current_corr["report_markdown"], str):
                        current_corr["report_markdown"] = current_corr["report_markdown"].replace("sao.wa.wa.gov", "sao.wa.gov")
                    if "citations" in current_corr and isinstance(current_corr["citations"], list):
                        for cit in current_corr["citations"]:
                            if "url" in cit and isinstance(cit["url"], str):
                                cit["url"] = cit["url"].replace("sao.wa.wa.gov", "sao.wa.gov")
            except Exception as e:
                print("    Error during fact-checking:", e)
                break
                
        if fact_check_passed:
            generated_count += 1

    # 7. Save Approved Correlations
    ids = []
    for c in validated_correlations:
        print(f"💾 Saving approved correlation: '{c.get('title')}'")
        row_id = save_correlation(c)
        ids.append(row_id)
        
    print(f"🤖 Successfully generated and saved {len(ids)} intelligent correlations.")
    if conn:
        conn.close()
    return {"status": "success", "source": "upgraded-intelligent-semantic-builder", "generated_ids": ids}

if __name__ == "__main__":
    generate_correlations()
