import json
from collections import defaultdict

def find_md_win_locks(md_num):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    fixtures = defaultdict(lambda: {"hw": 0, "aw": 0, "draw": 0, "total": 0})
    
    for s_name, seasons in data.items():
        if str(md_num) in seasons:
            for fix in seasons[str(md_num)]:
                key = fix["teams"]
                fixtures[key]["total"] += 1
                hg = fix["home_goals"] if "home_goals" in fix else int(fix["result"].split("-")[0])
                ag = fix["away_goals"] if "away_goals" in fix else int(fix["result"].split("-")[1])
                
                if hg > ag: fixtures[key]["hw"] += 1
                elif ag > hg: fixtures[key]["aw"] += 1
                else: fixtures[key]["draw"] += 1
    
    locks = []
    for teams, stats in fixtures.items():
        if stats["total"] >= 5:
            p_hw = stats["hw"] / stats["total"]
            p_aw = stats["aw"] / stats["total"]
            
            if p_hw == 1.0:
                locks.append({"teams": teams, "market": "Home Win", "n": stats["total"]})
            elif p_aw == 1.0:
                locks.append({"teams": teams, "market": "Away Win", "n": stats["total"]})
                
    return locks

if __name__ == "__main__":
    import sys
    md_num = int(sys.argv[1]) if len(sys.argv) > 1 else 17
    locks = find_md_win_locks(md_num)
    print(json.dumps(locks, indent=2))
