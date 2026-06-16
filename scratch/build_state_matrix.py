import sqlite3
import pandas as pd
import numpy as np

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

# We will build a 3D Tensor / Matrix representation
# Dimensions: Season -> Matchday -> Team
# Features: Rank, Points, GD

records = []
print("Building State Matrix...")

for season, season_group in df_all.groupby('season'):
    team_stats = {}
    
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        # 1. Update stats for the day's matches
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            
            team_stats[h_team]['gf'] += h; team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a; team_stats[a_team]['gd'] += (a - h)
            
            if h > a: team_stats[h_team]['pts'] += 3
            elif h == a:
                team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
            else: team_stats[a_team]['pts'] += 3
            
        # 2. Record the league table state AFTER the day's matches
        ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
        ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
        
        for team in ranked_teams:
            records.append({
                'season': season,
                'day': day,
                'team': team,
                'rank': ranks[team],
                'pts': team_stats[team]['pts'],
                'gd': team_stats[team]['gd']
            })
            
    # Just do one season for the proof of concept output
    break

df_matrix = pd.DataFrame(records)

# Let's show the user what this Matrix looks like at MD 15
md_15_state = df_matrix[df_matrix['day'] == 15].sort_values(by='rank')
print("--- LEAGUE STATE VECTOR (MATCHDAY 15) ---")
print(md_15_state.to_string(index=False))

