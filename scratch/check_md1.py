import json

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def get_signature(fixtures):
    return frozenset([normalize_fixture(f) for f in fixtures])

def check_single_md():
    # VFLM 5147 MD 1
    target = get_signature([
        "Brighton vs Leeds",
        "Aston Villa vs Everton",
        "West Ham vs Tottenham",
        "Chelsea vs Fulham",
        "Manchester Red vs London Guns",
        "Crystal Palace vs Manchester Blue",
        "Liverpool vs Wolverhampton",
        "Newcastle vs Bournemouth"
    ])
    
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
        
    found = []
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        for md, fixes in seasons.items():
            sig = get_signature([fx["teams"] for fx in fixes])
            if target == sig:
                found.append((s_name, md))
                
    return found

if __name__ == "__main__":
    found = check_single_md()
    if found:
        print(f"Match found in: {found}")
    else:
        print("MD 1 of 5147 never occurred in the 126-season history.")
