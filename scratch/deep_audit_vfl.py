import json
from collections import defaultdict

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def get_signature(fixtures):
    # Use a set to handle duplicates and order-invariance
    return frozenset([normalize_fixture(f) for f in fixtures])

def find_all_matches():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    sig_map = defaultdict(list)
    
    for s_name, seasons in data.items():
        # Only handle VFLM seasons with numbers
        parts = s_name.split(" ")
        if len(parts) < 2 or not parts[1].isdigit(): continue
        s_num = int(parts[1])
        
        for md, fixes in seasons.items():
            if not fixes: continue
            sig = get_signature([fx["teams"] for fx in fixes])
            sig_map[sig].append((s_num, int(md)))
            
    # Find all signature recycles
    recycled = {sig: locs for sig, locs in sig_map.items() if len(locs) > 1}
    
    # Analyze the gaps
    gaps = []
    for sig, locs in recycled.items():
        locs.sort()
        for i in range(len(locs) - 1):
            s1, m1 = locs[i]
            s2, m2 = locs[i+1]
            # We care about (s2-s1) and (m2-m1)
            gaps.append((s2 - s1, m2 - m1))
            
    return recycled, gaps

if __name__ == "__main__":
    recycled, gaps = find_all_matches()
    print(f"Total MDs with Recycled Signatures: {len(recycled)}")
    
    from collections import Counter
    gap_counts = Counter(gaps)
    print("\nTop (Season Gap, MD Offset) Patterns:")
    for (s_gap, m_off), count in gap_counts.most_common(20):
        if s_gap == 0 and m_off in [15, 19, -15, -19]:
            label = "(In-season reverse)"
        else:
            label = ""
        print(f"  Gap {s_gap} seasons, MD offset {m_off}: {count} times {label}")
