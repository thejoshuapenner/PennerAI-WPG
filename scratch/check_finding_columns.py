import sqlite3

def check_db():
    conn = sqlite3.connect("/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/sao_2024.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    for rnum in ['1039484', '1039596', '1039577', '1039592']:
        cur.execute("SELECT report_num, jurisdiction, summary, year FROM findings WHERE report_num = ?", (rnum,))
        row = cur.fetchone()
        if row:
            print(dict(row))
        else:
            print(f"Report {rnum} not found in sao_2024.db")
    conn.close()

if __name__ == "__main__":
    check_db()
