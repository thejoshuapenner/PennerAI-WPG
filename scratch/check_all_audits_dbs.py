import sqlite3

paths = [
    "/Users/thejoshuapenner/.openclaw/workspace/sao-scraper/sao_audits.db",
    "/Users/thejoshuapenner/sao_audits.db",
    "/Users/thejoshuapenner/My Drive/Penner Strategy/PennerAI-WPG/temp_repos/wa-policy-graph-backend/sao_audits.db",
    "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/sao_audits.db"
]

def check():
    for p in paths:
        print(f"\nDB Path: {p}")
        try:
            conn = sqlite3.connect(p)
            cur = conn.cursor()
            cur.execute("SELECT id, title, status FROM correlations ORDER BY id DESC LIMIT 3")
            rows = cur.fetchall()
            print(f"Success! Last 3 correlations:")
            for r in rows:
                print(r)
            conn.close()
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    check()
