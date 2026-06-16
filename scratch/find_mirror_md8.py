import json

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def find_mirror_md8(fixtures):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    target = set(normalize_fixture(f) for f in fixtures)
    matches = []
    
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        if "8" in seasons:
            current = set(normalize_fixture(f["teams"]) for f in seasons["8"])
            if target == current:
                matches.append(s_name)
                
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
    matches = find_mirror_md8(current_fixtures)
    print(json.dumps(matches, indent=2))
