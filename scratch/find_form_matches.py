import json
from collections import defaultdict

def get_team_form(seasons_data, season_name, team_name, up_to_md, length=5):
    season = seasons_data.get(season_name, {})
    results = []
    # Collect all matchdays for this team in this season
    for md in range(1, up_to_md):
        fixes = season.get(str(md), [])
        for fx in fixes:
            if team_name in fx["teams"]:
                # Get result for this team
                hg, ag = map(int, fx["result"].split("-"))
                teams = fx["teams"].split(" vs ")
                if teams[0] == team_name:
                    res = "W" if hg > ag else "L" if ag > hg else "D"
                else:
                    res = "W" if ag > hg else "L" if hg > ag else "D"
                results.append(res)
    return results[-length:]

def find_form_matches(target_home, target_away, target_home_form, target_away_form):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    matches = []
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue # Current season
        
        # Track form for all teams in this season
        team_forms = defaultdict(list)
        md_keys = sorted(seasons.keys(), key=lambda x: int(x))
        
        for md_str in md_keys:
            md = int(md_str)
            fixes = seasons[md_str]
            
            # Check every fixture in this MD to see if it matches our target fixture AND form
            for fx in fixes:
                teams = fx["teams"].split(" vs ")
                home, away = teams[0], teams[1]
                
                # Check if it's the same fixture (or even just any fixture?)
                # The user said "leeds vs chelsea", implying fixture specificity.
                if home == target_home and away == target_away:
                    home_form = team_forms[home][-5:]
                    away_form = team_forms[away][-5:]
                    
                    if home_form == target_home_form and away_form == target_away_form:
                        matches.append({
                            "season": s_name,
                            "md": md,
                            "result": fx["result"],
                            "odds": fx.get("odds", {})
                        })
            
            # Update forms after the MD
            for fx in fixes:
                t = fx["teams"].split(" vs ")
                hg, ag = map(int, fx["result"].split("-"))
                team_forms[t[0]].append("W" if hg > ag else "L" if ag > hg else "D")
                team_forms[t[1]].append("W" if ag > hg else "L" if hg > ag else "D")
                
    return matches

if __name__ == "__main__":
    # Example: Leeds vs Chelsea
    # Let's find their current form in VFLM 5147 up to MD 23
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    # Actually let's use a real fixture from MD 26 if possible, or just test the logic
    # For now, let's look at MD 23: Leeds vs Manchester Blue
    home_team = "Leeds"
    away_team = "Manchester Blue"
    h_form = get_team_form(data, "VFLM 5147", home_team, 23)
    a_form = get_team_form(data, "VFLM 5147", away_team, 23)
    
    print(f"Target: {home_team} ({h_form}) vs {away_team} ({a_form})")
    
    matches = find_form_matches(home_team, away_team, h_form, a_form)
    print(f"Found {len(matches)} historical matches with identical fixture and form.")
    for m in matches:
        print(f"  - {m['season']} MD {m['md']}: Result {m['result']} (Odds: {m['odds'].get('u35', 'N/A')})")
