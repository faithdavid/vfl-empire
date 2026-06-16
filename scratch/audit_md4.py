import json
from collections import defaultdict

def find_md_specific_locks(target_md):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    # Target MD 4 fixtures for Season 5148
    targets = [
        ("Wolverhampton", "London Guns"),
        ("Manchester Blue", "Newcastle"),
        ("Manchester Red", "Chelsea"),
        ("Leeds", "West Ham"),
        ("Everton", "Tottenham"),
        ("Fulham", "Liverpool"),
        ("Crystal Palace", "Brighton"),
        ("Aston Villa", "Bournemouth")
    ]
    
    results = defaultdict(list)
    
    for s_name, seasons in data.items():
        if s_name in ["VFLM 5147", "VFLM 5148"]: continue
        
        fixes = seasons.get(str(target_md))
        if not fixes: continue
        
        for fx in fixes:
            teams = tuple(sorted(fx["teams"].split(" vs ")))
            for t_home, t_away in targets:
                target_pair = tuple(sorted([t_home, t_away]))
                if teams == target_pair:
                    hg, ag = map(int, fx["result"].split("-"))
                    total = hg + ag
                    winner = "H" if hg > ag else "A" if ag > hg else "D"
                    teams_in_fix = fx["teams"].split(" vs ")
                    if teams_in_fix[0] != t_home:
                        if winner == "H": winner = "A"
                        elif winner == "A": winner = "H"
                        
                    results[(t_home, t_away)].append({
                        "total": total,
                        "winner": winner,
                        "u25": total < 2.5,
                        "o15": total > 1.5,
                        "u35": total < 3.5
                    })
                        
    return results

if __name__ == "__main__":
    locks = find_md_specific_locks(4)
    print("=== MD 4 HISTORICAL PERFORMANCE (FIXTURE + MD SPECIFIC) ===")
    for (h, a), samples in locks.items():
        if not samples: continue
        n = len(samples)
        u35_rate = sum(1 for s in samples if s["u35"]) / n
        o15_rate = sum(1 for s in samples if s["o15"]) / n
        u25_rate = sum(1 for s in samples if s["u25"]) / n
        h_win = sum(1 for s in samples if s["winner"] == "H") / n
        a_win = sum(1 for s in samples if s["winner"] == "A") / n
        
        if u35_rate > 0.85 or o15_rate > 0.85 or h_win > 0.65 or a_win > 0.65:
            print(f"\n{h} vs {a} (N={n})")
            if u35_rate > 0.85: print(f"  [LOCK] Under 3.5: {u35_rate:.2%}")
            if o15_rate > 0.85: print(f"  [LOCK] Over 1.5: {o15_rate:.2%}")
            if h_win > 0.65: print(f"  [LOCK] Home Win: {h_win:.2%}")
            if a_win > 0.65: print(f"  [LOCK] Away Win: {a_win:.2%}")
            print(f"  U2.5: {u25_rate:.2%}")
