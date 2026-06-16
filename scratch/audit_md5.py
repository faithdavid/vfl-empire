import json
from collections import defaultdict

def find_md_specific_locks(target_md):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    # MD 6 fixtures
    targets = [
        ("Fulham", "Tottenham"),
        ("Aston Villa", "Liverpool"),
        ("Crystal Palace", "London Guns"),
        ("Manchester Red", "Manchester Blue"),
        ("Wolverhampton", "Chelsea"),
        ("West Ham", "Brighton"),
        ("Leeds", "Bournemouth"),
        ("Everton", "Newcastle")
    ]
    
    results = defaultdict(list)
    for s_name, seasons in data.items():
        fixes = seasons.get(str(target_md))
        if not fixes: continue
        for fx in fixes:
            teams = tuple(sorted(fx["teams"].split(" vs ")))
            for t_home, t_away in targets:
                target_pair = tuple(sorted([t_home, t_away]))
                if teams == target_pair:
                    hg, ag = map(int, fx["result"].split("-"))
                    total = hg + ag
                    results[(t_home, t_away)].append(total)
                        
    return results

if __name__ == "__main__":
    locks = find_md_specific_locks(6)
    print("=== MD 5 HISTORICAL STABILITY ===")
    for (h, a), totals in locks.items():
        if not totals: continue
        n = len(totals)
        u35 = sum(1 for t in totals if t < 3.5) / n
        u25 = sum(1 for t in totals if t < 2.5) / n
        o15 = sum(1 for t in totals if t > 1.5) / n
        
        print(f"\n{h} vs {a} (N={n})")
        print(f"  U3.5: {u35:.2%}")
        print(f"  O1.5: {o15:.2%}")
        if u35 > 0.90: print(f"  [HIGH STABILITY] U3.5")
        if o15 > 0.90: print(f"  [HIGH STABILITY] O1.5")
