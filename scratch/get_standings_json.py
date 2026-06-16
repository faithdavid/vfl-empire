import json
from collections import defaultdict

with open("/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json", "r") as f:
    data = json.load(f)

matches = data.get('matches', [])
# filter matches for VFLM 5421, <= MD 10
mds = []
for m in matches:
    if m.get('season_id') == 'VFLM 5421' and m.get('match_day', 99) <= 10:
        mds.append(m)

points = defaultdict(int)
gd = defaultdict(int)
form = defaultdict(list)

for m in mds:
    home = m.get('home_team') or m.get('home')
    away = m.get('away_team') or m.get('away')
    hg = m.get('home_goals')
    ag = m.get('away_goals')
    if hg is None or ag is None: continue
    
    gd[home] += (hg - ag)
    gd[away] += (ag - hg)
    if hg > ag:
        points[home] += 3
        form[home].append((m['match_day'], 'W'))
        form[away].append((m['match_day'], 'L'))
    elif hg < ag:
        points[away] += 3
        form[away].append((m['match_day'], 'W'))
        form[home].append((m['match_day'], 'L'))
    else:
        points[home] += 1
        points[away] += 1
        form[home].append((m['match_day'], 'D'))
        form[away].append((m['match_day'], 'D'))

# Sort form by match_day to ensure chronological order
for team in form:
    form[team].sort(key=lambda x: x[0])
    form[team] = [res[1] for res in form[team]]

def get_sort_key(team):
    return (points[team], gd[team])

ranked = sorted(points.keys(), key=get_sort_key, reverse=True)
if not ranked:
    print("No matches found for VFLM 5421 in results_last12h_compiled.json.")
else:
    print("--- LIVE LEAGUE TABLE FOR VFLM 5421 (UP TO MD 10) ---")
    for i, t in enumerate(ranked):
        f = "".join(form[t][-5:])
        print(f"[{i+1}] {t} | {points[t]} pts | GD: {gd[t]} | Form: {f}")
