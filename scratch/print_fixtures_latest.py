import json

with open("/home/ubuntu/faith-workspace/vfl-complete-data/signals/predictions_latest.json", "r") as f:
    data = json.load(f)

md = data.get('matchdays', [{}])[0]
print(f"MATCHDAY: {md.get('matchday', 'Unknown')}")
print("--- ALL CURRENT FIXTURES & ODDS ---")
for fix in md.get('fixtures', []):
    h = fix.get('home', 'Home')
    a = fix.get('away', 'Away')
    odds = fix.get('odds', {})
    hw = odds.get('home_win', '-')
    d = odds.get('draw', '-')
    aw = odds.get('away_win', '-')
    print(f"{h} vs {a} | 1: {hw} | X: {d} | 2: {aw}")
