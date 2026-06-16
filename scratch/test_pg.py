import sys
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/services")
from common.db_manager import get_db

with get_db() as cur:
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='v_results_odd_even_ready';")
    print([r[0] for r in cur.fetchall()])
