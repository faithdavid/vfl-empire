import json

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def find_md_match(fixtures):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    target = set(normalize_fixture(f) for f in fixtures)
    matches = []
    
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            current = set(normalize_fixture(f["teams"]) for f in fixes)
            if target == current:
                matches.append({"season": s_name, "md": md})
                
    return matches

if __name__ == "__main__":
    fixtures_20 = [
        "Everton vs West Ham",
        "London Guns vs Brighton",
        "Manchester Red vs Crystal Palace",
        "Manchester Blue vs Newcastle",
        "Aston Villa vs Chelsea",
        "Fulham vs Liverpool",
        "Wolverhampton vs Leeds",
        "Tottenham vs Bournemouth"
    ]
    matches = find_md_match(fixtures_20)
    print(json.dumps(matches, indent=2))
