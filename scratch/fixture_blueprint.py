import json
from collections import defaultdict

def find_fixture_blueprint(t1, t2):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    md_stats = defaultdict(lambda: {"o15": 0, "u35": 0, "hw": 0, "aw": 0, "total": 0})
    
    for s_name, seasons in data.items():
        for md, fixtures in seasons.items():
            for fix in fixtures:
                if fix["teams"] == f"{t1} vs {t2}":
                    stats = md_stats[md]
                    stats["total"] += 1
                    hg = fix.get("home_goals", int(fix["result"].split("-")[0]))
                    ag = fix.get("away_goals", int(fix["result"].split("-")[1]))
                    if (hg + ag) > 1: stats["o15"] += 1
                    if (hg + ag) < 4: stats["u35"] += 1
                    if hg > ag: stats["hw"] += 1
                    if ag > hg: stats["aw"] += 1
                    
    return md_stats

if __name__ == "__main__":
    blueprint = find_fixture_blueprint("London Guns", "Chelsea")
    for md, s in sorted(blueprint.items(), key=lambda x: int(x[0])):
        if s["total"] >= 5:
            print(f"MD {md}: total={s['total']}, o15_rate={s['o15']/s['total']:.2f}, u35_rate={s['u35']/s['total']:.2f}, hw_rate={s['hw']/s['total']:.2f}, aw_rate={s['aw']/s['total']:.2f}")
