import json
import subprocess
from collections import defaultdict

def get_sql_output(query):
    cmd = ["sudo", "-u", "postgres", "psql", "-d", "vfl_empire", "-t", "-A", "-c", query]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip().split('\n')

def find_fixture_sequence_match(target_team, up_to_md, length=6):
    # 1. Get target team's fixture sequence in VFLM 5147 from DB
    query = f"""
    SELECT r.home_team, r.away_team
    FROM vfl_results_v2 r
    JOIN vfl_matchdays m ON r.matchday_id = m.id
    JOIN vfl_seasons s ON m.season_id = s.id
    WHERE s.season_name = 'VFLM 5147' AND m.matchday_number BETWEEN {up_to_md - length + 1} AND {up_to_md}
    ORDER BY m.matchday_number;
    """
    rows = get_sql_output(query)
    target_seq = []
    for row in rows:
        if not row: continue
        home, away = row.split("|")
        opp = away if home == target_team else home
        target_seq.append(opp)
    
    if len(target_seq) < length:
        return f"Insufficient data in DB for {target_team} up to MD {up_to_md}. Found: {target_seq}"

    print(f"Searching for {target_team} fixture sequence: {target_seq}")
    
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    matches = []
    # 2. Search other seasons in JSON
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        
        opponents = []
        md_keys = sorted(seasons.keys(), key=lambda x: int(x))
        for k in md_keys:
            fixes = seasons[k]
            for fx in fixes:
                if target_team in fx["teams"]:
                    teams = fx["teams"].split(" vs ")
                    opp = teams[1] if teams[0] == target_team else teams[0]
                    opponents.append((k, opp))
        
        for i in range(len(opponents) - length + 1):
            window = [o[1] for o in opponents[i:i+length]]
            if window == target_seq:
                matches.append({
                    "season": s_name,
                    "md_start": opponents[i][0],
                    "md_end": opponents[i+length-1][0]
                })
                
    return matches

if __name__ == "__main__":
    team = "Leeds"
    md = 23
    matches = find_fixture_sequence_match(team, md)
    
    if isinstance(matches, str):
        print(matches)
    elif not matches:
        print(f"No identical fixture sequence found for {team}.")
    else:
        print(f"Found {len(matches)} historical matches where {team} had the SAME fixture sequence:")
        for m in matches:
            print(f"  - {m['season']} Matchdays {m['md_start']} to {m['md_end']}")
