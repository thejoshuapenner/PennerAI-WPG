import sqlite3

def check_db():
    for db_name in ["sao_audits.db", "sao_2024.db"]:
        conn = sqlite3.connect(f"/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/{db_name}")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        print(f"--- FINDINGS in {db_name} ---")
        cur.execute("SELECT report_num, jurisdiction, summary, year FROM findings WHERE jurisdiction LIKE '%Aberdeen%' OR jurisdiction LIKE '%Ocosta%' OR jurisdiction LIKE '%La Center%' LIMIT 10")
        for r in cur.fetchall():
            print(dict(r))

        conn.close()

if __name__ == "__main__":
    check_db()
