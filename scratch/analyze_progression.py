import json
from collections import defaultdict

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def get_signature(fixtures):
    return frozenset([normalize_fixture(f) for f in fixtures])

def analyze_cross_season_progression():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    # season -> [sigs]
    season_sigs = {}
    for s_name, seasons in data.items():
        if not seasons: continue
        # Handle empty season names or non-standard ones
        if not s_name: s_name = "UNKNOWN"
        
        md_keys = sorted(seasons.keys(), key=lambda x: int(x))
        sigs = [get_signature([fx["teams"] for fx in seasons[k]]) for k in md_keys]
        season_sigs[s_name] = sigs
        
    results = []
    seasons = list(season_sigs.keys())
    
    for i in range(len(seasons)):
        for j in range(i + 1, len(seasons)):
            s1 = seasons[i]
            s2 = seasons[j]
            sigs1 = season_sigs[s1]
            sigs2 = season_sigs[s2]
            
            # Look for common subsequences
            for start1 in range(len(sigs1)):
                for start2 in range(len(sigs2)):
                    length = 0
                    while (start1 + length < len(sigs1) and 
                           start2 + length < len(sigs2) and 
                           sigs1[start1 + length] == sigs2[start2 + length]):
                        length += 1
                    
                    if length >= 5: # Threshold for a "consistent progression"
                        results.append({
                            "s1": s1,
                            "start1": start1 + 1,
                            "s2": s2,
                            "start2": start2 + 1,
                            "length": length
                        })
                        
    return results

if __name__ == "__main__":
    progressions = analyze_cross_season_progression()
    print(f"Found {len(progressions)} cross-season progressions of length >= 5.")
    
    # Find intervals
    intervals = []
    for p in progressions:
        try:
            n1 = int(p["s1"].split(" ")[1])
            n2 = int(p["s2"].split(" ")[1])
            intervals.append(abs(n1 - n2))
        except:
            continue
            
    if intervals:
        from collections import Counter
        print("\nCommon Season Intervals for Progressions:")
        for interval, count in Counter(intervals).most_common(10):
            print(f"  Gap {interval} seasons: {count} times")
            
    # Show longest progression
    if progressions:
        longest = max(progressions, key=lambda x: x["length"])
        print(f"\nLongest Progression Match: {longest['length']} matchdays.")
        print(f"  {longest['s1']} (MD {longest['start1']}+) matches {longest['s2']} (MD {longest['start2']}+)")
