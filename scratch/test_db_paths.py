import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.backend.correlation_engine import get_sqlite_conn

def test():
    for db_name in ["sao_audits.db", "sao_2024.db", "municipal_intent.db"]:
        conn = get_sqlite_conn(db_name)
        if conn:
            print(f"Connection to {db_name} SUCCESS!")
            conn.close()
        else:
            print(f"Connection to {db_name} FAILED (returned None)!")

if __name__ == "__main__":
    test()
