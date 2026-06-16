import json
with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/predictions_latest.json') as f:
    live_data = json.load(f)

for md in live_data.get('matchdays', []):
    print(f"Matchday: {md.get('matchday')} (type: {type(md.get('matchday'))})")
    for fix in md.get('fixtures', []):
        h = fix.get('home')
        a = fix.get('away')
        odds = fix.get('odds', {})
        hw = odds.get('home_win')
        d = odds.get('draw')
        aw = odds.get('away_win')
        print(f"{h} vs {a} | 1: {hw} | X: {d} | 2: {aw}")
