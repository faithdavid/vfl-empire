import json
from collections import defaultdict

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])
seasons = [matches[i:i+240] for i in range(0, len(matches), 240) if len(matches[i:i+240]) == 240]

# Calculate expected points for each rank at EACH matchday
avg_pts = defaultdict(lambda: defaultdict(int)) # avg_pts[matchday][rank]
for md in range(1, 31):
    rank_pts_sum = {r: 0 for r in range(1, 17)}
    for season_matches in seasons:
        team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
        for m in season_matches:
            if m['match_day'] > md: continue
            hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
            h, a = m['home_team'], m['away_team']
            if hg > ag: team_pts[h] += 3
            elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
            else: team_pts[a] += 3
        
        ranks = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
        for i, (t, pts) in enumerate(ranks):
            rank_pts_sum[i+1] += pts
            
    for r in range(1, 17):
        avg_pts[md][r] = rank_pts_sum[r] / len(seasons)

# Now map every single fixture state
routing = defaultdict(lambda: {'1':0, 'X':0, '2':0, 'total':0})

def get_bracket(rank):
    if rank <= 5: return "Elite"
    if rank <= 11: return "Mid"
    return "Bot"

def get_quota_status(pts, expected):
    diff = pts - expected
    if diff >= 2: return "Over"
    if diff <= -2: return "Under"
    return "On"

for season_matches in seasons:
    team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
    
    for md in range(1, 31):
        # Update standings BEFORE the matchday begins (so we use MD-1 stats to predict MD)
        ranks = {t: i+1 for i, (t, _) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))}
        
        for m in season_matches:
            if m['match_day'] != md: continue
            
            h, a = m['home_team'], m['away_team']
            h_rank, a_rank = ranks[h], ranks[a]
            
            # Using bracket + quota status to group states broadly enough to find volume
            if md == 1:
                h_state = "Start"
                a_state = "Start"
            else:
                h_exp = avg_pts[md-1][h_rank]
                a_exp = avg_pts[md-1][a_rank]
                h_status = get_quota_status(team_pts[h], h_exp)
                a_status = get_quota_status(team_pts[a], a_exp)
                h_state = f"{get_bracket(h_rank)}({h_status})"
                a_state = f"{get_bracket(a_rank)}({a_status})"
                
            # Phase of season
            phase = "Early(1-10)" if md <= 10 else "Mid(11-20)" if md <= 20 else "Late(21-30)"
            
            key = f"[{phase}] Home:{h_state} vs Away:{a_state}"
            
            hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
            routing[key]['total'] += 1
            if hg > ag: routing[key]['1'] += 1
            elif hg == ag: routing[key]['X'] += 1
            else: routing[key]['2'] += 1
            
        # Add MD points for next iteration
        for m in season_matches:
            if m['match_day'] == md:
                hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
                h, a = m['home_team'], m['away_team']
                if hg > ag: team_pts[h] += 3
                elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
                else: team_pts[a] += 3

print("=== UNIVERSAL ROUTING MAP (Top High-Volume Deterministic Angles) ===")
for key, stats in sorted(routing.items(), key=lambda x: x[1]['total'], reverse=True):
    t = stats['total']
    if t < 25: continue # Require high volume across the seasons
    
    w1 = stats['1']/t
    wX = stats['X']/t
    w2 = stats['2']/t
    
    # We want groups where one outcome (or double chance) is extremely high
    if w1 >= 0.70:
        print(f"[ {w1*100:^5.1f}% ] HOME WIN | {key} (Sample: {t})")
    elif w2 >= 0.70:
        print(f"[ {w2*100:^5.1f}% ] AWAY WIN | {key} (Sample: {t})")
    elif wX >= 0.50: # 50% for a raw draw is massive
        print(f"[ {wX*100:^5.1f}% ] RAW DRAW | {key} (Sample: {t})")
    elif (w1 + wX) >= 0.85:
        print(f"[ {(w1+wX)*100:^5.1f}% ] 1X (DC)  | {key} (Sample: {t})")
    elif (w2 + wX) >= 0.85:
        print(f"[ {(w2+wX)*100:^5.1f}% ] X2 (DC)  | {key} (Sample: {t})")

