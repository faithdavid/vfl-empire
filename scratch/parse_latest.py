import json

with open('/home/ubuntu/faith-workspace/vfl-empire/scripts/predictions_latest.json') as f:
    data = json.load(f)
    
md = data['matchdays'][0]
print(f"Season: {md['season_id']}, Matchday: {md['matchday']}\n")

for fix in md['fixtures']:
    markets_data = fix.get('markets', {})
    
    if isinstance(markets_data, dict):
        market = next(iter(markets_data.values()))
    elif isinstance(markets_data, list) and len(markets_data) > 0:
        market = markets_data[0]
    else:
        continue
    
    fixture_name = market.get('fixture', 'Unknown vs Unknown')
    try:
        h_team, a_team = fixture_name.split(' vs ')
    except:
        h_team, a_team = "Unknown", "Unknown"
        
    gates = market.get('gates', {})
    ls = gates.get('league_standing', {})
    h_rank = ls.get('h_rank')
    a_rank = ls.get('a_rank')
    h_form = ls.get('h_form')
    a_form = ls.get('a_form')
    
    o15 = gates.get('cluster', {}).get('o15')
    o25 = gates.get('cluster', {}).get('o25')
    u35 = gates.get('cluster', {}).get('u35')
    gg = gates.get('cluster', {}).get('gg')
    
    # Let's count streaks. For example, L3 means the form ends in LLL.
    def get_streak(form_str):
        if not form_str: return "Unknown"
        last_char = form_str[-1]
        count = 0
        for char in reversed(form_str):
            if char == last_char:
                count += 1
            else:
                break
        return f"{last_char}{count}"
        
    h_streak = get_streak(h_form)
    a_streak = get_streak(a_form)
    
    print(f"Fixture: {h_team} (R{h_rank}, {h_streak}) vs {a_team} (R{a_rank}, {a_streak})")
    print(f"  Form: {h_form} vs {a_form}")
    print(f"  Odds: O1.5: {o15}, O2.5: {o25}, U3.5: {u35}, GG: {gg}")
    print("-" * 50)
