import sys
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db

with get_db() as cur:
    cur.execute("SELECT COUNT(*) FROM vfl_bets")
    print(f"Total bets in vfl_bets: {cur.fetchone()[0]}")
    
    cur.execute("SELECT * FROM vfl_bets ORDER BY id DESC LIMIT 5")
    rows = cur.fetchall()
    print("Sample bets:")
    for r in rows:
        print(f"  {dict(r) if hasattr(r, 'keys') else r}")
        
    cur.execute("SELECT market, COUNT(*), SUM(CASE WHEN status='WON' THEN 1 ELSE 0 END) FROM vfl_bets GROUP BY market")
    print("\nBets by market:")
    for r in cur.fetchall():
        print(f"  - Market: {r[0]}, Count: {r[1]}, Won: {r[2]}")
