import sqlite3

def print_recent():
    for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
        conn = sqlite3.connect(f"/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/{db_name}")
        cur = conn.cursor()
        print(f"\n--- Recent correlations in {db_name} ---")
        try:
            cur.execute("SELECT id, title, status, created_at FROM correlations ORDER BY id DESC LIMIT 5")
            rows = cur.fetchall()
            for r in rows:
                print(r)
        except Exception as e:
            print(f"Error: {e}")
        conn.close()

if __name__ == "__main__":
    print_recent()
