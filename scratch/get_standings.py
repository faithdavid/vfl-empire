import sqlite3
from collections import defaultdict

conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db')
cur = conn.cursor()
cur.execute("SELECT home_team, away_team, home_goals, away_goals FROM results WHERE season_id='VFLM 5421' AND match_day <= 10")
rows = cur.fetchall()

points = defaultdict(int)
gd = defaultdict(int)
form = defaultdict(list)

for r in rows:
    home, away, hg, ag = r[0], r[1], r[2], r[3]
    gd[home] += (hg - ag)
    gd[away] += (ag - hg)
    if hg > ag:
        points[home] += 3
        form[home].append('W')
        form[away].append('L')
    elif hg < ag:
        points[away] += 3
        form[away].append('W')
        form[home].append('L')
    else:
        points[home] += 1
        points[away] += 1
        form[home].append('D')
        form[away].append('D')

def get_sort_key(team):
    return (points[team], gd[team])

ranked = sorted(points.keys(), key=get_sort_key, reverse=True)
for i, t in enumerate(ranked):
    f = "".join(form[t][-5:])
    print(f"Rank {i+1}: {t} - {points[t]} pts, GD: {gd[t]}, Form: {f}")
