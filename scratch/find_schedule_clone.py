import json
import subprocess

def get_sql_output(query):
    cmd = ["sudo", "-u", "postgres", "psql", "-d", "vfl_empire", "-t", "-A", "-c", query]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip().split('\n')

def get_md_signature(season_name, md_number):
    query = f"""
    SELECT r.home_team, r.away_team
    FROM vfl_results_v2 r
    JOIN vfl_matchdays m ON r.matchday_id = m.id
    JOIN vfl_seasons s ON m.season_id = s.id
    WHERE s.season_name = '{season_name}' AND m.matchday_number = {md_number}
    ORDER BY r.home_team;
    """
    rows = get_sql_output(query)
    if not rows or not rows[0]: return None
    return tuple(sorted(rows))

def find_season_schedule_match():
    # 1. Get current season's first 5 MDs (available in JSON for easy comparison)
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    target_season = data.get("VFLM 5147")
    if not target_season: return "VFLM 5147 not in JSON"
    
    def get_json_sig(md_data):
        fixes = [tuple(sorted(fx["teams"].split(" vs "))) for fx in md_data]
        return frozenset(fixes)

    target_sigs = [get_json_sig(target_season[str(m)]) for m in range(1, 6)]
    
    matches = []
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        
        # Check all possible start points in this season
        md_keys = sorted(seasons.keys(), key=lambda x: int(x))
        if len(md_keys) < 5: continue
        
        all_sigs = {int(k): get_json_sig(seasons[k]) for k in md_keys}
        
        for start_md in md_keys:
            start_md = int(start_md)
            if all(all_sigs.get(start_md + i) == target_sigs[i] for i in range(5)):
                matches.append((s_name, start_md))
                
    return matches

if __name__ == "__main__":
    matches = find_season_schedule_match()
    print("Searching for Season Schedule Clone (MD 1-5 Match):")
    if isinstance(matches, str):
        print(matches)
    elif not matches:
        print("No identical 5-MD schedule sequences found.")
    else:
        print(f"FOUND {len(matches)} SCHEDULE CLONES:")
        for s, md in matches:
            print(f"  - {s} starting at MD {md}")
