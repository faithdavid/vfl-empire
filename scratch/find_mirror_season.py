import json

def find_mirror_season(md, fixtures):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    match_fixtures = set(fixtures)
    
    matches = []
    for s_name, seasons in data.items():
        if str(md) in seasons:
            mirror_fixtures = set(fix["teams"] for fix in seasons[str(md)])
            if match_fixtures.issubset(mirror_fixtures) or mirror_fixtures.issubset(match_fixtures):
                matches.append(s_name)
            else:
                # Try partial match (e.g. 5 out of 8)
                common = match_fixtures.intersection(mirror_fixtures)
                if len(common) >= 4:
                    matches.append((s_name, len(common)))
                    
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
    matches = find_mirror_season(23, current_fixtures)
    print(json.dumps(matches, indent=2))
