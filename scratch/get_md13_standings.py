import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire')

try:
    from services.common.db_manager import get_db
    with get_db() as cur:
        cur.execute("""
            SELECT team_name, rank, points, won, draw, lost, goals_for, goals_against, goal_diff, form 
            FROM vfl_league_snapshots 
            WHERE played = 13
            ORDER BY id DESC
            LIMIT 16;
        """)
        rows = cur.fetchall()
        rows.sort(key=lambda x: x[1]) # Sort by rank ascending
        print("--- STANDINGS AFTER MD 13 (FROM POSTGRES) ---")
        for r in rows:
            print(f"Rank {r[1]}: {r[0]} | {r[2]} pts | W: {r[3]} D: {r[4]} L: {r[5]} | GF: {r[6]} GA: {r[7]} GD: {r[8]} | Form: {r[9]}")
except Exception as e:
    print(f"Error: {e}")
