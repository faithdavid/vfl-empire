import sqlite3
import pandas as pd
import numpy as np
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

print("Phase 1: Compiling 4D State Matrix & Graph Features...")

match_records = []

for season, season_group in df_all.groupby('season'):
    team_stats = {} # pts, gd, gf
    
    # To calculate Graph/Network features, we need to know who beat whom recently
    # dict of team -> list of tuples: (day, points_earned, opponent, opponent_pts_at_time)
    match_history = defaultdict(list)
    
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        ranks = {}
        if len(team_stats) > 0:
            ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
            ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
            
        for _, row in day_matches.iterrows():
            h_team, a_team = row['home'], row['away']
            outcome = row['outcome']
            
            if h_team in team_stats and a_team in team_stats:
                h_rank = ranks.get(h_team, -1)
                a_rank = ranks.get(a_team, -1)
                
                # Calculate Momentum (Points in last 3 matches)
                h_last_3 = match_history[h_team][-3:]
                a_last_3 = match_history[a_team][-3:]
                h_momentum = sum(x[1] for x in h_last_3)
                a_momentum = sum(x[1] for x in a_last_3)
                
                # Calculate Network Momentum (Sum of points of opponents they BEAT in last 3 matches)
                h_network = sum(x[3] for x in h_last_3 if x[1] == 3)
                a_network = sum(x[3] for x in a_last_3 if x[1] == 3)
                
                # Discretize network momentum to group similar patterns
                h_net_bracket = (h_network // 10) * 10
                a_net_bracket = (a_network // 10) * 10
                
                def get_rank_bracket(r):
                    if r <= 4: return 'Top 4'
                    if r <= 8: return 'Upper Mid'
                    if r <= 12: return 'Lower Mid'
                    return 'Bottom 4'
                    
                match_records.append({
                    'season': season,
                    'day': day,
                    'h_rank_bracket': get_rank_bracket(h_rank),
                    'a_rank_bracket': get_rank_bracket(a_rank),
                    'h_momentum': h_momentum, # 0 to 9
                    'a_momentum': a_momentum, # 0 to 9
                    'h_net_bracket': h_net_bracket,
                    'a_net_bracket': a_net_bracket,
                    'outcome': outcome
                })

        # Update stats
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            
            a_pts_at_time = team_stats[a_team]['pts']
            h_pts_at_time = team_stats[h_team]['pts']
            
            team_stats[h_team]['gf'] += h; team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a; team_stats[a_team]['gd'] += (a - h)
            
            if h > a: 
                team_stats[h_team]['pts'] += 3
                match_history[h_team].append((day, 3, a_team, a_pts_at_time))
                match_history[a_team].append((day, 0, h_team, h_pts_at_time))
            elif h == a:
                team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
                match_history[h_team].append((day, 1, a_team, a_pts_at_time))
                match_history[a_team].append((day, 1, h_team, h_pts_at_time))
            else: 
                team_stats[a_team]['pts'] += 3
                match_history[h_team].append((day, 0, a_team, a_pts_at_time))
                match_history[a_team].append((day, 3, h_team, h_pts_at_time))

df_features = pd.DataFrame(match_records)
print(f"Compiled Graph & Matrix Features for {len(df_features)} Matches.")

print("\nPhase 2: Scanning for Transitive Locks (>85% Win Rate)...")
# We will group by the deep graph signature
group_cols = ['h_rank_bracket', 'a_rank_bracket', 'h_momentum', 'a_momentum', 'h_net_bracket', 'a_net_bracket']

grouped = df_features.groupby(group_cols)['outcome'].agg(
    Total='count',
    Most_Common=lambda x: x.mode()[0] if not x.mode().empty else None,
    Count_Most_Common=lambda x: (x == x.mode()[0]).sum() if not x.mode().empty else 0
).reset_index()

grouped['Win_Rate'] = grouped['Count_Most_Common'] / grouped['Total']

# Filter for High Confidence Angles
# We want >= 15 samples to avoid flukes, and >= 85% predictability
locks = grouped[(grouped['Total'] >= 15) & (grouped['Win_Rate'] >= 0.85)]
locks = locks.sort_values(by=['Win_Rate', 'Total'], ascending=[False, False])

if locks.empty:
    print("No angles achieved >85% predictability with >=15 samples.")
    # Show the best ones we found
    best = grouped[grouped['Total'] >= 20].sort_values(by='Win_Rate', ascending=False)
    print("\nBest Angles Found (>=20 samples):")
    print(best.head(10).to_string(index=False))
else:
    print(f"\nFound {len(locks)} ABSOLUTE GRAPH LOCKS (>85% predictability)!")
    print(locks.head(15).to_string(index=False))
    
    # Calculate how many absolute picks this would generate in an average season
    total_picks_in_history = locks['Total'].sum()
    seasons_in_db = len(df_all['season'].unique())
    picks_per_season = total_picks_in_history / seasons_in_db
    print(f"\nThis deep matrix approach generates roughly {picks_per_season:.1f} absolute picks per season.")

