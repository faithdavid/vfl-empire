import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire')
from services.common.db_manager import get_db

try:
    with get_db() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'vfl_league_snapshots';")
        rows = cur.fetchall()
        print("Columns in vfl_league_snapshots:")
        print([r[0] for r in rows])
except Exception as e:
    print(f"Error: {e}")
