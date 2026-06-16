import json

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def find_single_md_match(fixtures):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    target = set(normalize_fixture(f) for f in fixtures)
    matches = []
    
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        for md, fixes in seasons.items():
            current = set(normalize_fixture(f["teams"]) for f in fixes)
            if target.issubset(current) or current.issubset(target):
                matches.append({"season": s_name, "md": md})
                
    return matches

if __name__ == "__main__":
    current_fixtures = [
        "West Ham vs Crystal Palace",
        "Liverpool vs Everton",
        "Bournemouth vs London Guns",
        "Chelsea vs Wolverhampton",
        "Brighton vs Manchester Red",
        "Newcastle vs Aston Villa",
        "Leeds vs Manchester Blue",
        "Tottenham vs Fulham"
    ]
    matches = find_single_md_match(current_fixtures)
    print(json.dumps(matches, indent=2))
