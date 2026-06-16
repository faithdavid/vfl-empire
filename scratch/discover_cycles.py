import json

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def get_signature(fixtures):
    return tuple(sorted([normalize_fixture(f) for f in fixtures]))

def find_recycles():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    signatures = {} # {signature: [(season, md), ...]}
    
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            sig = get_signature([fx["teams"] for fx in fixes])
            if sig not in signatures:
                signatures[sig] = []
            signatures[sig].append((s_name, md))
            
    recycled = {k: v for k, v in signatures.items() if len(v) > 1}
    
    # Calculate intervals
    intervals = []
    for sig, occurrences in recycled.items():
        valid_occ = []
        for occ in occurrences:
            parts = occ[0].split(" ")
            if len(parts) > 1 and parts[1].isdigit():
                valid_occ.append((int(parts[1]), occ))
        
        valid_occ.sort() # Sort by season number
        for i in range(len(valid_occ) - 1):
            s1 = valid_occ[i][0]
            s2 = valid_occ[i+1][0]
            if s1 != s2:
                intervals.append(s2 - s1)
            
    return recycled, intervals

if __name__ == "__main__":
    recycled, intervals = find_recycles()
    print(f"Total Unique Signatures: {len(recycled) + 0}") # Just a placeholder
    print(f"Total Recycled MDs: {len(recycled)}")
    
    from collections import Counter
    interval_counts = Counter(intervals)
    print("\nTop Intervals (Season Gaps):")
    for interval, count in interval_counts.most_common(10):
        print(f"Gap {interval} seasons: {count} times")
        
    # Find a specific example
    example_sig = list(recycled.keys())[0]
    print(f"\nExample Recycle for Signature {example_sig}:")
    for s, md in recycled[example_sig]:
        print(f"  - {s} Matchday {md}")
