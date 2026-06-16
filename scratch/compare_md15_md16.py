import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire')

try:
    from services.common.db_manager import get_db
    with get_db() as cur:
        # Get MD 15
        cur.execute("SELECT team_name, points, goals_for, goals_against FROM vfl_league_snapshots WHERE played = 15 ORDER BY id DESC LIMIT 16;")
        md15 = {row[0]: {'pts': row[1], 'gf': row[2], 'ga': row[3]} for row in cur.fetchall()}
        
        # Get MD 16
        cur.execute("SELECT team_name, points, goals_for, goals_against FROM vfl_league_snapshots WHERE played = 16 ORDER BY id DESC LIMIT 16;")
        md16 = {row[0]: {'pts': row[1], 'gf': row[2], 'ga': row[3]} for row in cur.fetchall()}
        
        print("--- ACTUAL MATCHDAY 16 RESULTS ---")
        for team in md15.keys():
            if team not in md16: continue
            diff_pts = md16[team]['pts'] - md15[team]['pts']
            diff_gf = md16[team]['gf'] - md15[team]['gf']
            diff_ga = md16[team]['ga'] - md15[team]['ga']
            
            res = "Draw"
            if diff_pts == 3: res = "Win"
            elif diff_pts == 0: res = "Loss"
            
            print(f"{team}: {res} (Scored: {diff_gf}, Conceded: {diff_ga})")

except Exception as e:
    print(f"Error: {e}")
