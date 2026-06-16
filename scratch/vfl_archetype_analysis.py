import json
import pandas as pd
from collections import defaultdict

def analyze_archetype_outcomes(home_form, away_form, length=3):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    matches = []
    h_form_list = list(home_form)[::-1][:length]
    a_form_list = list(away_form)[::-1][:length]
    
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
                
                h_f = team_forms[h][-length:]
                a_f = team_forms[a][-length:]
                
                if h_f == h_form_list and a_f == a_form_list:
                    hg, ag = map(int, fx["result"].split("-"))
                    matches.append({
                        "res": fx["result"],
                        "total": hg + ag,
                        "h_win": hg > ag,
                        "a_win": ag > hg,
                        "draw": hg == ag
                    })
                
            for fx in fixes:
                t = fx["teams"].split(" vs ")
                hg, ag = map(int, fx["result"].split("-"))
                team_forms[t[0]].append("W" if hg > ag else "L" if ag > hg else "D")
                team_forms[t[1]].append("W" if ag > hg else "L" if hg > ag else "D")
                
    return matches

if __name__ == "__main__":
    # MD 26 Case 1: Crystal Palace (DLW) vs Leeds (WLL)
    print("=== Archetype (Last 3): DLW vs WLL ===")
    m1 = analyze_archetype_outcomes("DLW", "WLL")
    if m1:
        df = pd.DataFrame(m1)
        print(f"Samples: {len(df)}")
        print(f"H Win %: {df['h_win'].mean():.2%}")
        print(f"A Win %: {df['a_win'].mean():.2%}")
        print(f"Draw %: {df['draw'].mean():.2%}")
        print(f"O 1.5 %: {(df['total'] > 1.5).mean():.2%}")
        print(f"U 2.5 %: {(df['total'] < 2.5).mean():.2%}")
    
    # MD 26 Case 2: Chelsea (WWL) vs Aston Villa (DLL)
    print("\n=== Archetype (Last 3): WWL vs DLL ===")
    m2 = analyze_archetype_outcomes("WWL", "DLL")
    if m2:
        df = pd.DataFrame(m2)
        print(f"Samples: {len(df)}")
        print(f"H Win %: {df['h_win'].mean():.2%}")
        print(f"A Win %: {df['a_win'].mean():.2%}")
        print(f"Draw %: {df['draw'].mean():.2%}")
        print(f"O 1.5 %: {(df['total'] > 1.5).mean():.2%}")
        print(f"U 2.5 %: {(df['total'] < 2.5).mean():.2%}")
