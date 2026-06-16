import json
import subprocess

def get_sql_output(query):
    cmd = ["sudo", "-u", "postgres", "psql", "-d", "vfl_empire", "-t", "-A", "-c", query]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip().split('\n')

def extract_season_snapshot(season_name):
    print(f"Extracting data for {season_name}...")
    
    # 1. Get Season ID
    season_id_rows = get_sql_output(f"SELECT id FROM vfl_seasons WHERE season_name = '{season_name}';")
    if not season_id_rows or not season_id_rows[0]:
        return "Season not found"
    season_id = season_id_rows[0]
    
    # 2. Extract Results with Odds
    results_query = f"""
    SELECT 
        m.matchday_number,
        r.home_team,
        r.away_team,
        r.home_goals,
        r.away_goals,
        o.over_1_5,
        o.over_2_5,
        o.over_3_5,
        o.home_win,
        o.draw,
        o.away_win
    FROM vfl_results_v2 r
    JOIN vfl_matchdays m ON r.matchday_id = m.id
    LEFT JOIN vfl_odds_v2 o ON r.id = o.result_id
    WHERE m.season_id = {season_id}
    ORDER BY m.matchday_number, r.id;
    """
    results_data = get_sql_output(results_query)
    
    # 3. Extract League Table (Snapshots) for MD 38 (Final)
    snapshots_query = f"""
    SELECT 
        team_name, position, played, won, drawn, lost, goals_for, goals_against, points
    FROM vfl_league_snapshots
    WHERE matchday_id = (SELECT id FROM vfl_matchdays WHERE season_id = {season_id} AND matchday_number = 38)
    ORDER BY position;
    """
    snapshots_data = get_sql_output(snapshots_query)
    
    return {
        "season": season_name,
        "results_count": len(results_data),
        "table_count": len(snapshots_data),
        "sample_results": results_data[:5],
        "final_table": snapshots_data
    }

if __name__ == "__main__":
    # Test with a recent complete season
    report = extract_season_snapshot("VFLM 5146")
    with open('/home/ubuntu/faith-workspace/vfl-empire/scratch/season_data_sample.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("Report generated in scratch/season_data_sample.json")
