import json
from collections import defaultdict

def analyze_form_outcomes(target_home, target_away, home_form, away_form):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    matches = []
    # Reverse form strings because we get them DESC from SQL but process them chronologically
    h_form_list = list(home_form)[::-1]
    a_form_list = list(away_form)[::-1]
    
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        
        team_forms = defaultdict(list)
        md_keys = sorted(seasons.keys(), key=lambda x: int(x))
        
        for md_str in md_keys:
            md = int(md_str)
            fixes = seasons[md_str]
            
            for fx in fixes:
                teams = fx["teams"].split(" vs ")
                h, a = teams[0], teams[1]
                
                # Broaden: Match form regardless of specific teams? 
                # No, let's keep it specific first, then broaden.
                if h == target_home and a == target_away:
                    if team_forms[h][-5:] == h_form_list and team_forms[a][-5:] == a_form_list:
                        matches.append({
                            "season": s_name,
                            "md": md,
                            "result": fx["result"]
                        })
                elif h == target_away and a == target_home:
                    # Reversed fixture check
                    if team_forms[h][-5:] == a_form_list and team_forms[a][-5:] == h_form_list:
                         matches.append({
                            "season": s_name,
                            "md": md,
                            "result": fx["result"],
                            "note": "Fixture Reversed"
                        })
            
            # Update forms
            for fx in fixes:
                t = fx["teams"].split(" vs ")
                hg, ag = map(int, fx["result"].split("-"))
                team_forms[t[0]].append("W" if hg > ag else "L" if ag > hg else "D")
                team_forms[t[1]].append("W" if ag > hg else "L" if hg > ag else "D")
                
    return matches

if __name__ == "__main__":
    # MD 26 Case 1: Crystal Palace (LDDLW) vs Leeds (DWLLL)
    print("=== Audit: Crystal Palace (LDDLW) vs Leeds (DWLLL) ===")
    m1 = analyze_form_outcomes("Crystal Palace", "Leeds", "LDDLW", "DWLLL")
    if not m1: print("No exact matches found.")
    for m in m1: print(m)
    
    # MD 26 Case 2: Chelsea (WWWWL) vs Aston Villa (DLDLL)
    print("\n=== Audit: Chelsea (WWWWL) vs Aston Villa (DLDLL) ===")
    m2 = analyze_form_outcomes("Chelsea", "Aston Villa", "WWWWL", "DLDLL")
    if not m2: print("No exact matches found.")
    for m in m2: print(m)
