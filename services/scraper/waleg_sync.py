import os
import requests
import json
import sqlite3
import psycopg2
import xml.etree.ElementTree as ET
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

def get_xml_namespace(element):
    m = ET.re.match(r'\{.*\}', element.tag)
    return m.group(0) if m else ''

def fetch_rcw_cites(biennium, bill_number):
    """Fetches RCW sections affected by the bill."""
    url = "https://wslwebservices.leg.wa.gov/LegislationService.asmx/GetRcwCites"
    params = {"biennium": biennium, "billNumber": bill_number}
    cites = []
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            ns = get_xml_namespace(root)
            for cite_node in root.findall(f'.//{ns}RcwCite'):
                rcw_text = cite_node.find(f'{ns}RcwCiteText')
                if rcw_text is not None and rcw_text.text:
                    cites.append(rcw_text.text.strip())
    except Exception as e:
        print(f"    Failed fetching RCW cites for Bill {bill_number}: {e}")
    return cites

def fetch_bill_details(biennium, bill_number):
    """Fetches details (ShortDescription and Sponsor) for a specific bill."""
    url = "https://wslwebservices.leg.wa.gov/LegislationService.asmx/GetLegislation"
    params = {"biennium": biennium, "billNumber": bill_number}
    details = {"title": "", "sponsor": ""}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            ns = get_xml_namespace(root)
            leg_node = root.find(f'.//{ns}Legislation')
            if leg_node is not None:
                short_desc = leg_node.find(f'{ns}ShortDescription')
                sponsor = leg_node.find(f'{ns}Sponsor')
                
                details["title"] = short_desc.text.strip() if short_desc is not None and short_desc.text else ""
                details["sponsor"] = sponsor.text.strip() if sponsor is not None and sponsor.text else ""
    except Exception as e:
        print(f"    Failed fetching detailed info for Bill {bill_number}: {e}")
    return details

def classify_bill_policy(bill_title, bill_number) -> str:
    """Uses a rule-based keyword classifier to categorize the bill's policy area."""
    title_up = bill_title.upper()
    
    # Define mapping of category to lists of keywords
    keywords_mapping = {
        "Taxation & Finance": [
            "TAX", "FINANCE", "REVENUE", "BUDGET", "APPROPRIATION", "LEVY", "BOND", "FISCAL", "PROPERTY TAX", 
            "SALES TAX", "EXCISE", "FUNDS", "EXEMPTION", "ASSESSMENT", "SURCHARGE", "FEE", "TAXATION"
        ],
        "Environmental & Growth Management (SEPA/GMA)": [
            "ENVIRONMENT", "GROWTH MANAGEMENT", "GMA", "SEPA", "SHORELINE", "WILDLIFE", "FOREST", "WATER", "CLIMAT",
            "CARBON", "EMISSION", "LAND USE", "ZONING", "CONSERVATION", "PARK", "HABITAT", "CLEAN ENERGY", "RECYCL",
            "SOLAR", "WIND", "POLLUTION", "WASTE", "AGRICULTUR", "FISH"
        ],
        "Transportation & Infrastructure": [
            "TRANSPORTATION", "ROAD", "HIGHWAY", "BRIDGE", "TRANSIT", "VEHICLE", "TRAFFIC", "PORT", "AIRCRAFT",
            "RAILWAY", "STREET", "INFRASTRUCTURE", "FERRY", "AIRPORT", "PARKING"
        ],
        "Labor & Pensions": [
            "LABOR", "PENSION", "RETIREMENT", "EMPLOYEE", "COLLECTIVE BARGAINING", "WAGE", "BENEFIT", "WORKERS' COMP",
            "UNEMPLOYMENT", "SALARY", "UNION", "EMPLOYER", "WORKFORCE", "EMPLOYMENT", "LEAVE", "VACATION"
        ],
        "Public Records & Open Meetings": [
            "PUBLIC RECORDS", "OPEN MEETINGS", "OPMA", "PRA", "DISCLOSURE", "PRIVACY", "RECORD KEEPING", "FREEDOM OF INFO",
            "ARCHIVE", "TRANSPARENCY", "MEETING"
        ],
        "Procurement & Contracting": [
            "PROCUREMENT", "CONTRACT", "BID", "PUBLIC WORKS", "PURCHASING", "VENDOR", "SUBCONTRACT", "AGREEMENT"
        ],
        "Unfunded Mandate": [
            "MANDAT", "REQUIREMENT", "COMPEL", "IMPOSE", "OBLIGATION", "MANDATORY"
        ]
    }
    
    best_category = "General Administration"
    max_matches = 0
    
    for category, keywords in keywords_mapping.items():
        matches = 0
        for kw in keywords:
            if kw in title_up:
                matches += 1
        if matches > max_matches:
            max_matches = matches
            best_category = category
            
    return best_category

def load_existing_bills() -> set:
    """Loads all existing bill numbers from SQLite and Postgres to avoid duplicate processing."""
    existing = set()
    sqlite_conn = get_sqlite_conn()
    if sqlite_conn:
        try:
            cur = sqlite_conn.cursor()
            cur.execute("SELECT bill_number FROM legislative_bills")
            for r in cur.fetchall():
                existing.add(r['bill_number'])
            cur.close()
            sqlite_conn.close()
        except Exception as e:
            print(f"Failed loading bills from SQLite: {e}")
            
    pg_conn = get_pg_conn()
    if pg_conn:
        try:
            cur = pg_conn.cursor()
            cur.execute("SELECT bill_number FROM legislative_bills")
            for r in cur.fetchall():
                existing.add(r[0])
            cur.close()
            pg_conn.close()
        except Exception as e:
            print(f"Failed loading bills from Postgres: {e}")
            
    return existing

def save_bill(bill_id, title, biennium, sponsor, rcws_json, policy_cat):
    """Saves a bill to both SQLite and Postgres databases."""
    sqlite_conn = get_sqlite_conn()
    if sqlite_conn:
        try:
            cur = sqlite_conn.cursor()
            cur.execute(
                """
                INSERT OR IGNORE INTO legislative_bills (bill_number, title, biennium, sponsor, summary, affected_rcws, affected_wacs, policy_category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (bill_id, title, biennium, sponsor, "", rcws_json, "[]", policy_cat)
            )
            sqlite_conn.commit()
            cur.close()
            sqlite_conn.close()
        except Exception as e:
            print(f"    SQLite insert failed for bill {bill_id}: {e}")
            
    pg_conn = get_pg_conn()
    if pg_conn:
        try:
            cur = pg_conn.cursor()
            cur.execute(
                """
                INSERT INTO legislative_bills (bill_number, title, biennium, sponsor, summary, affected_rcws, affected_wacs, policy_category)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (bill_number) DO NOTHING
                """,
                (bill_id, title, biennium, sponsor, "", rcws_json, "[]", policy_cat)
            )
            pg_conn.commit()
            cur.close()
            pg_conn.close()
        except Exception as e:
            print(f"    Postgres insert failed for bill {bill_id}: {e}")

def sync_passed_bills(limit_per_biennium=100):
    print("🚀 [WALEG SYNC] Syncing passed legislation (2020-Present)...")
    
    # Load all existing bill IDs from DB to prevent duplicate processing
    existing_bills = load_existing_bills()
    print(f"  Pre-loaded {len(existing_bills)} existing bills from database.")
    
    bienniums = ["2019-20", "2021-22", "2023-24", "2025-26"]
    saved_count = 0
    
    biennium_agencies = [(b, a) for b in bienniums for a in ["House", "Senate"]]
    for biennium, agency in biennium_agencies:
        print(f"  Fetching Governor Signed Bills for Biennium {biennium} ({agency})...")
        url = "https://wslwebservices.leg.wa.gov/LegislationService.asmx/GetLegislationGovernorSigned"
        params = {"biennium": biennium, "agency": agency}
        
        try:
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code != 200:
                print(f"    Failed to query WSL API: {resp.status_code}")
                continue
                
            root = ET.fromstring(resp.content)
            ns = get_xml_namespace(root)
            
            bills = root.findall(f'.//{ns}LegislationInfo')
            print(f"    Found {len(bills)} governor-signed bills.")
            
            processed_in_biennium = 0
            for bill in bills:
                if processed_in_biennium >= limit_per_biennium:
                    break
                    
                bill_num_node = bill.find(f'{ns}BillNumber')
                bill_id_node = bill.find(f'{ns}BillId')
                
                bill_number = bill_num_node.text.strip() if bill_num_node is not None else ""
                bill_id = bill_id_node.text.strip() if bill_id_node is not None else ""
                
                if not bill_number or not bill_id:
                    continue
                    
                # Skip if already exists in DB (memory check)
                if bill_id in existing_bills:
                    continue
                    
                print(f"    * Processing new passed bill: {bill_id}...")
                
                # Fetch detailed info (Title and Sponsor) from GetLegislation
                details = fetch_bill_details(biennium, bill_number)
                title = details["title"]
                sponsor = details["sponsor"]
                
                if not title:
                    continue
                    
                # Fetch RCWs cited
                rcws = fetch_rcw_cites(biennium, bill_number)
                rcws_json = json.dumps(rcws)
                
                # Classify policy area using rule-based keywords
                policy_cat = classify_bill_policy(title, bill_id)
                
                # Save to database
                save_bill(bill_id, title, biennium, sponsor, rcws_json, policy_cat)
                
                existing_bills.add(bill_id)
                saved_count += 1
                processed_in_biennium += 1
                
        except Exception as e:
            print(f"    Error processing biennium {biennium}: {e}")
            
    print(f"✅ [WALEG SYNC] Sync complete. Ingested {saved_count} new passed bills.")

if __name__ == "__main__":
    sync_passed_bills(limit_per_biennium=100)
