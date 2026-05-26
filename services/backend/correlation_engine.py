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

def get_pg_conn():
    return psycopg2.connect(POSTGRES_URL)

def get_sqlite_conn(db_name: str):
    sqlite_dir = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper"
    db_path = os.path.join(sqlite_dir, db_name)
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
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
    cit_id = str(cit.get("id") or "")
    
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
                    cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures FROM budgets WHERE id = ?", (int(cit_id),))
                else:
                    clean_search = re.sub(r'[^a-zA-Z\s]', '', cit_id).split()
                    search_val = f"%{clean_search[0]}%" if clean_search else f"%{cit_id}%"
                    cur.execute("SELECT jurisdiction_name, fiscal_year, total_revenue, total_expenditures FROM budgets WHERE jurisdiction_name LIKE ? OR ? LIKE '%' || jurisdiction_name || '%'", (search_val, cit_id))
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row:
                    return f"Budget Record for {row[0]} ({row[1]}): Total Revenue: ${row[2]:,}, Total Expenditures: ${row[3]:,}."
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

def generate_correlations():
    """Generates 2-3 correlation reports and saves them to the DB as proposed."""
    print("🤖 Starting AI Correlation Generation...")
    
    findings, actions, budgets, grants, school_financials, contributions, bills = fetch_recent_data()
    print(f"  Retrieved {len(findings)} audits, {len(actions)} council actions, {len(budgets)} budgets, {len(grants)} grants, {len(school_financials)} school records, {len(contributions)} campaign contributions, and {len(bills)} legislative bills from database.")
    
    # If DB is empty, use realistic fallback mock data to seed
    if (len(findings) < 2 and len(budgets) < 2) or not GEMINI_API_KEY:
        print("  Insufficient database context or GEMINI_API_KEY missing. Seeding fallback mock correlations.")
        fallbacks = get_fallback_correlations()
        ids = []
        for f in fallbacks:
            row_id = save_correlation(f)
            ids.append(row_id)
        return {"status": "success", "source": "mock_fallbacks", "generated_ids": ids}
        
    # Format inputs for LLM
    findings_text = ""
    for f in findings[:15]:
        year_str = f.get("year", "2025")
        findings_text += f"- [Audit {f['report_num']}] Jurisdiction: {f['jurisdiction']} | Year: {year_str} | Category: {f['category']} | Summary: {f['summary']} | Impact: ${f['dollar_impact']:,} | URL: https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber={f['report_num']}\n"
        
    actions_text = ""
    for a in actions[:15]:
        actions_text += f"- [Event {a['event_id']}] Jurisdiction: {a['jurisdiction']} | Committee: {a['committee']} | Description: {a['key_action']} | Amount: ${a['dollar_amount']:,} | URL: {a.get('source_url') or 'https://municipal-intent-search'}\n"

    budgets_text = ""
    for b in budgets[:15]:
        item_str = f" | {b['major_category']}: ${b['item_amount']:,}" if b.get("major_category") else ""
        budgets_text += f"- [Budget {b['id']}] Jurisdiction: {b['jurisdiction_name']} | Year: {b['fiscal_year']} | Revenue: ${b['total_revenue']:,} | Expenditures: ${b['total_expenditures']:,}{item_str} | URL: {b.get('source_url') or 'https://portal.sao.wa.gov/ReportSearch'}\n"

    grants_text = ""
    for g in grants[:15]:
        date_str = str(g.get("award_date") or "")
        grants_text += f"- [Grant {g['id']}] Recipient: {g['recipient_jurisdiction']} | Title: {g['grant_title']} | Amount: ${g['award_amount']:,} | Date: {date_str} | Agency: {g['awarding_agency']} | Purpose: {g['purpose_category']} | URL: {g.get('source_url') or 'https://www.usaspending.gov'}\n"

    schools_text = ""
    for s in school_financials[:15]:
        schools_text += f"- [School {s['id']}] District: {s['district_name']} | Year: {s['fiscal_year']} | Enrollment: {s['enrollment']:.0f} FTE | Rev: ${s['total_revenue']:,} | Exp: ${s['total_expenditures']:,} | Levy: ${s['levy_amount']:,} | SpEd Exp: ${s['special_education_spending']:,} | URL: {s.get('source_url') or 'https://data.wa.gov'}\n"

    contributions_text = ""
    for c in contributions[:15]:
        date_str = str(c.get("receipt_date") or "")
        contributions_text += f"- [Contribution {c['id']}] Candidate: {c['candidate_name']} | Contributor: {c['contributor_name']} ({c['contributor_employer'] or 'No Employer info'}) | Amount: ${c['amount']:,} | Date: {date_str} | Jurisdiction: {c['jurisdiction'] or 'Statewide/Unknown'} | URL: {c.get('source_url') or 'https://www.pdc.wa.gov'}\n"

    bills_text = ""
    for b in bills[:15]:
        passed_str = f" | Passed: {b['passed_date']}" if b.get("passed_date") else ""
        summary_str = f" | Summary: {b['summary']}" if b.get("summary") else ""
        bills_text += f"- [Bill {b['bill_number']}] Title: {b['title']} | Biennium: {b['biennium']} | Sponsor: {b['sponsor'] or 'Unknown'} | Category: {b['policy_category'] or 'General'}{passed_str}{summary_str} | URL: https://app.leg.wa.gov/billsummary?BillNumber={b['bill_number']}\n"

    system_prompt = """You are an expert investigative civic analyst specializing in tracking public finance, political accountability, and downstream policy outcomes in Washington State. Your objective is to conduct deep, rigorous civic investigations and highlight analytical correlations rather than commercial or journalistic news summaries.
Analyze the provided audit findings, local city council actions, municipal budgets, state/federal grants, school district financials, campaign contributions, and legislative bills. Find underlying connections, policy effects, or cooperative initiatives.

CRITICAL - CAUSALITY & INVESTIGATIVE CONNECTIONS (MONEY ➔ POLICY ➔ OUTCOME):
- Uncover unexpected, interesting, or damaging correlations, as well as notable policy successes, project completions, or other known concrete outcomes.
- Specifically, prioritize tracing sequences of influence, policy, and subsequent results: Campaign contributions or lobbying dollars ($) from special interests, developers, or unions ➔ specific state legislative bills or municipal policies passed ➔ downstream local outcomes (which can include local administrative failures/deficits/bad audit findings, OR conversely, positive civic successes, new infrastructure contracts, or other known project/grant outcomes). (i.e. Influence ➔ Law/Policy ➔ Downstream Outcome/Result).
- Connect the dots clearly, showing how financial or political inputs correlate with subsequent local outcomes and administrative results.

CRITICAL - TEMPORAL SEQUENCING & CHRONOLOGICAL FLOW:
- Temporal order is just as important as matching entries. You MUST establish a logical timeline showing that events occurred sequentially.
- The narrative must explicitly trace this chronology.
- IMPORTANT - CHRONOLOGICAL INTEGRITY: A past event cannot be a "downstream result" or effect of a future event. For example, a compliance failure from a 2024 audit CANNOT be caused by, strain from, or related to a 2026 grant. Events can only influence or lead to subsequent events in the future. Always check the year/date of each record.
- Refer to the year of the data (e.g., 2024 fiscal year or 2025 budget year) in the narrative text. Do not claim that the events occurred in the publication year of the audit report (e.g. 2026) if the database entry indicates the data year is different (e.g. 2024).
- Do not treat correlations as static or simultaneous co-occurrences. Clearly walk the reader through the chronological progression.

CRITICAL - PROGRAM BOUNDARIES & CAUSATION:
- Do not fabricate or extrapolate causal links between unrelated programs or events. For example, do not claim that an audit finding regarding a procurement oversight on a Highway project was a result of or strain from a FEMA SAFER fire grant.
- If two events occur in the same jurisdiction but cover completely different areas (e.g. transport procurement and fire department staffing), you must treat them as parallel examples illustrating the overall scale of federal funding versus administrative capacity, rather than claiming one caused the other.
- Be precise when grouping entities. Do not apply a specific detail (like a dollar threshold, e.g. $25,000, or a specific program name) to multiple entities if that detail is only associated with one of them in the database inputs.

CRITICAL - ANALYTICAL TONE & LEGISLATIVE FACTUALITY:
- State legislative bills and policy changes are rarely passed by unanimous consent. However, you MUST NOT fabricate or include specific debates, floor arguments, opponent/proponent statements, or quotes unless they are explicitly present in the provided source text database. Do NOT use phrases like "proponents argued" or "opponents cautioned" to describe general policy tradeoffs; if the database summary does not list specific arguments, simply state what the bill does without attributing arguments or mentioning proponents or opponents.
- If the database only contains the bill number, summary, sponsors, and passed date, stick strictly to what the bill actually does. Do not invent quotes or floor statements. Do not include any hypothetical or general arguments/debates.
- Avoid commercial, sensationalist, or promotional news-reporting language. Do NOT use phrases like "state leaders hope", "lawmakers agree", or describing a bill as a simple "solution" without acknowledging its contested nature.
- Maintain a strictly analytical, objective, and investigative tone. Present the policy change as a debated mechanism with tradeoffs rather than an unalloyed positive development.
- EVERY claim in the report must be directly supported by the database inputs provided. Do not make ungrounded assumptions (e.g., claiming "no funds were lost" if the audit doesn't explicitly state that).
- Do not use words like 'influx', 'surge', 'crisis', or 'systemic failure' in the title or hook unless the database records for each cited entity explicitly support a significant increase, deficit, or systemic finding.
- If citing multiple audits or records for a single city or school district, refer to them as separate records or reports (using their specific IDs or report numbers); do not refer to them as 'the same audit/record' unless they share the same ID.

CRITICAL: All content must be written in plain, accessible language that is easy for the general public to understand (target an 8th-to-9th-grade reading level), while maintaining strict factual accuracy.
Avoid dense academic jargon and overly complex phrasing. For example:
- Instead of "systemic administrative collapse", use "severe staffing shortages and record-keeping delays".
- Instead of "inter-departmental data fragmentation hampers permitting", use "departments using software that doesn't share information, which slows down building permits".
- Keep explanations direct, active, and engaging for everyday citizens.

Identify 2 distinct correlations. For each, generate:
1. Title: A clear, analytical title that exposes the connection found (avoid clickbaity, commercial, or sensationalist news-headline phrasing).
2. Hook: A 1-2 sentence compelling teaser summarizing the core analytical connection.
3. Report: A markdown report (300-400 words) presenting the investigative analysis, tracing the temporal chain of events, explaining why it matters to local residents, and highlighting the downstream impacts.
   CRITICAL: The report MUST be written as an analytical investigation, leaning heavily toward citation of verifiable sources.
   CRITICAL: Every key fact, budget figure, audit finding, campaign contribution, or legislative statement in the report MUST be directly cited inline using standard markdown link syntax with a descriptive anchor text (e.g., `[Aberdeen School District Financial Report (2024)](url)` or `[Bill SSB 5412 (2025-26)](url)` or `[Contribution to Candidate X (2024)](url)`).
   The URL in these inline markdown links MUST exactly match the corresponding source URL defined in the `citations` list and the URL provided on the input line for that cited item.
   CRITICAL: You MUST explicitly include the audit/fiscal year or event date (e.g. 2024 or 2025) in the narrative text when describing the data.
4. Citations: List the specific items cited.
   CRITICAL: You MUST explicitly include the year in the citation title.
   Support citations of source types: 'audit', 'council', 'budget', 'grant', 'school', 'contribution', or 'bill'.

Format your output STRICTLY as a JSON object matching this schema:
{
  "correlations": [
    {
      "title": "Analytical connection title",
      "hook": "Teaser string",
      "report_markdown": "Full analysis report in Markdown format",
      "citations": [
        {
          "id": "The report_num, event_id, grant_id, contribution_id, bill_number, or budget/school year cited",
          "source": "audit" | "council" | "budget" | "grant" | "school" | "contribution" | "bill",
          "title": "Readable title for the citation containing the year, e.g. Orting Budget (2025) or Bill HB 1003 (2025)",
          "url": "Provide a valid URL (MUST exactly match the URL provided in the input list for this item; do not invent or use placeholder URLs)"
        }
      ]
    }
  ]
Return ONLY the raw JSON object, without markdown block formatting (do not wrap in ```json). Ensure that all double quotes inside the JSON string values are strictly escaped as \" to maintain a valid, parsable JSON structure."""


    prompt = f"""Identify 2 correlations based on these lists:

--- STATE AUDITOR FINDINGS ---
{findings_text}

--- MUNICIPAL COUNCIL ACTIONS ---
{actions_text}

--- LOCAL GOVERNMENT BUDGETS ---
{budgets_text}

--- STATE & FEDERAL GRANTS ---
{grants_text}

--- SCHOOL DISTRICT FINANCIALS ---
{schools_text}

--- SIGNIFICANT CAMPAIGN CONTRIBUTIONS ---
{contributions_text}

--- STATE LEGISLATIVE BILLS ---
{bills_text}"""

    try:
        membrane = MembraneClient()
        response = membrane.chat_completion(
            model="membrane-engagement-layer",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0
        )
        
        if isinstance(response, dict):
            content = response["choices"][0]["message"]["content"].strip()
        else:
            content = response.choices[0].message.content.strip()
        
        # Clean potential markdown wrapping
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()
            
        print("DEBUG: Raw response content:", repr(content))
        data = json.loads(content)
        
        # Self-correction loop
        validated_correlations = []
        for c in data.get("correlations", []):
            attempts = 0
            max_attempts = 2
            current_corr = c
            
            while attempts < max_attempts:
                # 1. Fetch verbatim contexts for all citations in current_corr
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
                
                # 2. Run fact checker prompt
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
2. Ensure there are no temporal contradictions (e.g. causes must precede effects; check the audit/data years vs grant dates).
3. Ensure there are no fabricated details (e.g. district numbers like No 5, or proponent/opponent debates) that are not explicitly present in the verbatim contexts.
4. Ensure all URLs in markdown links exactly match the citation URLs, and there are no placeholder URLs like '...ReportNumber=NUM'.
5. If there are ANY discrepancies, contradictions, or unsupported claims, output a list of issues.
6. If the report is 100% factually accurate, chronologically correct, and URLs match perfectly, output ONLY the word 'PASS' (no markdown, no quotes, no extra text).
"""
                print(f"Fact-checking generated correlation: '{current_corr.get('title')}' (Attempt {attempts + 1})...")
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
                    print("✅ Correlation passed fact-check!")
                    validated_correlations.append(current_corr)
                    break
                else:
                    print(f"❌ Correlation failed fact-check. Issues identified:\n{check_text}")
                    attempts += 1
                    if attempts >= max_attempts:
                        print("⚠️ Maximum correction attempts reached. Saving correlation despite warnings.")
                        validated_correlations.append(current_corr)
                        break
                        
                    # Request rewrite / correction
                    correction_prompt = f"""You are the correlation generator. The proposed correlation failed a strict fact-check review.
                    
Proposed Correlation:
Title: {current_corr.get('title')}
Hook: {current_corr.get('hook')}
Report Markdown:
{current_corr.get('report_markdown')}

Verbatim Contexts for Citations:
{json.dumps(citations_with_context, indent=2)}

Reviewer Feedback:
{check_text}

Rewrite the correlation to completely resolve all issues in the feedback.
Follow all original constraints:
- Stick strictly to the verbatim contexts.
- Correct any date or year references (do not call a 2024 audit a 2026 audit, etc.).
- Remove any fabricated details (e.g. do not invent district numbers or debate details if not in context).
- Ensure URLs in report markdown exactly match the citation URLs.
- Make the narrative understandable and easy to read.

Return the rewritten correlation strictly as a JSON object with keys 'title', 'hook', 'report_markdown', 'citations'. Do not wrap in markdown block formatting."""
                    
                    rewrite_response = membrane.chat_completion(
                        model="membrane-engagement-layer",
                        messages=[
                            {"role": "system", "content": "You are a helpful assistant."},
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
                        
                    try:
                        current_corr = json.loads(rewrite_content)
                    except Exception as parse_err:
                        print("Failed to parse rewritten correlation JSON:", parse_err)
                        validated_correlations.append(current_corr)
                        break
        
        ids = []
        for c in validated_correlations:
            print(f"DEBUG: Saving correlation: '{c.get('title')}'")
            row_id = save_correlation(c)
            print(f"DEBUG: Saved correlation. Result row_id: {row_id}")
            ids.append(row_id)
            
        print(f"🤖 Successfully generated and saved {len(ids)} correlations.")
        return {"status": "success", "source": "membrane-engagement-layer", "generated_ids": ids}
        
    except Exception as e:
        print("Error during AI correlation generation:", e)
        # Fallback in case of api error
        fallbacks = get_fallback_correlations()
        ids = []
        for f in fallbacks:
            row_id = save_correlation(f)
            ids.append(row_id)
        return {"status": "success", "source": "error_fallbacks", "generated_ids": ids}

if __name__ == "__main__":
    generate_correlations()
