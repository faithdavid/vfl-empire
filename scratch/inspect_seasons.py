import sys
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db

with get_db() as cur:
    cur.execute("""
        SELECT s.season_name, COUNT(*)
        FROM vfl_results_v2 r
        JOIN vfl_matchdays m ON r.matchday_id = m.id
        JOIN vfl_seasons s ON m.season_id = s.id
        GROUP BY s.season_name
        ORDER BY s.season_name ASC
        LIMIT 20
    """)
    print("First 20 seasons in database:")
    for r in cur.fetchall():
        print(f"  - {r[0]}: {r[1]} matches")
        
    cur.execute("""
        SELECT s.season_name, COUNT(*)
        FROM vfl_results_v2 r
        JOIN vfl_matchdays m ON r.matchday_id = m.id
        JOIN vfl_seasons s ON m.season_id = s.id
        GROUP BY s.season_name
        ORDER BY s.season_name DESC
        LIMIT 20
    """)
    print("\nLast 20 seasons in database:")
    for r in cur.fetchall():
        print(f"  - {r[0]}: {r[1]} matches")
