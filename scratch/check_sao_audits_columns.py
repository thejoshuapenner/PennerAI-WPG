import sqlite3

def check_db():
    conn = sqlite3.connect("/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/sao_audits.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(findings)")
    columns = [col[1] for col in cur.fetchall()]
    print("sao_audits.db findings columns:", columns)
    conn.close()

if __name__ == "__main__":
    check_db()
