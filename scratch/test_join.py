import sys
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db

with get_db() as cur:
    print("Engine counts and settled counts:")
    cur.execute("""
        SELECT engine, COUNT(*), SUM(settled), SUM(CASE WHEN settled=1 THEN profit ELSE 0 END) 
        FROM vfl_predictions 
        GROUP BY engine
        ORDER BY COUNT(*) DESC
    """)
    for r in cur.fetchall():
        print(f"  - Engine: {r[0]}, Total: {r[1]}, Settled: {r[2]}, Total Profit: {r[3]}")
        
    print("\nSample markets in predictions:")
    cur.execute("SELECT prediction, COUNT(*) FROM vfl_predictions GROUP BY prediction ORDER BY COUNT(*) DESC LIMIT 10")
    for r in cur.fetchall():
        print(f"  - Market: {r[0]}, Count: {r[1]}")


