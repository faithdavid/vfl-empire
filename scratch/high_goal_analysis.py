import json
import subprocess

def get_sql_output(query):
    cmd = ["sudo", "-u", "postgres", "psql", "-d", "vfl_empire", "-t", "-A", "-F", ",", "-c", query]
    res = subprocess.run(cmd, capture_output=True, text=True)
    lines = res.stdout.strip().split('\n')
    return [line.split(',') for line in lines if line]

def analyze_high_goal_pairs():
    # Find fixture pairs with >90% Over 1.5 in history
    query = """
    SELECT 
        home_team, 
        away_team, 
        COUNT(*) as total,
        SUM(CASE WHEN (home_goals + away_goals) >= 2 THEN 1 ELSE 0 END) as o15_wins
    FROM vfl_results_v2
    GROUP BY home_team, away_team
    HAVING COUNT(*) > 50
    ORDER BY (CAST(SUM(CASE WHEN (home_goals + away_goals) >= 2 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*)) DESC
    LIMIT 20;
    """
    rows = get_sql_output(query)
    
    locks = []
    for row in rows:
        if len(row) < 4: continue
        home, away, total, o15 = row
        rate = int(o15) / int(total)
        if rate > 0.85:
            locks.append({
                "fixture": f"{home} vs {away}",
                "rate": round(rate * 100, 2),
                "total": int(total)
            })
    return locks

def get_season_overview(season_name):
    query_id = f"SELECT id FROM vfl_seasons WHERE season_name = '{season_name}';"
    sid_rows = get_sql_output(query_id)
    if not sid_rows: return "Season not found"
    sid = sid_rows[0][0]
    
    # Final Table
    query_table = f"""
    SELECT team_name, position, points, goals_for, goals_against
    FROM vfl_league_snapshots
    WHERE matchday_id = (SELECT MAX(id) FROM vfl_matchdays WHERE season_id = {sid})
    ORDER BY position;
    """
    table = get_sql_output(query_table)
    
    return {
        "season": season_name,
        "top_3": table[:3],
        "bottom_3": table[-3:]
    }

if __name__ == "__main__":
    locks = analyze_high_goal_pairs()
    overview = get_season_overview("VFLM 5146")
    
    report = {
        "high_goal_safely_locks": locks,
        "season_5146_overview": overview
    }
    
    print(json.dumps(report, indent=2))
