import json
from collections import defaultdict

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])
seasons = [matches[i:i+240] for i in range(0, len(matches), 240) if len(matches[i:i+240]) == 240]

# Calculate the AVERAGE points for each rank at MD 15 across all seasons
rank_pts_sum = {i: 0 for i in range(1, 17)}
for season_matches in seasons:
    team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
    for m in season_matches:
        if m['match_day'] > 15: continue
        if m['home_goals'] > m['away_goals']: team_pts[m['home_team']] += 3
        elif m['home_goals'] == m['away_goals']: team_pts[m['home_team']] += 1; team_pts[m['away_team']] += 1
        else: team_pts[m['away_team']] += 3
    
    sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
    for i, (t, pts) in enumerate(sorted_teams):
        rank_pts_sum[i+1] += pts

avg_rank_pts = {r: int(round(pts / len(seasons))) for r, pts in rank_pts_sum.items()}
print("--- AVERAGE MD 15 POINTS BY RANK ---")
print(avg_rank_pts)
print()

groups = defaultdict(lambda: {'hw':0, 'aw':0, 'dw':0, 'total':0})

for season_matches in seasons:
    # Build MD 15 Standings and Points
    team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
    for m in season_matches:
        if m['match_day'] > 15: continue
        if m['home_goals'] > m['away_goals']: team_pts[m['home_team']] += 3
        elif m['home_goals'] == m['away_goals']: team_pts[m['home_team']] += 1; team_pts[m['away_team']] += 1
        else: team_pts[m['away_team']] += 3
        
    ranks = {t: i+1 for i, (t, _) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))}
    
    # Assign Quota Status based on points vs avg
    quota_status = {}
    for t, pts in team_pts.items():
        r = ranks[t]
        avg = avg_rank_pts[r]
        if pts > avg + 1: quota_status[t] = "OverQuota"
        elif pts < avg - 1: quota_status[t] = "UnderQuota"
        else: quota_status[t] = "OnQuota"

    leg1_dict = {}
    for m in season_matches:
        if m['match_day'] <= 15:
            pair = tuple(sorted([m['home_team'], m['away_team']]))
            leg1_dict[pair] = m

    for m2 in season_matches:
        if m2['match_day'] > 15:
            pair = tuple(sorted([m2['home_team'], m2['away_team']]))
            m1 = leg1_dict.get(pair)
            if not m1: continue
            
            h1, a1 = m1['home_team'], m1['away_team']
            hg1, ag1 = m1['home_goals'], m1['away_goals']
            
            if hg1 > ag1: w1, l1 = h1, a1
            elif ag1 > hg1: w1, l1 = a1, h1
            else: w1, l1 = "DRAW", "DRAW"
            
            h2, a2 = m2['home_team'], m2['away_team']
            hg2, ag2 = m2['home_goals'], m2['away_goals']
            
            if w1 != "DRAW":
                w1_status = quota_status[w1]
                l1_status = quota_status[l1]
                
                # Check if the Leg 1 Winner was OVER-QUOTA
                if w1_status == "OverQuota":
                    l2_home = "L1 Winner (OverQuota)" if h2 == w1 else "L1 Loser"
                    key = f"L1 Winner was OverQuota | L2 Home is {l2_home}"
                    groups[key]['total'] += 1
                    if hg2 > ag2: groups[key]['hw'] += 1
                    elif ag2 > hg2: groups[key]['aw'] += 1
                    else: groups[key]['dw'] += 1
                
                # Check if the Leg 1 Winner was UNDER-QUOTA
                if w1_status == "UnderQuota":
                    l2_home = "L1 Winner (UnderQuota)" if h2 == w1 else "L1 Loser"
                    key = f"L1 Winner was UnderQuota | L2 Home is {l2_home}"
                    groups[key]['total'] += 1
                    if hg2 > ag2: groups[key]['hw'] += 1
                    elif ag2 > hg2: groups[key]['aw'] += 1
                    else: groups[key]['dw'] += 1


print("--- POINT-AWARENESS IMPACT ON LEG 2 REVENGE ---")
for key, stats in sorted(groups.items(), key=lambda x: x[1]['total'], reverse=True):
    t = stats['total']
    if t < 10: continue
    hw = (stats['hw'] / t) * 100
    aw = (stats['aw'] / t) * 100
    dw = (stats['dw'] / t) * 100
    print(f"{key:<55} | Total: {t:<4} | HomeWin: {hw:^5.1f}% | AwayWin: {aw:^5.1f}% | Draw: {dw:^5.1f}%")

