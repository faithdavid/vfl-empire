import json
from collections import defaultdict

def analyze_elite_teams():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    elite_teams = ["Manchester Blue", "Manchester Red", "London Guns"]
    
    # Track how many times a 100% lock for these teams existed and if it hit across seasons
    # But wait, the mirror index IS the history. 
    # Let's check if any 100% lock (n >= 5) actually FAILED in any season.
    # This would mean it wasn't a 100% lock in the first place?
    # No, we want to see if the "blueprint" ever drifts.
    
    results = []
    
    for s_name, seasons in data.items():
        for md_num, fixtures in seasons.items():
            for fix in fixtures:
                teams = fix["teams"]
                if any(t in teams for t in elite_teams):
                    # We need to know if it was a lock BEFORE this season.
                    # That's hard with current data structure.
                    pass

    # Alternative: Find fixtures for these teams that have high n and 100% hit rate.
    stats = defaultdict(lambda: {"o15": 0, "u35": 0, "total": 0})
    for s_name, seasons in data.items():
        for md_num, fixtures in seasons.items():
            for fix in fixtures:
                key = (fix["teams"], md_num)
                if any(t in key[0] for t in elite_teams):
                    stats[key]["total"] += 1
                    if fix["total"] > 1: stats[key]["o15"] += 1
                    if fix["total"] < 4: stats[key]["u35"] += 1
                    
    elite_locks = []
    for (teams, md), s in stats.items():
        if s["total"] >= 10: # High confidence
            if s["o15"] == s["total"]:
                elite_locks.append({"teams": teams, "md": md, "market": "O1.5", "n": s["total"]})
            if s["u35"] == s["total"]:
                elite_locks.append({"teams": teams, "md": md, "market": "U3.5", "n": s["total"]})
                
    return sorted(elite_locks, key=lambda x: int(x["md"]))

if __name__ == "__main__":
    locks = analyze_elite_teams()
    print(json.dumps(locks, indent=2))
