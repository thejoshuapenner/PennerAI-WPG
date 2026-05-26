import sqlite3

def cleanup():
    conn = sqlite3.connect("/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/sao_audits.db")
    cur = conn.cursor()
    
    # Let's delete ID 59, 60, 61, 62, 63
    ids_to_delete = [59, 60, 61, 62, 63]
    for id_val in ids_to_delete:
        cur.execute("DELETE FROM correlations WHERE id = ?", (id_val,))
    
    conn.commit()
    print(f"Deleted extra correlations: {ids_to_delete}")
    
    # Print current proposed correlations
    cur.execute("SELECT id, title, status FROM correlations WHERE status = 'proposed'")
    rows = cur.fetchall()
    print("Current Proposed Correlations in DB:")
    for r in rows:
        print(r)
        
    conn.close()

if __name__ == "__main__":
    cleanup()
