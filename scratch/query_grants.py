import sqlite3

def check_db():
    conn = sqlite3.connect("/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/municipal_intent.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    print("--- GRANTS ---")
    cur.execute("SELECT * FROM grants WHERE recipient_jurisdiction LIKE '%Anacortes%' LIMIT 10")
    for r in cur.fetchall():
        print(dict(r))
        
    print("\n--- SCHOOL FINANCIALS ---")
    cur.execute("SELECT * FROM school_district_financials WHERE district_name LIKE '%Ocosta%' OR district_name LIKE '%La Center%' OR district_name LIKE '%Aberdeen%' LIMIT 10")
    for r in cur.fetchall():
        print(dict(r))

    conn.close()

if __name__ == "__main__":
    check_db()
