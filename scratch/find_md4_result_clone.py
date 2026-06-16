import json
from collections import defaultdict

def find_md4_results_match():
    # Actual MD 4 Results for VFLM 5148
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
        
        # Check all matchdays in this season
        for md_str, fixes in seasons.items():
            if not fixes or len(fixes) < 8: continue
            
            md_results = {}
            for fx in fixes:
                pair = tuple(sorted(fx["teams"].split(" vs ")))
                md_results[pair] = fx["result"]
            
            # Check if all 8 results match
            if all(md_results.get(pair) == res for pair, res in results.items()):
                matches.append((s_name, md_str))
                
    return matches

if __name__ == "__main__":
    matches = find_md4_results_match()
    print("Searching for Exact MD 4 Result Clone:")
    if not matches:
        print("No exact clones found for MD 4 results.")
    else:
        print(f"FOUND CLONES: {matches}")
