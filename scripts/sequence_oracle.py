import json
import os
import sys
from collections import deque
from pathlib import Path

# Paths
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
MASTER_INDEX = BASE_DIR / "master_mirror_index.json"

def get_team_sequence(season_data, team_name, up_to_md):
    """
    Extracts the sequence of results for a team in a season up to a specific matchday.
    Returns a list of result codes (W, D, L) or goal counts.
    """
    seq = []
    # matchdays are keys "1", "2", ... in season_data
    for md in range(1, up_to_md + 1):
        md_str = str(md)
        if md_str not in season_data:
            continue
        
        found = False
        for fixture in season_data[md_str]:
            teams = fixture["teams"].split(" vs ")
            if team_name in teams:
                res = fixture["result"] # e.g. "2-1"
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
                except:
                    pass
                break
        if not found:
            # Maybe the team didn't play or data missing
            pass
    return seq[-5:] # Last 5

def find_sequence_clones(current_home, current_away, current_home_seq, current_away_seq):
    """
    Searches historical data for cases where two teams (not necessarily the same ones)
    had the exact same 5-match sequences leading up to their meeting.
    """
    with open(MASTER_INDEX) as f:
        master_data = json.load(f)
    
    matches = []
    
    for season_name, season_data in master_data.items():
        # Iterate from MD 6 to 38
        for md in range(6, 39):
            md_str = str(md)
            if md_str not in season_data: continue
            
            for fixture in season_data[md_str]:
                f_teams = fixture["teams"].split(" vs ")
                f_home, f_away = f_teams[0], f_teams[1]
                
                # Get their sequences up to MD-1
                h_seq = get_team_sequence(season_data, f_home, md - 1)
                a_seq = get_team_sequence(season_data, f_away, md - 1)
                
                # Match against current sequences
                if h_seq == current_home_seq and a_seq == current_away_seq:
                    matches.append({
                        "season": season_name,
                        "matchday": md,
                        "home": f_home,
                        "away": f_away,
                        "result": fixture["result"],
                        "total_goals": sum(map(int, fixture["result"].split("-")))
                    })
                # Also check inverted (maybe it's a mirror)
                elif h_seq == current_away_seq and a_seq == current_home_seq:
                    matches.append({
                        "season": season_name,
                        "matchday": md,
                        "home": f_home,
                        "away": f_away,
                        "result": fixture["result"],
                        "total_goals": sum(map(int, fixture["result"].split("-"))),
                        "inverted": True
                    })
                    
    return matches

if __name__ == "__main__":
    # Example test
    h_seq = ["W", "D", "L", "W", "L"]
    a_seq = ["L", "L", "W", "D", "W"]
    print(f"Searching for clones of Home:{h_seq} Away:{a_seq}...")
    clones = find_sequence_clones("Leeds", "Chelsea", h_seq, a_seq)
    print(f"Found {len(clones)} clones.")
    for c in clones[:5]:
        print(c)
