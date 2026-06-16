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
            if target == current:
                matches.append({"season": s_name, "md": md})
                
    return matches

if __name__ == "__main__":
    fixtures_24 = [
        "London Guns vs Leeds",
        "Manchester Blue vs Tottenham",
        "Aston Villa vs Liverpool",
        "Chelsea vs West Ham",
        "Wolverhampton vs Fulham",
        "Crystal Palace vs Brighton",
        "Everton vs Bournemouth",
        "Manchester Red vs Newcastle"
    ]
    matches = find_single_md_match(fixtures_24)
    print(json.dumps(matches, indent=2))
