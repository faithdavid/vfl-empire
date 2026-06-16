import json

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def get_signature(fixtures):
    return frozenset([normalize_fixture(f) for f in fixtures])

if __name__ == "__main__":
    target = get_signature([
        "West Ham vs Crystal Palace",
        "Liverpool vs Everton",
        "Bournemouth vs London Guns",
        "Chelsea vs Wolverhampton",
        "Brighton vs Manchester Red",
        "Newcastle vs Aston Villa",
        "Leeds vs Manchester Blue",
        "Tottenham vs Fulham"
    ])
    
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
        
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        for md, fixes in seasons.items():
            if not fixes: continue
            sig = get_signature([fx["teams"] for fx in fixes])
            if target == sig:
                print(f"Match found in {s_name} Matchday {md}")
