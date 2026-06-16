import sys
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db

def inspect():
    with get_db() as cur:
        # Get list of tables
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        tables = [r[0] for r in cur.fetchall()]
        print("Tables in vfl_empire:")
        for t in tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            count = cur.fetchone()[0]
            print(f"  - {t}: {count} rows")
            
            # Show first 3 columns
            cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{t}' LIMIT 5")
            cols = cur.fetchall()
            col_desc = ", ".join([f"{c[0]} ({c[1]})" for c in cols])
            print(f"    Columns (first 5): {col_desc}")

if __name__ == "__main__":
    inspect()
