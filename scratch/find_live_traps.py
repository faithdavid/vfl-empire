import json

RESULTS_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json"
JSON_PATH = "/home/ubuntu/faith-workspace/vfl-empire/scripts/predictions_latest.json"

with open(RESULTS_PATH, "r") as f:
    res_data = json.load(f)
matches = res_data.get('matches', [])

with open(JSON_PATH, "r") as f:
    pred_data = json.load(f)
    
md = pred_data['matchdays'][0]
season = md.get('season', 'Unknown') # Fix: use 'season' string, not 'season_id'
matchday = md.get('matchday', 0)

season_matches = [m for m in matches if m['season'] == season]

team_stats = {t: {'pts': 0, 'w': 0, 'd': 0, 'l': 0} for t in set([m['home_team'] for m in season_matches])}
for m in season_matches:
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
over_quota_teams = [t for t, s in team_stats.items() if s['pts'] > 30]

print(f"=== LIVE STANDINGS: {season} (At Matchday 15) ===")
print("Target Quota for Rank 1 (Midpoint): ~30.5 pts, 9 Wins\n")

for team, stats in sorted_teams:
    if stats['pts'] > 30:
        print(f"🚨 OVER-QUOTA: {team} (Rank {md15_ranks[team]}) -> {stats['pts']} Pts")
    elif md15_ranks[team] <= 5:
        print(f"   ON-PACE: {team} (Rank {md15_ranks[team]}) -> {stats['pts']} Pts")

print(f"\n=== HUNTING REVENGE TRAPS IN MD {matchday}-30 ===")
found_any = False

for m_num in range(matchday, 31):
    for h_team in team_stats.keys():
        for a_team in team_stats.keys():
            if h_team == a_team: continue
            
            # Check if this fixture happens in Leg 1 (we swap home/away for Leg 1)
            l1_matches = [m for m in season_matches if m['match_day'] == m_num - 15 and m['home_team'] == a_team and m['away_team'] == h_team]
            if not l1_matches: continue
            l1 = l1_matches[0]
            
            if h_team not in over_quota_teams and a_team not in over_quota_teams: continue
            
            hg1, ag1 = l1.get('home_goals', 0), l1.get('away_goals', 0)
            if hg1 == ag1: continue
            
            winner1 = l1['home_team'] if hg1 > ag1 else l1['away_team']
            loser1 = l1['away_team'] if hg1 > ag1 else l1['home_team']
            
            if winner1 in over_quota_teams and md15_ranks.get(loser1, 16) > 6:
                found_any = True
                print(f"🎯 MATCHDAY {m_num}: {h_team} vs {a_team}")
                print(f"   ▶ Fade Over-Quota: {winner1}")
                print(f"   ▶ Back Underdog: {loser1} (Double Chance: 1X or X2)")

if not found_any:
    print("No Over-Quota Sabotage Traps found in the remaining matchdays.")

