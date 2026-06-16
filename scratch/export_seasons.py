import subprocess
import os

def export_season_data(season_name):
    # Get Season ID
    cmd_id = ["sudo", "-u", "postgres", "psql", "-d", "vfl_empire", "-t", "-A", "-c", f"SELECT id FROM vfl_seasons WHERE season_name = '{season_name}';"]
    sid = subprocess.run(cmd_id, capture_output=True, text=True).stdout.strip()
    if not sid: return
    
    # Export Results + Odds to CSV
    export_query = f"""
    COPY (
        SELECT 
            m.matchday_number,
            r.home_team,
            r.away_team,
            r.home_goals,
            r.away_goals,
            o.o15,
            o.o25,
            o.u35,
            o.gg,
            o.ng
        FROM vfl_results_v2 r
        JOIN vfl_matchdays m ON r.matchday_id = m.id
        LEFT JOIN vfl_odds_v2 o ON r.event_id = o.event_id
        WHERE m.season_id = {sid}
        ORDER BY m.matchday_number
    ) TO '/tmp/season_{sid}_results.csv' WITH CSV HEADER;
    """
    subprocess.run(["sudo", "-u", "postgres", "psql", "-d", "vfl_empire", "-c", export_query])
    
    # Move from /tmp to workspace
    clean_name = season_name.replace(" ", "_")
    target_path = f"/home/ubuntu/faith-workspace/vfl-empire/data/seasons/{clean_name}_results.csv"
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    subprocess.run(["sudo", "mv", f"/tmp/season_{sid}_results.csv", target_path])
    subprocess.run(["sudo", "chown", "ubuntu:ubuntu", target_path])
    print(f"Exported {target_path}")

if __name__ == "__main__":
    # Export a few recent seasons
    seasons = ["VFLM 5146", "VFLM 5145", "VFLM 5144", "VFLM 5143"]
    for s in seasons:
        export_season_data(s)
