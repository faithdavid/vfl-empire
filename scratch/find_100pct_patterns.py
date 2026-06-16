import json
from collections import defaultdict

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])

# Chunk matches into full seasons (240 matches each)
seasons = [matches[i:i+240] for i in range(0, len(matches), 240) if len(matches[i:i+240]) == 240]

patterns = defaultdict(lambda: {'L2_H_Win': 0, 'L2_A_Win': 0, 'L2_Draw': 0, 'L2_O25': 0, 'L2_U25': 0, 'L2_BTTS': 0, 'total': 0})

for season_matches in seasons:
    # Build dictionary of Leg 1 matches by teams (sorted tuple so home/away doesn't matter for key)
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
            
            # Determine Leg 1 attributes (relative to m1's home team)
            h1, a1 = m1['home_team'], m1['away_team']
            hg1, ag1 = m1['home_goals'], m1['away_goals']
            
            # Identify who won Leg 1
            if hg1 > ag1: l1_winner, l1_loser = h1, a1
            elif ag1 > hg1: l1_winner, l1_loser = a1, h1
            else: l1_winner, l1_loser = "DRAW", "DRAW"
            
            l1_gd = abs(hg1 - ag1)
            l1_total = hg1 + ag1
            l1_btts = hg1 > 0 and ag1 > 0
            
            # Define Scenarios based on Leg 1
            scenarios = []
            
            if l1_winner == "DRAW":
                if hg1 == 0: scenarios.append("L1 was 0-0 Draw")
                else: scenarios.append("L1 was Score Draw")
            else:
                if l1_gd >= 3: scenarios.append("L1 was Blowout (3+ GD)")
                elif l1_gd == 1: scenarios.append("L1 was Close Win (1 GD)")
                
                if m2['home_team'] == l1_winner: scenarios.append("L1 Winner plays Home in L2")
                else: scenarios.append("L1 Loser plays Home in L2")
                
            if l1_total > 3: scenarios.append("L1 was Very High Scoring (4+ Goals)")
            
            # Determine Leg 2 Outcome (relative to m2)
            h2, a2 = m2['home_team'], m2['away_team']
            hg2, ag2 = m2['home_goals'], m2['away_goals']
            
            for s in scenarios:
                patterns[s]['total'] += 1
                if hg2 > ag2: patterns[s]['L2_H_Win'] += 1
                elif ag2 > hg2: patterns[s]['L2_A_Win'] += 1
                else: patterns[s]['L2_Draw'] += 1
                
                if hg2 + ag2 > 2.5: patterns[s]['L2_O25'] += 1
                else: patterns[s]['L2_U25'] += 1
                
                if hg2 > 0 and ag2 > 0: patterns[s]['L2_BTTS'] += 1

print(f"Analyzed {len(seasons)} full seasons.\n")
print(f"{'Leg 1 Scenario':<35} | {'Total':<6} | {'H-Win%':<7} | {'A-Win%':<7} | {'Draw%':<7} | {'O2.5%':<7} | {'BTTS%':<7}")
print("-" * 85)

for scenario, stats in sorted(patterns.items(), key=lambda x: x[1]['total'], reverse=True):
    t = stats['total']
    if t < 20: continue # Skip rare events
    hw = (stats['L2_H_Win'] / t) * 100
    aw = (stats['L2_A_Win'] / t) * 100
    dw = (stats['L2_Draw'] / t) * 100
    o25 = (stats['L2_O25'] / t) * 100
    btts = (stats['L2_BTTS'] / t) * 100
    
    print(f"{scenario:<35} | {t:<6} | {hw:<7.1f} | {aw:<7.1f} | {dw:<7.1f} | {o25:<7.1f} | {btts:<7.1f}")
