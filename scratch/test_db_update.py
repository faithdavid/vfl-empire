import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services"))
from common.db_manager import get_db

print("Starting DB update test...")
try:
    with get_db() as cur:
        cur.execute("SELECT id, settled FROM vfl_predictions WHERE settled = 0 LIMIT 1")
        row = cur.fetchone()
        if row:
            pred_id = row[0]
            print(f"Updating row ID {pred_id}...")
            cur.execute("UPDATE vfl_predictions SET settled = 1 WHERE id = %s", (pred_id,))
            print("Update executed.")
        else:
            print("No rows found where settled = 0")
except Exception as e:
    print(f"Error during update: {e}")

print("Verifying...")
with get_db() as cur:
    cur.execute("SELECT settled FROM vfl_predictions WHERE settled = 1 LIMIT 5")
    rows = cur.fetchall()
    print("Settled = 1 rows:", rows)
