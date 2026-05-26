import sqlite3

def clear_db():
    for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
        conn = sqlite3.connect(f"/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/{db_name}")
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM correlations WHERE status = 'proposed'")
            conn.commit()
            print(f"Cleared proposed correlations from {db_name}")
        except Exception as e:
            print(f"No table or failed to clear {db_name}: {e}")
        conn.close()

if __name__ == "__main__":
    clear_db()
