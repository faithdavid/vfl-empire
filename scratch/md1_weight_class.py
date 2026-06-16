import sqlite3
import pandas as pd

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

# Calculate total wins per team across ALL seasons
team_wins = {}
team_matches = {}

for _, row in df_all.iterrows():
    h_team, a_team = row['home'], row['away']
    outcome = row['outcome']
    
    if h_team not in team_wins:
        team_wins[h_team] = 0
        team_matches[h_team] = 0
    if a_team not in team_wins:
        team_wins[a_team] = 0
        team_matches[a_team] = 0
        
    team_matches[h_team] += 1
    team_matches[a_team] += 1
    
    if outcome == 'HOME': team_wins[h_team] += 1
    elif outcome == 'AWAY': team_wins[a_team] += 1

print("Analyzing Permanent Team Weight Classes...")
records = []
for t in team_wins.keys():
    win_rate = team_wins[t] / team_matches[t]
    records.append({'Team': t, 'Win_Rate': win_rate, 'Total_Matches': team_matches[t]})
    
df_weight = pd.DataFrame(records).sort_values(by='Win_Rate', ascending=False)
print(df_weight.to_string(index=False))

# Check Matchday 1 specifically
print("\n--- MATCHDAY 1 PREDICTABILITY (FAVORITE WEIGHT CLASS) ---")
md1 = df_all[df_all['day'] == 1]
correct = 0
total = 0
for _, row in md1.iterrows():
    h_team, a_team, outcome = row['home'], row['away'], row['outcome']
    h_weight = team_wins[h_team] / team_matches[h_team]
    a_weight = team_wins[a_team] / team_matches[a_team]
    
    pred = 'HOME' if h_weight > a_weight else 'AWAY'
    if pred == outcome:
        correct += 1
    total += 1

print(f"If we blindly bet the historically 'heavier' weight class on MD1: {correct}/{total} ({correct/total*100:.1f}%)")

