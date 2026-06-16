import sys
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/services")
from common.db_manager import get_db

with get_db() as cur:
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")
    tables = [r[0] for r in cur.fetchall()]
    print(tables)
