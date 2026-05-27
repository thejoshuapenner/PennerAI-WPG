import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:postgres_dev_password@localhost:5432/penner_governance_db"
)

def run_migration():
    print("🚀 Starting database vector dimension migration to 768...")
    
    try:
        conn = psycopg2.connect(POSTGRES_URL)
        cur = conn.cursor()
        
        tables = [
            ("findings", "idx_findings_embedding"),
            ("merged_actions", "idx_merged_actions_embedding"),
            ("processed_intent", "idx_processed_intent_embedding"),
            ("budget_items", "idx_budget_items_embedding"),
            ("grants", "idx_grants_embedding"),
            ("school_district_financials", "idx_school_financials_embedding")
        ]
        
        for table, index in tables:
            print(f"Migrating table: {table} (dropping {index}, altering type, recreating {index})...")
            try:
                # 1. Drop index
                cur.execute(f"DROP INDEX IF EXISTS {index};")
                # 2. Alter column type (cast from 1536 down to 768)
                cur.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector(768) USING embedding::vector(768);")
                # 3. Recreate HNSW index
                cur.execute(f"CREATE INDEX IF NOT EXISTS {index} ON {table} USING hnsw (embedding vector_cosine_ops);")
                print(f"✅ Successfully migrated {table}")
            except Exception as table_err:
                print(f"❌ Failed to migrate {table}: {table_err}")
                conn.rollback()
                continue
                
        conn.commit()
        cur.close()
        conn.close()
        print("🎉 Migration completed successfully.")
    except Exception as e:
        print(f"💥 Migration failed: {e}")

if __name__ == "__main__":
    run_migration()
