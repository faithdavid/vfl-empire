import json

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)
matches = data.get('matches', [])[:240]

# --- Build MD 15 Standings ---
team_stats = {t: {'pts': 0, 'w': 0, 'd': 0, 'l': 0} for t in set([m['home_team'] for m in matches])}
for m in matches:
    if m['match_day'] > 15: continue
    h, a = m['home_team'], m['away_team']
    hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
    if hg > ag:
        team_stats[h]['pts'] += 3; team_stats[h]['w'] += 1; team_stats[a]['l'] += 1
    elif hg == ag:
        team_stats[h]['pts'] += 1; team_stats[h]['d'] += 1; team_stats[a]['pts'] += 1; team_stats[a]['d'] += 1
    else:
        team_stats[a]['pts'] += 3; team_stats[a]['w'] += 1; team_stats[h]['l'] += 1

sorted_teams = sorted(team_stats.items(), key=lambda x: x[1]['pts'], reverse=True)
md15_ranks = {t: i+1 for i, (t, _) in enumerate(sorted_teams)}

print("=== THE INSIGHT TEST: MD 16-30 ===")
print("Standard Odds Model: Underdog Double Chance = 2.20 | Underdog Outright Win = 6.00\n")

# 1. OVER-QUOTA FADE (Tottenham)
tot_traps = 0
tot_dc_hits = 0
tot_outright_hits = 0

print("--- STRATEGY 1: FADE OVER-QUOTA TOTTENHAM ---")
print("Targeting: Bottom 10 teams who lost to Tottenham in Leg 1.")
for m2 in matches:
    if m2['match_day'] < 16: continue
    h2, a2 = m2['home_team'], m2['away_team']
    if 'Tottenham' not in (h2, a2): continue
    
    # Find Leg 1
    l1 = [m for m in matches if m['match_day'] == m2['match_day'] - 15 and m['home_team'] == a2 and m['away_team'] == h2][0]
    hg1, ag1 = l1['home_goals'], l1['away_goals']
    
    if hg1 == ag1: continue
    winner1 = l1['home_team'] if hg1 > ag1 else l1['away_team']
    loser1 = l1['away_team'] if hg1 > ag1 else l1['home_team']
    
    if winner1 == 'Tottenham' and md15_ranks[loser1] > 6:
        tot_traps += 1
        hg2, ag2 = m2['home_goals'], m2['away_goals']
        res = "LOSS ❌"
        is_dc = False
        is_outright = False
        
        if h2 == loser1:
            if hg2 > ag2: is_dc = True; is_outright = True; res = "OUTRIGHT WIN ✅"
            elif hg2 == ag2: is_dc = True; res = "DRAW (DC HIT) ✅"
        else:
            if ag2 > hg2: is_dc = True; is_outright = True; res = "OUTRIGHT WIN ✅"
            elif ag2 == hg2: is_dc = True; res = "DRAW (DC HIT) ✅"
            
        if is_dc: tot_dc_hits += 1
        if is_outright: tot_outright_hits += 1
        print(f"MD {m2['match_day']}: {loser1} vs Tottenham -> {res} (Score: {hg2}-{ag2})")

print(f"\nTottenham Fade Results:")
print(f"Traps: {tot_traps}")
print(f"Double Chance Hits: {tot_dc_hits} ({(tot_dc_hits/tot_traps)*100:.1f}%)")
print(f"Outright Hits: {tot_outright_hits} ({(tot_outright_hits/tot_traps)*100:.1f}%)")
dc_profit_tot = (tot_dc_hits * 2.20) - tot_traps
out_profit_tot = (tot_outright_hits * 6.00) - tot_traps
print(f"ROI (Double Chance): {(dc_profit_tot/tot_traps)*100:.1f}% (+{dc_profit_tot:.2f} Units)")
print(f"ROI (Outright Win): {(out_profit_tot/tot_traps)*100:.1f}% (+{out_profit_tot:.2f} Units)\n")


# 2. UNDER-QUOTA BACKING (Crystal Palace)
# At MD 15, Palace had 5 points.
pal_traps = 0
pal_dc_hits = 0
pal_outright_hits = 0

print("--- STRATEGY 2: BACK UNDER-QUOTA CRYSTAL PALACE ---")
print("Targeting: Crystal Palace against ANY Top 6 team that beat them in Leg 1.")
for m2 in matches:
    if m2['match_day'] < 16: continue
    h2, a2 = m2['home_team'], m2['away_team']
    if 'Crystal Palace' not in (h2, a2): continue
    
    l1 = [m for m in matches if m['match_day'] == m2['match_day'] - 15 and m['home_team'] == a2 and m['away_team'] == h2][0]
    hg1, ag1 = l1['home_goals'], l1['away_goals']
    
    if hg1 == ag1: continue
    winner1 = l1['home_team'] if hg1 > ag1 else l1['away_team']
    loser1 = l1['away_team'] if hg1 > ag1 else l1['home_team']
    
    if loser1 == 'Crystal Palace' and md15_ranks[winner1] <= 6:
        pal_traps += 1
        hg2, ag2 = m2['home_goals'], m2['away_goals']
        res = "LOSS ❌"
        is_dc = False
        is_outright = False
        
        if h2 == 'Crystal Palace':
            if hg2 > ag2: is_dc = True; is_outright = True; res = "OUTRIGHT WIN ✅"
            elif hg2 == ag2: is_dc = True; res = "DRAW (DC HIT) ✅"
        else:
            if ag2 > hg2: is_dc = True; is_outright = True; res = "OUTRIGHT WIN ✅"
            elif ag2 == hg2: is_dc = True; res = "DRAW (DC HIT) ✅"
            
        if is_dc: pal_dc_hits += 1
        if is_outright: pal_outright_hits += 1
        print(f"MD {m2['match_day']}: Crystal Palace vs {winner1} -> {res} (Score: {hg2}-{ag2})")

print(f"\nCrystal Palace Backing Results:")
print(f"Traps: {pal_traps}")
print(f"Double Chance Hits: {pal_dc_hits} ({(pal_dc_hits/pal_traps)*100 if pal_traps > 0 else 0:.1f}%)")
print(f"Outright Hits: {pal_outright_hits} ({(pal_outright_hits/pal_traps)*100 if pal_traps > 0 else 0:.1f}%)")
if pal_traps > 0:
    dc_profit_pal = (pal_dc_hits * 2.20) - pal_traps
    out_profit_pal = (pal_outright_hits * 6.00) - pal_traps
    print(f"ROI (Double Chance): {(dc_profit_pal/pal_traps)*100:.1f}% (+{dc_profit_pal:.2f} Units)")
    print(f"ROI (Outright Win): {(out_profit_pal/pal_traps)*100:.1f}% (+{out_profit_pal:.2f} Units)")

