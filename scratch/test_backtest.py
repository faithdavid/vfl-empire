import sys
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/services")
from common.db_manager import get_db
import pandas as pd

with get_db() as conn:
    print("Fetching vfl_predictions count...")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM vfl_predictions;")
    print("Predictions count:", cur.fetchone()['count'])
    
    print("Sample prediction:")
    cur.execute("SELECT * FROM vfl_predictions ORDER BY iso_time DESC LIMIT 1;")
    print(dict(cur.fetchone() or {}))
