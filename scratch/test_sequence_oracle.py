import json
import os
import sys
from collections import deque
from pathlib import Path

# Paths
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
MASTER_INDEX = BASE_DIR / "master_mirror_index.json"

def get_team_sequence(season_data, team_name, up_to_md):
    seq = []
    for md in range(1, up_to_md + 1):
        md_str = str(md)
        if md_str not in season_data: continue
        found = False
        for fixture in season_data[md_str]:
            teams = fixture["teams"].split(" vs ")
            if team_name in teams:
                res = fixture["result"]
                try:
                    h_goals, a_goals = map(int, res.split("-"))
                    if team_name == teams[0]:
                        if h_goals > a_goals: seq.append("W")
                        elif h_goals < a_goals: seq.append("L")
                        else: seq.append("D")
                    else:
                        if a_goals > h_goals: seq.append("W")
                        elif a_goals < h_goals: seq.append("L")
                        else: seq.append("D")
                    found = True
                except: pass
                break
        if not found: pass
    return seq[-5:]

def find_sequence_clones(h_seq_target, a_seq_target):
    with open(MASTER_INDEX) as f:
        master_data = json.load(f)
    
    matches = []
    for season_name, season_data in master_data.items():
        for md in range(6, 39):
            md_str = str(md)
            if md_str not in season_data: continue
            for fixture in season_data[md_str]:
                f_teams = fixture["teams"].split(" vs ")
                f_home, f_away = f_teams[0], f_teams[1]
                h_seq = get_team_sequence(season_data, f_home, md - 1)
                a_seq = get_team_sequence(season_data, f_away, md - 1)
                
                if h_seq == h_seq_target and a_seq == a_seq_target:
                    matches.append({
                        "season": season_name,
                        "matchday": md,
                        "fixture": f"{f_home} vs {f_away}",
                        "result": fixture["result"]
                    })
    return matches

if __name__ == "__main__":
    h_seq = ["W", "W", "W", "D", "W"]
    a_seq = ["W", "D", "W", "L", "L"]
    clones = find_sequence_clones(h_seq, a_seq)
    print(json.dumps(clones, indent=2))
