import json
import subprocess

def get_sql_output(query):
    cmd = ["sudo", "-u", "postgres", "psql", "-d", "vfl_empire", "-t", "-A", "-c", query]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip().split('\n')

def get_snapshot_signature(season_id, md_number):
    query = f"""
    SELECT team_name, points, goals_for, goals_against
    FROM vfl_league_snapshots
    WHERE matchday_id = (SELECT id FROM vfl_matchdays WHERE season_id = {season_id} AND matchday_number = {md_number})
    ORDER BY team_name;
    """
    rows = get_sql_output(query)
    if not rows or not rows[0]: return None
    return tuple(rows)

def find_snapshot_clone(target_season_name, md_number):
    # 1. Get Target Signature
    tid_query = f"SELECT id FROM vfl_seasons WHERE season_name = '{target_season_name}';"
    tid = get_sql_output(tid_query)[0]
    target_sig = get_snapshot_signature(tid, md_number)
    
    if not target_sig:
        return f"No snapshot found for {target_season_name} MD {md_number}"
    
    # 2. Iterate all other seasons at the same MD
    all_seasons_query = f"SELECT id, season_name FROM vfl_seasons WHERE season_name != '{target_season_name}';"
    all_seasons = get_sql_output(all_seasons_query)
    
    matches = []
    for row in all_seasons:
        if not row: continue
        sid, sname = row.split("|")
        sig = get_snapshot_signature(sid, md_number)
        if sig == target_sig:
            matches.append(sname)
            
    return matches

if __name__ == "__main__":
    # Check current season VFLM 5147 at MD 22 (latest available)
    md = 22
    matches = find_snapshot_clone("VFLM 5147", md)
    print(f"Searching for Seasons that had the EXACT same league table as VFLM 5147 at MD {md}:")
    if isinstance(matches, str):
        print(matches)
    elif not matches:
        print("No exact league table matches found in history.")
    else:
        print(f"Found CLONE seasons: {matches}")
