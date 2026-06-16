import json
from collections import defaultdict

def find_draw_locks(md_num):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    fixtures = defaultdict(lambda: {"draws": 0, "total": 0})
    
    for s_name, seasons in data.items():
        if str(md_num) in seasons:
            for fix in seasons[str(md_num)]:
                key = fix["teams"]
                fixtures[key]["total"] += 1
                hg = fix.get("home_goals", int(fix["result"].split("-")[0]))
                ag = fix.get("away_goals", int(fix["result"].split("-")[1]))
                if hg == ag:
                    fixtures[key]["draws"] += 1
    
    locks = []
    for teams, stats in fixtures.items():
        if stats["total"] >= 5:
            p_draw = stats["draws"] / stats["total"]
            if p_draw >= 0.5: # 50% or more draw rate is extremely high for 1X2
                locks.append({"teams": teams, "draw_rate": p_draw, "n": stats["total"]})
                
    return sorted(locks, key=lambda x: x["draw_rate"], reverse=True)

if __name__ == "__main__":
    import sys
    md = int(sys.argv[1]) if len(sys.argv) > 1 else 23
    locks = find_draw_locks(md)
    print(json.dumps(locks, indent=2))
