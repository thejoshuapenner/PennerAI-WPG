import sqlite3

def check_db():
    for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
        conn = sqlite3.connect(f"/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/{db_name}")
        cur = conn.cursor()
        print(f"\n--- Correlations in {db_name} ---")
        try:
            cur.execute("SELECT id, title, status FROM correlations")
            rows = cur.fetchall()
            print(f"Total rows: {len(rows)}")
            for r in rows:
                print(r)
        except Exception as e:
            print(f"Error: {e}")
        conn.close()

if __name__ == "__main__":
    check_db()
