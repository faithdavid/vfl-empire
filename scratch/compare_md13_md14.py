import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire')

try:
    from services.common.db_manager import get_db
    with get_db() as cur:
        # Get MD 13
        cur.execute("SELECT team_name, points, goals_for, goals_against FROM vfl_league_snapshots WHERE played = 13 ORDER BY id DESC LIMIT 16;")
        md13 = {row[0]: {'pts': row[1], 'gf': row[2], 'ga': row[3]} for row in cur.fetchall()}
        
        # Get MD 14
        cur.execute("SELECT team_name, points, goals_for, goals_against FROM vfl_league_snapshots WHERE played = 14 ORDER BY id DESC LIMIT 16;")
        md14 = {row[0]: {'pts': row[1], 'gf': row[2], 'ga': row[3]} for row in cur.fetchall()}
        
        print("--- ACTUAL MATCHDAY 14 RESULTS ---")
        for team in md13.keys():
            if team not in md14: continue
            diff_pts = md14[team]['pts'] - md13[team]['pts']
            diff_gf = md14[team]['gf'] - md13[team]['gf']
            diff_ga = md14[team]['ga'] - md13[team]['ga']
            
            res = "Draw"
            if diff_pts == 3: res = "Win"
            elif diff_pts == 0: res = "Loss"
            
            print(f"{team}: {res} (Scored: {diff_gf}, Conceded: {diff_ga})")

except Exception as e:
    print(f"Error: {e}")
