import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services"))
from common.db_manager import get_db

with get_db() as cur:
    cur.execute("SELECT settled, count(*) FROM vfl_predictions GROUP BY settled")
    print("Database State:")
    for row in cur.fetchall():
        print(f"  settled={row[0]}: {row[1]} rows")
