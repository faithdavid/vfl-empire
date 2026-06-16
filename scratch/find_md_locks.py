import json
from collections import defaultdict

def find_md_locks(md_num):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    fixtures = defaultdict(lambda: {"hits_o15": 0, "hits_u35": 0, "total": 0})
    
    for s_name, seasons in data.items():
        if str(md_num) in seasons:
            for fix in seasons[str(md_num)]:
                key = fix["teams"]
                fixtures[key]["total"] += 1
                if fix["total"] > 1:
                    fixtures[key]["hits_o15"] += 1
                if fix["total"] < 4:
                    fixtures[key]["hits_u35"] += 1
    
    locks = []
    for teams, stats in fixtures.items():
        if stats["total"] >= 5:
            p_o15 = stats["hits_o15"] / stats["total"]
            p_u35 = stats["hits_u35"] / stats["total"]
            
            if p_o15 == 1.0:
                locks.append({"teams": teams, "market": "Over 1.5 Goals", "n": stats["total"]})
            elif p_u35 == 1.0:
                locks.append({"teams": teams, "market": "Under 3.5 Goals", "n": stats["total"]})
                
    return locks

if __name__ == "__main__":
    import sys
    md_num = int(sys.argv[1]) if len(sys.argv) > 1 else 17
    locks = find_md_locks(md_num)
    print(json.dumps(locks, indent=2))
