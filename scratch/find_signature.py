import json
from collections import defaultdict

def find_signature_match(fixtures):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    target = set(fixtures)
    matches = []
    
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            current = set(f["teams"] for f in fixes)
            common = target.intersection(current)
            if len(common) >= 4:
                matches.append({"season": s_name, "md": md, "score": len(common), "fixtures": list(common)})
                
    return sorted(matches, key=lambda x: x["score"], reverse=True)

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
    matches = find_signature_match(current_fixtures)
    print(json.dumps(matches[:10], indent=2))
