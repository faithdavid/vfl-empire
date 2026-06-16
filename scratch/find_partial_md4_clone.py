import json
from collections import defaultdict

def find_partial_md4_results_match():
    results = {
        tuple(sorted(["Aston Villa", "Bournemouth"])): "0-2",
        tuple(sorted(["Crystal Palace", "Brighton"])): "0-1",
        tuple(sorted(["Fulham", "Liverpool"])): "0-5",
        tuple(sorted(["Everton", "Tottenham"])): "3-0",
        tuple(sorted(["Leeds", "West Ham"])): "2-1",
        tuple(sorted(["Manchester Red", "Chelsea"])): "2-2",
        tuple(sorted(["Manchester Blue", "Newcastle"])): "0-1",
        tuple(sorted(["Wolverhampton", "London Guns"])): "0-3"
    }
    
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    matches = []
    for s_name, seasons in data.items():
        if s_name == "VFLM 5148": continue
        
        for md_str, fixes in seasons.items():
            if not fixes or len(fixes) < 8: continue
            
            md_results = {}
            for fx in fixes:
                pair = tuple(sorted(fx["teams"].split(" vs ")))
                md_results[pair] = fx["result"]
            
            # Count matches
            count = sum(1 for pair, res in results.items() if md_results.get(pair) == res)
            if count >= 6:
                matches.append((s_name, md_str, count))
                
    return sorted(matches, key=lambda x: x[2], reverse=True)

if __name__ == "__main__":
    matches = find_partial_md4_results_match()
    print("Searching for Partial MD 4 Result Clones (6/8 or better):")
    if not matches:
        print("No partial clones found.")
    else:
        for s, md, c in matches:
            print(f"  - {s} MD {md}: {c}/8 matches")
