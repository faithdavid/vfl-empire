import json

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def get_signature(fixtures):
    return frozenset([normalize_fixture(f) for f in fixtures])

def find_twin_sequence():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    # 1. Get current season progression (VFLM 5147)
    current_season = data.get("VFLM 5147")
    if not current_season:
        return "VFLM 5147 not found in data"
    
    current_progression = []
    for md in range(1, 23): # We have data up to MD 22/23
        md_str = str(md)
        if md_str in current_season:
            current_progression.append(get_signature([fx["teams"] for fx in current_season[md_str]]))
        else:
            break
            
    print(f"Current Season (5147) has {len(current_progression)} matchdays recorded.")
    
    matches = []
    
    # 2. Iterate through all other seasons
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        
        # Get all signatures for this season in order
        md_keys = sorted(seasons.keys(), key=lambda x: int(x))
        season_sigs = [get_signature([fx["teams"] for fx in seasons[k]]) for k in md_keys]
        
        # 3. Look for the current progression sequence within this season
        for i in range(len(season_sigs) - len(current_progression) + 1):
            is_match = True
            for j in range(len(current_progression)):
                if current_progression[j] != season_sigs[i+j]:
                    is_match = False
                    break
            if is_match:
                matches.append({
                    "target_season": s_name,
                    "start_md": md_keys[i],
                    "offset": i
                })
                
    return matches

if __name__ == "__main__":
    matches = find_twin_sequence()
    if isinstance(matches, str):
        print(matches)
    elif not matches:
        print("No twin sequences found in history.")
    else:
        print(f"Found {len(matches)} twin sequences:")
        print(json.dumps(matches, indent=2))
