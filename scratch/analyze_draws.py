import json
from collections import defaultdict

def analyze_draws(fixtures):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    target_fixtures = set(fixtures)
    stats = defaultdict(lambda: {"draws": 0, "total": 0})
    
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            for fx in fixes:
                if fx["teams"] in target_fixtures:
                    stats[fx["teams"]]["total"] += 1
                    hg = fx.get("home_goals", int(fx["result"].split("-")[0]))
                    ag = fx.get("away_goals", int(fx["result"].split("-")[1]))
                    if hg == ag:
                        stats[fx["teams"]]["draws"] += 1
                        
    results = []
    for t, s in stats.items():
        results.append({"teams": t, "draw_rate": s["draws"]/s["total"], "n": s["total"]})
    return sorted(results, key=lambda x: x["draw_rate"], reverse=True)

if __name__ == "__main__":
    fixtures = [
        "Tottenham vs London Guns",
        "West Ham vs Wolverhampton",
        "Liverpool vs Manchester Red",
        "Brighton vs Chelsea",
        "Fulham vs Manchester Blue",
        "Newcastle vs Crystal Palace",
        "Bournemouth vs Aston Villa",
        "Leeds vs Everton"
    ]
    print(json.dumps(analyze_draws(fixtures), indent=2))
