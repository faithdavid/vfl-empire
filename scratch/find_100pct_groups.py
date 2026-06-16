import json
from collections import defaultdict

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])
seasons = [matches[i:i+240] for i in range(0, len(matches), 240) if len(matches[i:i+240]) == 240]

groups = defaultdict(lambda: {'hw':0, 'aw':0, 'dw':0, 'o25':0, 'u25':0, 'btts_yes':0, 'btts_no':0, 'total':0})

def get_rank_group(rank):
    if rank <= 6: return "Top6"
    if rank <= 12: return "Mid6"
    return "Bot4"

for season_matches in seasons:
    # Build MD 15 Standings
    team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
    for m in season_matches:
        if m['match_day'] > 15: continue
        hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
        h, a = m['home_team'], m['away_team']
        if hg > ag: team_pts[h] += 3
        elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
        else: team_pts[a] += 3
        
    ranks = {t: i+1 for i, (t, _) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))}

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
            
            # Construct Group Key
            if w1 == "DRAW":
                scenario = "0-0 Draw" if hg1 == 0 else "Score Draw"
                key = f"L1 {scenario} | L2 Home={get_rank_group(ranks[h2])} vs L2 Away={get_rank_group(ranks[a2])}"
            else:
                gd = abs(hg1 - ag1)
                gd_str = "1GD" if gd == 1 else "2GD" if gd == 2 else "3+GD"
                w_rank = get_rank_group(ranks[w1])
                l_rank = get_rank_group(ranks[l1])
                l2_home = "L1 Winner" if h2 == w1 else "L1 Loser"
                key = f"L1 {w_rank} beats {l_rank} by {gd_str} | L2 Home = {l2_home}"

            groups[key]['total'] += 1
            if hg2 > ag2: groups[key]['hw'] += 1
            elif ag2 > hg2: groups[key]['aw'] += 1
            else: groups[key]['dw'] += 1
            
            if hg2 + ag2 > 2.5: groups[key]['o25'] += 1
            else: groups[key]['u25'] += 1
            
            if hg2 > 0 and ag2 > 0: groups[key]['btts_yes'] += 1
            else: groups[key]['btts_no'] += 1

print("--- 100% DETERMINISTIC GROUPS (Sample Size >= 5) ---")
found = 0
for key, stats in sorted(groups.items(), key=lambda x: x[1]['total'], reverse=True):
    t = stats['total']
    if t < 5: continue
    
    hw = stats['hw'] / t
    aw = stats['aw'] / t
    dw = stats['dw'] / t
    o25 = stats['o25'] / t
    u25 = stats['u25'] / t
    btts_y = stats['btts_yes'] / t
    btts_n = stats['btts_no'] / t
    
    for name, rate in [("Home Win", hw), ("Away Win", aw), ("Draw", dw), ("Over 2.5", o25), ("Under 2.5", u25), ("BTTS Yes", btts_y), ("BTTS No", btts_n)]:
        if rate >= 0.90:
            print(f"[ {rate*100:^5.1f}% ] {name:<12} | {key} (Sample: {t})")
            found += 1

if found == 0:
    print("No 90%+ hit rate groups found with sample >= 5. The algorithm maintains variance.")
    
print("\n--- HIGH PROBABILITY GROUPS (80%+ Hit Rate, Sample Size >= 10) ---")
for key, stats in sorted(groups.items(), key=lambda x: x[1]['total'], reverse=True):
    t = stats['total']
    if t < 10: continue
    
    hw = stats['hw'] / t
    aw = stats['aw'] / t
    dw = stats['dw'] / t
    o25 = stats['o25'] / t
    u25 = stats['u25'] / t
    btts_y = stats['btts_yes'] / t
    btts_n = stats['btts_no'] / t
    
    for name, rate in [("Home Win", hw), ("Away Win", aw), ("Draw", dw), ("Over 2.5", o25), ("Under 2.5", u25), ("BTTS Yes", btts_y), ("BTTS No", btts_n)]:
        if 0.80 <= rate < 0.90:
            print(f"[ {rate*100:^5.1f}% ] {name:<12} | {key} (Sample: {t})")

