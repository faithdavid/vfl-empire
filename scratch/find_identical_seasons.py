import json

def get_season_signature(season_data):
    # Get signatures for all 38 MDs
    sigs = []
    for md in range(1, 39):
        md_str = str(md)
        if md_str in season_data:
            fixes = season_data[md_str]
            sig = frozenset([tuple(sorted(f["teams"].split(" vs "))) for f in fixes])
            sigs.append(sig)
        else:
            sigs.append(None)
    return tuple(sigs)

def find_clones():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    season_sigs = {} # {sig: [season_names]}
    
    for s_name, seasons in data.items():
        if not seasons: continue
        sig = get_season_signature(seasons)
        if sig not in season_sigs:
            season_sigs[sig] = []
        season_sigs[sig].append(s_name)
        
    clones = {k: v for k, v in season_sigs.items() if len(v) > 1}
    return clones

if __name__ == "__main__":
    clones = find_clones()
    if not clones:
        print("No identical seasons found.")
    else:
        for sig, names in clones.items():
            print(f"Clone set: {names}")
