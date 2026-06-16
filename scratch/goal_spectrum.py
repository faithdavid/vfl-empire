import sqlite3
import pandas as pd

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

match_records = []

for season, season_group in df_all.groupby('season'):
    team_stats = {} 
    
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        for _, row in day_matches.iterrows():
            h_team, a_team = row['home'], row['away']
            h_score, a_score = row['h'], row['a']
            
            if h_team in team_stats and a_team in team_stats and day > 5: # Wait for 5 matches to establish goal baseline
                h_gf_avg = team_stats[h_team]['gf'] / team_stats[h_team]['played']
                h_ga_avg = team_stats[h_team]['ga'] / team_stats[h_team]['played']
                
                a_gf_avg = team_stats[a_team]['gf'] / team_stats[a_team]['played']
                a_ga_avg = team_stats[a_team]['ga'] / team_stats[a_team]['played']
                
                total_goals = h_score + a_score
                
                def categorize_attack(gf):
                    if gf >= 2.0: return 'High'
                    if gf >= 1.2: return 'Avg'
                    return 'Low'
                    
                def categorize_defense(ga):
                    if ga >= 2.0: return 'Leaky'
                    if ga >= 1.2: return 'Avg'
                    return 'Solid'
                
                match_records.append({
                    'h_att': categorize_attack(h_gf_avg),
                    'h_def': categorize_defense(h_ga_avg),
                    'a_att': categorize_attack(a_gf_avg),
                    'a_def': categorize_defense(a_ga_avg),
                    'total_goals': total_goals,
                    'o15': 1 if total_goals > 1.5 else 0,
                    'o25': 1 if total_goals > 2.5 else 0,
                    'o35': 1 if total_goals > 3.5 else 0,
                })

        # Update stats
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            
            if h_team not in team_stats: team_stats[h_team] = {'gf': 0, 'ga': 0, 'played': 0}
            if a_team not in team_stats: team_stats[a_team] = {'gf': 0, 'ga': 0, 'played': 0}
            
            team_stats[h_team]['gf'] += h
            team_stats[h_team]['ga'] += a
            team_stats[h_team]['played'] += 1
            
            team_stats[a_team]['gf'] += a
            team_stats[a_team]['ga'] += h
            team_stats[a_team]['played'] += 1

df_goals = pd.DataFrame(match_records)

print("Analyzing the Full Goal Spectrum (Over/Under Traps)...\\n")

group_cols = ['h_att', 'h_def', 'a_att', 'a_def']
grouped = df_goals.groupby(group_cols).agg(
    Total=('total_goals', 'count'),
    O15_Rate=('o15', 'mean'),
    O25_Rate=('o25', 'mean'),
    O35_Rate=('o35', 'mean')
).reset_index()

grouped = grouped[grouped['Total'] >= 20]

print("--- HIGHEST OVER 2.5 LIKELIHOOD ---")
o25_traps = grouped.sort_values(by='O25_Rate', ascending=False)
print(o25_traps.head(5).to_string(index=False))

print("\\n--- HIGHEST UNDER 2.5 LIKELIHOOD (Lowest O25) ---")
u25_traps = grouped.sort_values(by='O25_Rate', ascending=True)
print(u25_traps.head(5).to_string(index=False))

print("\\n--- GUARANTEED OVER 1.5 LIKELIHOOD ---")
o15_traps = grouped.sort_values(by='O15_Rate', ascending=False)
print(o15_traps.head(5).to_string(index=False))

