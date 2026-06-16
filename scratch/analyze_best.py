import json
from collections import defaultdict

def analyze_best_markets(fixtures):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    target_fixtures = set(fixtures)
    stats = defaultdict(lambda: {
        "o15": 0, "u35": 0, "hw": 0, "aw": 0, "draw": 0, "total": 0
    })
    
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            for fx in fixes:
                if fx["teams"] in target_fixtures:
                    s = stats[fx["teams"]]
                    s["total"] += 1
                    hg = fx.get("home_goals", int(fx["result"].split("-")[0]))
                    ag = fx.get("away_goals", int(fx["result"].split("-")[1]))
                    if (hg + ag) > 1: s["o15"] += 1
                    if (hg + ag) < 4: s["u35"] += 1
                    if hg > ag: s["hw"] += 1
                    if ag > hg: s["aw"] += 1
                    if hg == ag: s["draw"] += 1
                        
    results = []
    for t, s in stats.items():
        if s["total"] > 0:
            res = {
                "teams": t,
                "total": s["total"],
                "o15_rate": s["o15"]/s["total"],
                "u35_rate": s["u35"]/s["total"],
                "hw_rate": s["hw"]/s["total"],
                "aw_rate": s["aw"]/s["total"],
                "draw_rate": s["draw"]/s["total"]
            }
            results.append(res)
    return results

if __name__ == "__main__":
    fixtures = [
        "London Guns vs Leeds",
        "Manchester Blue vs Tottenham",
        "Aston Villa vs Liverpool",
        "Chelsea vs West Ham",
        "Wolverhampton vs Fulham",
        "Crystal Palace vs Brighton",
        "Everton vs Bournemouth",
        "Manchester Red vs Newcastle"
    ]
    res = analyze_best_markets(fixtures)
    print(json.dumps(res, indent=2))
