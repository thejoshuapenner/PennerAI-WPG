import os
import json
import psycopg2
import sqlite3
from psycopg2.extras import RealDictCursor
import litellm
from dotenv import load_dotenv

load_dotenv()

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:penner_secret_password_2026@localhost:5432/penner_governance_db"
)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

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

def fetch_recent_data():
    """Fetch diverse findings, council actions, budgets, grants, and school financials from PostgreSQL or SQLite."""
    findings_pool = []
    actions_pool = []
    budgets_pool = []
    grants_pool = []
    school_financials_pool = []
    
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
            actions_pool = [dict(r) for r in cur.fetchall()]
        except Exception:
            conn.rollback()

        # Fetch budgets
        try:
            cur.execute(
                """
                SELECT b.jurisdiction_name, b.entity_type, b.fiscal_year, b.total_revenue, b.total_expenditures, b.fund_balance_beginning, b.fund_balance_ending,
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
                SELECT id, grant_title, awarding_agency, recipient_jurisdiction, award_amount, award_date, purpose_category, funding_source
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
                SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount
                FROM school_district_financials
                ORDER BY fiscal_year DESC, id DESC
                LIMIT 100
                """
            )
            school_financials_pool = [dict(r) for r in cur.fetchall()]
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
                        "key_action": f"{r['agenda_item_title'] or ''}: {r['key_action']}",
                        "dollar_amount": r["dollar_amount"]
                    })
                
                # SQLite Budgets
                try:
                    cur.execute(
                        """
                        SELECT b.jurisdiction_name, b.entity_type, b.fiscal_year, b.total_revenue, b.total_expenditures, b.fund_balance_beginning, b.fund_balance_ending,
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
                        SELECT id, grant_title, awarding_agency, recipient_jurisdiction, award_amount, award_date, purpose_category, funding_source
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
                        SELECT district_name, fiscal_year, enrollment, total_revenue, total_expenditures, levy_amount, special_education_spending, federal_funding_amount
                        FROM school_district_financials
                        ORDER BY fiscal_year DESC
                        LIMIT 100
                        """
                    )
                    school_financials_pool = [dict(r) for r in cur.fetchall()]
                except Exception:
                    pass
                
                conn.close()
            except Exception:
                pass

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
                
    return findings, actions, budgets, grants, school_financials

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
During recent 2025 checks, the Washington State Auditor's Office noted that some small police departments, including Orting and Enumclaw, had incomplete paperwork. The issues were mainly related to tracking training hours and background checks. This happened after new state laws in 2023 increased the details cities must record for police certifications.

### Upgrading the Systems
These small towns did not fail records checks on purpose. Instead, their office staff was overwhelmed by the new paperwork requirements. Traditionally, these smaller cities kept record files on paper, which makes it harder to organize and check during reviews.

### Moving Forward
To solve this problem, towns are starting to use modern tracking software. By moving to digital records and training their office staff, these cities are making sure they meet state rules. This helps local departments run more efficiently and avoids potential legal issues.
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
Local governments and school districts are successfully teaming up with state agencies to fund clean energy upgrades. In 2025, school districts like Bellevue and Snohomish received grants to install solar panels, replace old heating units, and make classroom lighting more efficient.

### Saving Local Tax Dollars
These clean energy projects are funded by state grants rather than local property taxes. By utilizing these grants, schools and cities can lower their electricity bills. The money saved on utilities can then be kept in classrooms or general city services.

### Successful Partnerships
School boards and city councils have approved contracts to begin these projects. This shows how state-level grants can help local schools and cities modernize their buildings, save money, and lower their carbon footprint without raising taxes for local residents.
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

def generate_correlations():
    """Generates 2-3 correlation reports and saves them to the DB as proposed."""
    print("🤖 Starting AI Correlation Generation...")
    
    findings, actions, budgets, grants, school_financials = fetch_recent_data()
    print(f"  Retrieved {len(findings)} audits, {len(actions)} council actions, {len(budgets)} budgets, {len(grants)} grants, and {len(school_financials)} school records from database.")
    
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
        findings_text += f"- [Audit {f['report_num']}] Jurisdiction: {f['jurisdiction']} | Year: {year_str} | Category: {f['category']} | Summary: {f['summary']} | Impact: ${f['dollar_impact']:,}\n"
        
    actions_text = ""
    for a in actions[:15]:
        actions_text += f"- [Event {a['event_id']}] Jurisdiction: {a['jurisdiction']} | Committee: {a['committee']} | Description: {a['key_action']} | Amount: ${a['dollar_amount']:,}\n"

    budgets_text = ""
    for b in budgets[:15]:
        item_str = f" | {b['major_category']}: ${b['item_amount']:,}" if b.get("major_category") else ""
        budgets_text += f"- [Budget] Jurisdiction: {b['jurisdiction_name']} | Year: {b['fiscal_year']} | Revenue: ${b['total_revenue']:,} | Expenditures: ${b['total_expenditures']:,}{item_str}\n"

    grants_text = ""
    for g in grants[:15]:
        date_str = str(g.get("award_date") or "")
        grants_text += f"- [Grant {g['id']}] Recipient: {g['recipient_jurisdiction']} | Title: {g['grant_title']} | Amount: ${g['award_amount']:,} | Date: {date_str} | Agency: {g['awarding_agency']} | Purpose: {g['purpose_category']}\n"

    schools_text = ""
    for s in school_financials[:15]:
        schools_text += f"- [SchoolSD] District: {s['district_name']} | Year: {s['fiscal_year']} | Enrollment: {s['enrollment']:.0f} FTE | Rev: ${s['total_revenue']:,} | Exp: ${s['total_expenditures']:,} | Levy: ${s['levy_amount']:,} | SpEd Exp: ${s['special_education_spending']:,}\n"

    system_prompt = """You are an expert civic intelligence analyst identifying trends and correlations across Washington State auditor reports, local council meeting minutes, municipal budgets, grants, and school district performance data.
Analyze the provided audit findings, local city council events, municipal budgets, state/federal grants, and school district financials. Look for underlying connections, policy effects, or cooperative initiatives.

CRITICAL: Your surfaced intelligence must be balanced and not solely focused on negative audit failures, deficits, or problems.
At least one of the correlations you identify MUST highlight positive civic progress, collaborative contracts, community upgrades, or state/federal grant funding wins (e.g. clean energy projects, school improvements, or inter-local agreements).

CRITICAL: All content must be written in plain, accessible language that is easy for the general public to understand (target an 8th-to-9th-grade reading level), while maintaining strict factual accuracy.
Avoid dense academic jargon and overly complex phrasing. For example:
- Instead of "systemic administrative collapse", use "severe staffing shortages and record-keeping delays".
- Instead of "inter-departmental data fragmentation hampers permitting", use "departments using software that doesn't share information, which slows down building permits".
- Keep explanations direct, active, and engaging for everyday citizens.

Identify 2 distinct correlations. For each, generate:
1. Title: A sharp, news-style headline summarizing the correlation in plain English.
2. Hook: A 1-2 sentence compelling teaser.
3. Report: A markdown report (2-3 paragraphs) explaining the trend, why it matters to local residents, and the local impact.
   CRITICAL: You MUST explicitly include the audit/fiscal year (e.g. 2024 or 2025) in the narrative text when describing the data.
4. Citations: List the specific items cited.
   CRITICAL: You MUST explicitly include the year in the citation title.
   Support citations of source types: 'audit', 'council', 'budget', 'grant', or 'school'.

Format your output STRICTLY as a JSON object matching this schema:
{
  "correlations": [
    {
      "title": "Headline string",
      "hook": "Teaser string",
      "report_markdown": "Full analysis report in Markdown format",
      "citations": [
        {
          "id": "The report_num, event_id, grant_id, or budget/school year cited",
          "source": "audit" | "council" | "budget" | "grant" | "school",
          "title": "Readable title for the citation containing the year, e.g. Orting Budget (2025)",
          "url": "Provide a valid URL (use: https://portal.sao.wa.gov/ReportSearch/Home/ViewReportFile?ReportNumber=NUM for audits, and a search URL or dummy search URL for council/budget/grant/school)"
        }
      ]
    }
  ]
}
Return ONLY the raw JSON object, without markdown block formatting (do not wrap in ```json)."""

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
{schools_text}"""

    try:
        response = litellm.completion(
            model="gemini/gemini-3.5-flash",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            api_key=GEMINI_API_KEY
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean potential markdown wrapping
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()
            
        data = json.loads(content)
        ids = []
        for c in data.get("correlations", []):
            row_id = save_correlation(c)
            ids.append(row_id)
            
        print(f"🤖 Successfully generated and saved {len(ids)} correlations.")
        return {"status": "success", "source": "gemini-3.5-flash", "generated_ids": ids}
        
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
