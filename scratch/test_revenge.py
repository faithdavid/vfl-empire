import sys
import json
from collections import defaultdict

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire')

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    results_data = json.load(f)

# The first season's matches
matches = results_data.get('matches', [])[:240]

# Pre-calculate standings for each matchday (1 to 30)
standings_by_md = {}
team_stats = {t: {'pts': 0, 'gf': 0, 'ga': 0} for t in set([m['home_team'] for m in matches])}

matches.sort(key=lambda x: x['match_day'])

current_md = 1
for m in matches:
    if m['match_day'] > current_md:
        # Snapshot the standings for the previous matchday
        standings_by_md[current_md] = {k: v.copy() for k, v in team_stats.items()}
        current_md = m['match_day']
    
    h = m['home_team']
    a = m['away_team']
    hg = m.get('home_goals', 0)
    ag = m.get('away_goals', 0)
    
    team_stats[h]['gf'] += hg
    team_stats[h]['ga'] += ag
    team_stats[a]['gf'] += ag
    team_stats[a]['ga'] += hg
    
    if hg > ag:
        team_stats[h]['pts'] += 3
    elif hg == ag:
        team_stats[h]['pts'] += 1
        team_stats[a]['pts'] += 1
    else:
        team_stats[a]['pts'] += 3

standings_by_md[current_md] = {k: v.copy() for k, v in team_stats.items()}

def get_rank(team, md):
    if md not in standings_by_md: return 16
    stats = standings_by_md[md]
    sorted_teams = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    for i, (t, _) in enumerate(sorted_teams, 1):
        if t == team: return i
    return 16

# Now test the revenge script for MD 16-30
revenge_opportunities = 0
revenge_successes = 0  # Weaker team wins or draws
revenge_upsets = 0     # Weaker team outright wins

print("--- TESTING REVENGE SCRIPT (MD 16-30) ---")
print("Scenario: Top 6 team beats a Bottom 10 team in Leg 1.")
print("Does the Bottom 10 team get revenge (Win/Draw) in Leg 2?\n")

for m2 in matches:
    if m2['match_day'] < 16: continue
    md2 = m2['match_day']
    h2 = m2['home_team']
    a2 = m2['away_team']
    hg2 = m2['home_goals']
    ag2 = m2['away_goals']
    
    # Find Leg 1
    md1 = md2 - 15
    leg1 = [m for m in matches if m['match_day'] == md1 and m['home_team'] == a2 and m['away_team'] == h2]
    if not leg1: continue
    l1 = leg1[0]
    hg1 = l1['home_goals']
    ag1 = l1['away_goals']
    
    # Determine ranks before Leg 1 and Leg 2
    rank_h1 = get_rank(l1['home_team'], max(1, md1 - 1))
    rank_a1 = get_rank(l1['away_team'], max(1, md1 - 1))
    
    rank_h2 = get_rank(h2, max(1, md2 - 1))
    rank_a2 = get_rank(a2, max(1, md2 - 1))
    
    # Did someone win Leg 1?
    if hg1 > ag1:
        winner1, loser1 = l1['home_team'], l1['away_team']
        rank_w1, rank_l1 = rank_h1, rank_a1
    elif ag1 > hg1:
        winner1, loser1 = l1['away_team'], l1['home_team']
        rank_w1, rank_l1 = rank_a1, rank_h1
    else:
        continue # It was a draw in Leg 1, no revenge needed
        
    # Check if winner was Top 6 and loser was Bottom 10 at the time of Leg 2
    rank_w_now = get_rank(winner1, md2-1)
    rank_l_now = get_rank(loser1, md2-1)
    
    if rank_w_now <= 6 and rank_l_now > 6:
        revenge_opportunities += 1
        
        # Did loser get revenge?
        is_revenge = False
        is_upset = False
        res2 = "None"
        if h2 == loser1: # Loser is playing at home in Leg 2
            if hg2 > ag2: 
                is_revenge = True; is_upset = True; res2 = "WIN"
            elif hg2 == ag2:
                is_revenge = True; res2 = "DRAW"
        else: # Loser is playing away in Leg 2
            if ag2 > hg2:
                is_revenge = True; is_upset = True; res2 = "WIN"
            elif ag2 == hg2:
                is_revenge = True; res2 = "DRAW"
                
        if is_revenge: revenge_successes += 1
        if is_upset: revenge_upsets += 1
        
        if is_revenge:
            print(f"MD {md2}: {loser1} (R{rank_l_now}) got revenge on {winner1} (R{rank_w_now})! [Leg 1: L | Leg 2: {res2}]")

print(f"\nRESULTS:")
print(f"Total Traps (Elite beat weaker in Leg 1): {revenge_opportunities}")
print(f"Revenge Successes (Weaker team draws or wins Leg 2): {revenge_successes} ({(revenge_successes/revenge_opportunities*100):.1f}%)")
print(f"Outright Upsets (Weaker team outright wins Leg 2): {revenge_upsets} ({(revenge_upsets/revenge_opportunities*100):.1f}%)")
