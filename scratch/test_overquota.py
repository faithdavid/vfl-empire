import json

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)
matches = data.get('matches', [])[:240]

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

print("--- MD 15 TEAMS VS MD 30 QUOTAS ---")
print("Target Quota for Rank 1 (Midpoint): ~30.5 pts, 9 Wins")
print("Target Quota for Rank 16 (Midpoint): ~8 pts, 2 Wins\n")

for team, stats in sorted_teams:
    proj_pts = stats['pts'] * 2
    proj_w = stats['w'] * 2
    over_pts = proj_pts - 61 # Rank 1 quota is 61
    status = "OVER-QUOTA" if proj_pts > 61 else "UNDER-QUOTA"
    if stats['pts'] > 30:
        print(f"{team} (R{md15_ranks[team]}): {stats['pts']} Pts, {stats['w']} W -> Projected {proj_pts} Pts. {status}")

print("\n--- REVENGE TRAPS AGAINST OVER-QUOTA TEAMS ---")
over_quota_teams = [t for t, s in team_stats.items() if s['pts'] > 30] # Teams with 31+ pts at halfway

traps = 0
hits = 0
for m2 in matches:
    if m2['match_day'] < 16: continue
    md2 = m2['match_day']
    h2, a2 = m2['home_team'], m2['away_team']
    hg2, ag2 = m2['home_goals'], m2['away_goals']
    
    l1 = [m for m in matches if m['match_day'] == md2 - 15 and m['home_team'] == a2 and m['away_team'] == h2][0]
    hg1, ag1 = l1['home_goals'], l1['away_goals']
    
    if hg1 == ag1: continue
    winner1 = l1['home_team'] if hg1 > ag1 else l1['away_team']
    loser1 = l1['away_team'] if hg1 > ag1 else l1['home_team']
    
    # Check if the Elite team was Over-Quota!
    if winner1 in over_quota_teams and md15_ranks[loser1] > 6:
        traps += 1
        success = False
        res = "LOSS"
        if h2 == loser1 and hg2 >= ag2: success = True; res = "WIN/DRAW"
        if a2 == loser1 and ag2 >= hg2: success = True; res = "WIN/DRAW"
        if success: hits += 1
        
        print(f"MD {md2}: {loser1} vs {winner1} (Over-Quota) -> {res}")

print(f"\nTargeting ONLY Over-Quota Traps:")
print(f"Traps: {traps}")
print(f"Hits: {hits} ({(hits/traps)*100:.1f}%)")

