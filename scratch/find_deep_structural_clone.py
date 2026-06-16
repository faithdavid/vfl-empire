import json

def normalize(name):
    return name.strip()

def find_deep_structural_clone():
    # Target Sequences (MD 24-28)
    leeds_target = ['London Guns', 'Everton', 'Aston Villa', 'Manchester Red', 'Crystal Palace']
    chelsea_target = ['West Ham', 'Brighton', 'Newcastle', 'Liverpool', 'Bournemouth']
    
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    matches = []
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        
        # Get opponents for Leeds and Chelsea
        leeds_opps = {}
        chelsea_opps = {}
        h2h_mds = []
        
        md_keys = sorted(seasons.keys(), key=lambda x: int(x))
        for k in md_keys:
            fixes = seasons[k]
            for fx in fixes:
                teams = [normalize(t) for t in fx["teams"].split(" vs ")]
                if "Leeds" in teams and "Chelsea" in teams:
                    h2h_mds.append(int(k))
                if "Leeds" in teams:
                    leeds_opps[int(k)] = teams[1] if teams[0] == "Leeds" else teams[0]
                if "Chelsea" in teams:
                    chelsea_opps[int(k)] = teams[1] if teams[0] == "Chelsea" else teams[0]
        
        # Check around each H2H matchday
        for h2h_md in h2h_mds:
            # We want the 5 matches BEFORE this H2H
            l_seq = [leeds_opps.get(h2h_md - i) for i in range(5, 0, -1)]
            c_seq = [chelsea_opps.get(h2h_md - i) for i in range(5, 0, -1)]
            
            if l_seq == leeds_target and c_seq == chelsea_target:
                matches.append({
                    "season": s_name,
                    "h2h_md": h2h_md,
                    "result": next(fx["result"] for fx in seasons[str(h2h_md)] if "Leeds" in fx["teams"] and "Chelsea" in fx["teams"]),
                    "odds": next(fx.get("odds", {}) for fx in seasons[str(h2h_md)] if "Leeds" in fx["teams"] and "Chelsea" in fx["teams"])
                })
                
    return matches

if __name__ == "__main__":
    matches = find_deep_structural_clone()
    print("Searching for Structural Clone (Leeds & Chelsea identical lead-up):")
    if not matches:
        print("No exact structural clones found for this specific lead-up.")
    else:
        print(f"FOUND {len(matches)} STRUCTURAL CLONES:")
        for m in matches:
            print(f"  - {m['season']} MD {m['h2h_md']}: Result {m['result']} (u35 Odds: {m['odds'].get('u35', 'N/A')})")
