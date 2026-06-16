import sys
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/services")
from common.db_manager import get_db

with get_db() as cur:
    cur.execute("SELECT COUNT(*) FROM vfl_predictions;")
    count = cur.fetchone()[0]
    
    cur.execute("SELECT * FROM vfl_predictions ORDER BY iso_time DESC LIMIT 5;")
    rows = cur.fetchall()
    
    print(f"Total predictions: {count}")
    print("Latest 5:")
    for r in rows:
        print(r)
