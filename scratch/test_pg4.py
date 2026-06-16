import sys
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/services")
from common.db_manager import get_db
import pandas as pd

with get_db() as cur:
    cur.execute("SELECT season, COUNT(*) FROM vfl_predictions GROUP BY season;")
    rows = cur.fetchall()
    for r in rows:
        print(f"Season: {r[0]} - Rows: {r[1]}")
