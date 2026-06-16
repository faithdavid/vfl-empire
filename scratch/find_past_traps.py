import sqlite3

RESULTS_DB = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db"
season = "VFLM 5424"

conn = sqlite3.connect(RESULTS_DB)
cursor = conn.cursor()

# Get MD15 Standings
cursor.execute('''
    SELECT home_team, away_team, home_goals, away_goals 
    FROM results 
    WHERE season_name = ? AND match_day <= 15 AND status = 3
''', (season,))

team_stats = {}
matches = cursor.fetchall()
for h, a, hg, ag in matches:
    if h not in team_stats: team_stats[h] = {'pts': 0, 'w': 0, 'd': 0, 'l': 0}
    if a not in team_stats: team_stats[a] = {'pts': 0, 'w': 0, 'd': 0, 'l': 0}
    
    if hg > ag:
        team_stats[h]['pts'] += 3; team_stats[h]['w'] += 1; team_stats[a]['l'] += 1
    elif hg == ag:
        team_stats[h]['pts'] += 1; team_stats[h]['d'] += 1; team_stats[a]['pts'] += 1; team_stats[a]['d'] += 1
    else:
        team_stats[a]['pts'] += 3; team_stats[a]['w'] += 1; team_stats[h]['l'] += 1

sorted_teams = sorted(team_stats.items(), key=lambda x: x[1]['pts'], reverse=True)
md15_ranks = {t: i+1 for i, (t, _) in enumerate(sorted_teams)}
over_quota_teams = [t for t, s in team_stats.items() if s['pts'] > 30]

print(f"=== STANDINGS: {season} (At Matchday 15) ===")

for team, stats in sorted_teams[:5]:
    if stats['pts'] > 30:
        print(f"🚨 OVER-QUOTA: {team} (Rank {md15_ranks[team]}) -> {stats['pts']} Pts")
    else:
        print(f"   ON-PACE: {team} (Rank {md15_ranks[team]}) -> {stats['pts']} Pts")

print("\n=== REVENGE TRAPS THAT TRIGGERED IN MD 16-30 ===")
found_any = False

for m_num in range(16, 31):
    for h_team in team_stats.keys():
        for a_team in team_stats.keys():
            if h_team == a_team: continue
            if h_team not in over_quota_teams and a_team not in over_quota_teams: continue
            
            # Find Leg 1 result
            cursor.execute('''
                SELECT home_goals, away_goals 
                FROM results 
                WHERE season_name = ? AND match_day = ? AND home_team = ? AND away_team = ? AND status = 3
            ''', (season, m_num - 15, a_team, h_team))
            l1 = cursor.fetchone()
            if not l1: continue
            
            hg1, ag1 = l1
            if hg1 == ag1: continue
            
            winner1 = a_team if hg1 > ag1 else h_team
            loser1 = h_team if hg1 > ag1 else a_team
            
            if winner1 in over_quota_teams and md15_ranks.get(loser1, 16) > 6:
                found_any = True
                cursor.execute('''
                    SELECT home_goals, away_goals 
                    FROM results 
                    WHERE season_name = ? AND match_day = ? AND home_team = ? AND away_team = ? AND status = 3
                ''', (season, m_num, h_team, a_team))
                l2 = cursor.fetchone()
                res = "UNKNOWN"
                if l2:
                    hg2, ag2 = l2
                    if h_team == loser1:
                        if hg2 >= ag2: res = "HIT (DC WON) ✅"
                        else: res = "MISS ❌"
                    else:
                        if ag2 >= hg2: res = "HIT (DC WON) ✅"
                        else: res = "MISS ❌"
                        
                print(f"🎯 MD {m_num}: {h_team} vs {a_team} | Fade: {winner1} -> Result: {res}")

if not found_any:
    print("No traps found.")
