import json
from collections import defaultdict

def find_md2_locks():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    # Target MD 2 fixtures for Season 5148
    targets = [
        ("Newcastle", "Chelsea"),
        ("Fulham", "Bournemouth"),
        ("Wolverhampton", "Brighton"),
        ("Crystal Palace", "West Ham"),
        ("Manchester Red", "London Guns"),
        ("Manchester Blue", "Tottenham"),
        ("Everton", "Liverpool"),
        ("Leeds", "Aston Villa")
    ]
    
    results = defaultdict(list)
    
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147" or s_name == "VFLM 5148": continue
        
        for md, fixes in seasons.items():
            for fx in fixes:
                teams = tuple(sorted(fx["teams"].split(" vs ")))
                for t_home, t_away in targets:
                    target_pair = tuple(sorted([t_home, t_away]))
                    if teams == target_pair:
                        hg, ag = map(int, fx["result"].split("-"))
                        total = hg + ag
                        winner = "H" if hg > ag else "A" if ag > hg else "D"
                        # Adjust winner if target home/away is flipped
                        teams_in_fix = fx["teams"].split(" vs ")
                        if teams_in_fix[0] != t_home:
                            # If history is Away vs Home, flip the result
                            if winner == "H": winner = "A"
                            elif winner == "A": winner = "H"
                            
                        results[(t_home, t_away)].append({
                            "total": total,
                            "winner": winner,
                            "u25": total < 2.5,
                            "o15": total > 1.5
                        })
                        
    return results

if __name__ == "__main__":
    locks = find_md2_locks()
    for (h, a), samples in locks.items():
        if not samples: continue
        print(f"\n--- {h} vs {a} (N={len(samples)}) ---")
        u25_rate = sum(1 for s in samples if s["u25"]) / len(samples)
        o15_rate = sum(1 for s in samples if s["o15"]) / len(samples)
        
        # Winner rates
        h_win = sum(1 for s in samples if s["winner"] == "H") / len(samples)
        a_win = sum(1 for s in samples if s["winner"] == "A") / len(samples)
        draw = sum(1 for s in samples if s["winner"] == "D") / len(samples)
        
        print(f"  U2.5: {u25_rate:.2%}")
        print(f"  O1.5: {o15_rate:.2%}")
        print(f"  1X2: H:{h_win:.2%} D:{draw:.2%} A:{a_win:.2%}")
