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

MEMBRANE_API_KEY = os.environ.get("MEMBRANE_API_KEY")
MEMBRANE_URL = "https://membrane-api.com/v1/chat/completions"

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
    """Uses Membrane to classify the policy area of a bill."""
    if not MEMBRANE_API_KEY:
        return "General Governance"
        
    headers = {
        "Authorization": f"Bearer {MEMBRANE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "membrane-engagement-layer",
        "messages": [
            {
                "role": "system",
                "content": """You are a policy analyst tracking state mandates. 
                Classify the main policy category of the given Washington State bill.
                Choose ONE of the following categories:
                - Unfunded Mandate
                - Taxation & Finance
                - Environmental & Growth Management (SEPA/GMA)
                - Transportation & Infrastructure
                - Labor & Pensions
                - Public Records & Open Meetings
                - Procurement & Contracting
                - General Administration
                
                Return a JSON object: {"category": "Category Name"}"""
            },
            {
                "role": "user",
                "content": f"Classify this bill:\nBill ID: {bill_number}\nTitle: {bill_title}"
            }
        ],
        "response_format": {"type": "json_object"}
    }
    
    try:
        resp = requests.post(MEMBRANE_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            content = resp.json()['choices'][0]['message']['content']
            if "```json" in content: content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content: content = content.split("```")[1].split("```")[0].strip()
            return json.loads(content).get("category", "General Administration")
    except Exception as e:
        print(f"    Membrane classification failed for Bill {bill_number}: {e}")
        
    return "General Administration"

def is_bill_in_sqlite(bill_id):
    try:
        conn = sqlite3.connect(SQLITE_PATH, timeout=30.0)
        cur = conn.cursor()
        cur.execute("SELECT bill_number FROM legislative_bills WHERE bill_number = ?", (bill_id,))
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        return exists
    except Exception as e:
        print(f"    SQLite exists check failed: {e}")
        return False

def save_bill_to_sqlite(bill_id, title, biennium, sponsor, rcws_json, policy_cat):
    try:
        conn = sqlite3.connect(SQLITE_PATH, timeout=30.0)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO legislative_bills (bill_number, title, biennium, sponsor, summary, affected_rcws, affected_wacs, policy_category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (bill_id, title, biennium, sponsor, "", rcws_json, "[]", policy_cat)
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"    SQLite insert failed: {e}")
        return False

def sync_passed_bills(limit_per_biennium=100):
    print("🚀 [WALEG SYNC] Syncing passed legislation (2020-Present)...")
    
    bienniums = ["2019-20", "2021-22", "2023-24", "2025-26"]
    
    pg_conn = get_pg_conn()
    pg_cur = pg_conn.cursor() if pg_conn else None
    
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
            
            # Sync a subset per run to save performance/tokens, or run full in production
            for i, bill in enumerate(bills[:limit_per_biennium]):
                bill_num_node = bill.find(f'{ns}BillNumber')
                bill_id_node = bill.find(f'{ns}BillId')
                
                bill_number = bill_num_node.text.strip() if bill_num_node is not None else ""
                bill_id = bill_id_node.text.strip() if bill_id_node is not None else ""
                
                if not bill_number:
                    continue
                    
                # Fetch detailed info (Title and Sponsor) from GetLegislation
                details = fetch_bill_details(biennium, bill_number)
                title = details["title"]
                sponsor = details["sponsor"]
                
                if not title:
                    continue
                    
                # Skip if already exists in DB
                in_db = False
                if pg_cur:
                    pg_cur.execute("SELECT bill_number FROM legislative_bills WHERE bill_number = %s", (bill_id,))
                    if pg_cur.fetchone():
                        in_db = True
                else:
                    if is_bill_in_sqlite(bill_id):
                        in_db = True
                        
                if in_db:
                    continue
                    
                print(f"    * Processing passed bill: {bill_id} - {title[:60]}...")
                
                # Fetch RCWs cited
                rcws = fetch_rcw_cites(biennium, bill_number)
                rcws_json = json.dumps(rcws)
                
                # Classify policy area using Membrane
                policy_cat = classify_bill_policy(title, bill_id)
                
                # Postgres Insert
                if pg_conn and pg_cur:
                    try:
                        pg_cur.execute(
                            """
                            INSERT INTO legislative_bills (bill_number, title, biennium, sponsor, summary, affected_rcws, affected_wacs, policy_category)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (bill_number) DO NOTHING
                            """,
                            (bill_id, title, biennium, sponsor, "", rcws_json, "[]", policy_cat)
                        )
                        saved_count += 1
                    except Exception as pg_err:
                        print(f"    Postgres insert failed: {pg_err}")
                        pg_conn.rollback()
                        
                # SQLite Insert
                if save_bill_to_sqlite(bill_id, title, biennium, sponsor, rcws_json, policy_cat):
                    if not pg_conn:
                        saved_count += 1
                        
        except Exception as e:
            print(f"    Error processing biennium {biennium}: {e}")
            
    if pg_conn:
        pg_conn.commit()
        pg_cur.close()
        pg_conn.close()
        
    print(f"✅ [WALEG SYNC] Sync complete. Ingested {saved_count} passed bills.")

if __name__ == "__main__":
    sync_passed_bills(limit_per_biennium=100)
