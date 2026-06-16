import json

with open("/home/ubuntu/faith-workspace/vfl-complete-data/signals/predictions_latest.json", "r") as f:
    data = json.load(f)

md = data.get('matchdays', [{}])[0]
print(f"MATCHDAY: {md.get('matchday', 'Unknown')}")
print("--- ALL CURRENT FIXTURES & ODDS ---")
for fix in md.get('fixtures', []):
    h = fix.get('home', 'Home')
    a = fix.get('away', 'Away')
    
    # Try to get ranks from markets if available, else just say '?'
    hr, ar, hf, af = '?', '?', '?', '?'
    markets = fix.get('markets', [])
    if markets:
        gates = markets[0].get('gate_result', {}).get('gates', {})
        ls = gates.get('league_standing', {})
        hr = ls.get('h_rank', '?')
        ar = ls.get('a_rank', '?')
        hf = ls.get('h_form', '?')
        af = ls.get('a_form', '?')
        
    odds = fix.get('odds', {})
    hw = odds.get('home_win', '-')
    d = odds.get('draw', '-')
    aw = odds.get('away_win', '-')
    
    print(f"Match: {h} [Rank {hr}, Form: {hf}] vs {a} [Rank {ar}, Form: {af}]")
    print(f"Odds : 1: {hw} | X: {d} | 2: {aw}\n")
