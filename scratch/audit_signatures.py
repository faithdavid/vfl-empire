import json
from collections import defaultdict

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def get_signature(fixtures):
    return frozenset([normalize_fixture(f) for f in fixtures])

def audit_all_signatures():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    # signature -> list of (season, md)
    sig_map = defaultdict(list)
    
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            if not fixes: continue
            sig = get_signature([fx["teams"] for fx in fixes])
            sig_map[sig].append((s_name, md))
            
    # Find signatures that appear in multiple seasons
    cross_season_recycles = []
    for sig, occurrences in sig_map.items():
        seasons_seen = set(occ[0] for occ in occurrences)
        if len(seasons_seen) > 1:
            cross_season_recycles.append({
                "signature": list(sig),
                "occurrences": occurrences
            })
            
    return cross_season_recycles

if __name__ == "__main__":
    recycles = audit_all_signatures()
    print(f"Found {len(recycles)} cross-season recycled matchday signatures.")
    
    # Save for deeper analysis
    with open('/home/ubuntu/faith-workspace/vfl-empire/scratch/recycled_signatures.json', 'w') as f:
        json.dump(recycles, f, indent=2)
    
    # Display top examples
    for item in recycles[:5]:
        print(f"\nSignature: {item['signature']}")
        for s, md in item['occurrences']:
            print(f"  - {s} Matchday {md}")
