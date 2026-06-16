import sqlite3
import pandas as pd
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

state_outcomes = defaultdict(list)

print("Calculating team states day-by-day across all seasons...")
for season, season_group in df_all.groupby('season'):
    team_stats = {}
    
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        ranks = {}
        if len(team_stats) > 0:
            ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
            ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
            
        # Record state before the match
        for idx, row in day_matches.iterrows():
            h_team, a_team = row['home'], row['away']
            outcome = row['outcome'] # 'HOME', 'AWAY', 'DRAW'
            
            h_res = 'WIN' if outcome == 'HOME' else ('DRAW' if outcome == 'DRAW' else 'LOSE')
            a_res = 'WIN' if outcome == 'AWAY' else ('DRAW' if outcome == 'DRAW' else 'LOSE')
            
            if h_team in team_stats:
                h_pts = team_stats[h_team]['pts']
                h_rank = ranks.get(h_team, -1)
                state_outcomes[(h_team, 'HOME', h_rank, h_pts)].append(h_res)
                
            if a_team in team_stats:
                a_pts = team_stats[a_team]['pts']
                a_rank = ranks.get(a_team, -1)
                state_outcomes[(a_team, 'AWAY', a_rank, a_pts)].append(a_res)

        # Update stats
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            
            team_stats[h_team]['gf'] += h
            team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a
            team_stats[a_team]['gd'] += (a - h)
            
            if h > a: team_stats[h_team]['pts'] += 3
            elif h == a:
                team_stats[h_team]['pts'] += 1
                team_stats[a_team]['pts'] += 1
            else: team_stats[a_team]['pts'] += 3

print(f"Generated {len(state_outcomes)} unique state signatures.")

# Look for 100% locks
MIN_SAMPLES = 4
perfect_locks = []
total_instances_checked = 0

for state, outcomes in state_outcomes.items():
    total_instances_checked += len(outcomes)
    if len(outcomes) >= MIN_SAMPLES:
        if len(set(outcomes)) == 1:
            perfect_locks.append({
                'Team': state[0],
                'Location': state[1],
                'Rank': state[2],
                'Points': state[3],
                'Samples': len(outcomes),
                'Guaranteed Outcome': outcomes[0]
            })

df_locks = pd.DataFrame(perfect_locks)

print(f"\nTotal historical matches checked across all states: {total_instances_checked}")

if df_locks.empty:
    print(f"\nNo 100% locks found for (Team + Location + Rank + Points) with >= {MIN_SAMPLES} samples.")
else:
    df_locks = df_locks.sort_values(by='Samples', ascending=False)
    print(f"\n*** FOUND {len(df_locks)} PERFECT STATE LOCKS (100% CONSISTENT) ***")
    print(df_locks.head(20).to_string(index=False))
    
    # Check consistency of less strict states (just Rank + Points)
    print("\nWhat if we just use (Rank + Points) ignoring the specific team?")
    
rank_pts_outcomes = defaultdict(list)
for state, outcomes in state_outcomes.items():
    rank_pts_outcomes[(state[2], state[3])].extend(outcomes)
    
rp_locks = []
for state, outcomes in rank_pts_outcomes.items():
    if len(outcomes) >= MIN_SAMPLES and len(set(outcomes)) == 1:
        rp_locks.append({'Rank': state[0], 'Points': state[1], 'Samples': len(outcomes), 'Outcome': outcomes[0]})

df_rp_locks = pd.DataFrame(rp_locks)
if df_rp_locks.empty:
    print(f"No 100% locks found for purely (Rank + Points) with >= {MIN_SAMPLES} samples.")
else:
    df_rp_locks = df_rp_locks.sort_values(by='Samples', ascending=False)
    print(f"Found {len(df_rp_locks)} perfect locks for purely (Rank + Points)!")
    print(df_rp_locks.head(10).to_string(index=False))

