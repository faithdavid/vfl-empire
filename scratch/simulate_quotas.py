import sys
import json
from collections import defaultdict

# Load the historical season
with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])[:240]

# Calculate standings at MD 30 (Final Quotas)
def get_standings(up_to_md):
    team_stats = defaultdict(lambda: {'pts': 0, 'w': 0, 'd': 0, 'l': 0, 'gf': 0, 'ga': 0})
    for m in matches:
        if m['match_day'] > up_to_md: continue
        h = m['home_team']
        a = m['away_team']
        hg = m.get('home_goals', 0)
        ag = m.get('away_goals', 0)
        
        team_stats[h]['gf'] += hg
        team_stats[h]['ga'] += ag
        team_stats[a]['gf'] += ag
        team_stats[a]['ga'] += hg
        
        if hg > ag:
            team_stats[h]['pts'] += 3; team_stats[h]['w'] += 1; team_stats[a]['l'] += 1
        elif hg == ag:
            team_stats[h]['pts'] += 1; team_stats[h]['d'] += 1; team_stats[a]['pts'] += 1; team_stats[a]['d'] += 1
        else:
            team_stats[a]['pts'] += 3; team_stats[a]['w'] += 1; team_stats[h]['l'] += 1
            
    return sorted(team_stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga'], x[1]['gf']), reverse=True)

final_table = get_standings(30)
print("### 📌 STERN QUOTAS (FINAL MD 30 TABLE)")
print("| Rank | Pts | W | D | L |")
print("| :--- | :--- | :--- | :--- | :--- |")
for i, (team, stats) in enumerate(final_table, 1):
    print(f"| Rank {i:<2} | {stats['pts']:<3} | {stats['w']:<2} | {stats['d']:<2} | {stats['l']:<2} |")

# Define target quotas for MD 15 (Halfway point)
# If Rank 1 finishes with 62 pts, they should have ~31 pts at MD 15.
# If they have 35+ pts, they are OVER-QUOTA.
md15_table = get_standings(15)
team_md15_ranks = {t: i+1 for i, (t, _) in enumerate(md15_table)}

# Simulate MD 16-30 Betting
total_bets = 0
won_bets = 0

print("\n### 🚀 LIVE SIMULATION OF REVENGE TRAPS (MD 16-30)")
for m2 in matches:
    if m2['match_day'] < 16: continue
    md2 = m2['match_day']
    h2 = m2['home_team']
    a2 = m2['away_team']
    hg2 = m2['home_goals']
    ag2 = m2['away_goals']
    
    # Find Leg 1 result
    md1 = md2 - 15
    l1 = [m for m in matches if m['match_day'] == md1 and m['home_team'] == a2 and m['away_team'] == h2][0]
    hg1 = l1['home_goals']
    ag1 = l1['away_goals']
    
    # We only trigger trap if Leg 1 had a winner
    if hg1 == ag1: continue
    
    winner1 = l1['home_team'] if hg1 > ag1 else l1['away_team']
    loser1 = l1['away_team'] if hg1 > ag1 else l1['home_team']
    
    # Check Rank at the time of MD 15
    w1_rank = team_md15_ranks[winner1]
    l1_rank = team_md15_ranks[loser1]
    
    # STRATEGY: Elite team (Top 6) beat a weak team (Bottom 10) in Leg 1.
    # We bet on the WEAK TEAM to get revenge (Double Chance: Win or Draw) in Leg 2.
    if w1_rank <= 6 and l1_rank > 6:
        total_bets += 1
        
        # Did the weak team (loser1) win or draw Leg 2?
        success = False
        if h2 == loser1: # Weak team plays home
            if hg2 >= ag2: success = True
        else: # Weak team plays away
            if ag2 >= hg2: success = True
            
        if success:
            won_bets += 1
            res = "HIT ✅"
        else:
            res = "MISS ❌"
            
        # print(f"MD {md2}: {loser1} (R{l1_rank}) vs {winner1} (R{w1_rank}) -> Bet: {loser1} X2 | Result: {res}")

print(f"\n### 📊 SIMULATION RESULTS (FLAT BETTING)")
print(f"Total Traps Identified: {total_bets}")
print(f"Traps Successfully Hit (Win/Draw): {won_bets}")
print(f"Hit Rate: {(won_bets/total_bets)*100:.1f}%")

# Assuming average Double Chance odds for a bottom team vs Top 6 team is 2.20
avg_dc_odds = 2.20
units_wagered = total_bets
units_returned = won_bets * avg_dc_odds
roi = ((units_returned - units_wagered) / units_wagered) * 100

print(f"\nIf betting 1 Unit per Trap on Double Chance (@ ~2.20 average odds):")
print(f"Units Wagered: {units_wagered}")
print(f"Units Returned: {units_returned:.2f}")
print(f"Net Profit: {units_returned - units_wagered:.2f} Units")
print(f"ROI: {roi:.1f}%")
