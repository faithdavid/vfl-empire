import sqlite3
import pandas as pd
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

print("Booting Calculus Tracking Engine...")

match_records = []

for season, season_group in df_all.groupby('season'):
    team_stats = {}
    
    # We need to track points earned in each match to calculate derivatives
    # dict of team -> list of points earned per matchday
    pts_history = defaultdict(list)
    
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        # 1. Calculate Calculus features BEFORE the match
        for _, row in day_matches.iterrows():
            h_team, a_team = row['home'], row['away']
            outcome = row['outcome']
            
            if h_team in team_stats and a_team in team_stats and day > 6:
                # Integral: Total Accumulated Points (Mass)
                h_integral = sum(pts_history[h_team])
                a_integral = sum(pts_history[a_team])
                
                # First Derivative (Velocity): Points in last 3 games
                h_velocity_current = sum(pts_history[h_team][-3:])
                a_velocity_current = sum(pts_history[a_team][-3:])
                
                # Previous Velocity (Points in the 3 games before the last 3)
                h_velocity_past = sum(pts_history[h_team][-6:-3])
                a_velocity_past = sum(pts_history[a_team][-6:-3])
                
                # Second Derivative (Acceleration): Change in Velocity
                h_acceleration = h_velocity_current - h_velocity_past
                a_acceleration = a_velocity_current - a_velocity_past
                
                # Rank (for context)
                ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
                ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
                
                def get_rank_bracket(r):
                    if r <= 4: return 'Top4'
                    if r <= 8: return 'UpMid'
                    if r <= 12: return 'LowMid'
                    return 'Bot4'
                    
                match_records.append({
                    'season': season,
                    'day': day,
                    'h_rank': get_rank_bracket(ranks.get(h_team, 16)),
                    'a_rank': get_rank_bracket(ranks.get(a_team, 16)),
                    'h_vel': h_velocity_current,
                    'a_vel': a_velocity_current,
                    'h_accel': h_acceleration,
                    'a_accel': a_acceleration,
                    'outcome': outcome
                })

        # 2. Update Stats
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            
            team_stats[h_team]['gf'] += h; team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a; team_stats[a_team]['gd'] += (a - h)
            
            if h > a: 
                team_stats[h_team]['pts'] += 3
                pts_history[h_team].append(3); pts_history[a_team].append(0)
            elif h == a:
                team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
                pts_history[h_team].append(1); pts_history[a_team].append(1)
            else: 
                team_stats[a_team]['pts'] += 3
                pts_history[h_team].append(0); pts_history[a_team].append(3)

df_calc = pd.DataFrame(match_records)

print(f"\nCalculus tracking completed for {len(df_calc)} fixtures.")
print("Scanning for mathematically forced outcomes...")

# We are looking for high-velocity teams crashing (negative acceleration)
# Or low-velocity teams surging (positive acceleration)

group_cols = ['h_rank', 'a_rank', 'h_vel', 'a_vel', 'h_accel', 'a_accel']

grouped = df_calc.groupby(group_cols)['outcome'].agg(
    Total='count',
    Most_Common=lambda x: x.mode()[0] if not x.mode().empty else None,
    Count_Most_Common=lambda x: (x == x.mode()[0]).sum() if not x.mode().empty else 0
).reset_index()

grouped['Win_Rate'] = grouped['Count_Most_Common'] / grouped['Total']

# Find angles with >= 20 samples and highest win rate
locks = grouped[(grouped['Total'] >= 20) & (grouped['Win_Rate'] >= 0.80)]
locks = locks.sort_values(by=['Win_Rate', 'Total'], ascending=[False, False])

if not locks.empty:
    print(f"\nFound {len(locks)} high-confidence Calculus Locks (>80% with >=20 samples):")
    print(locks.head(10).to_string(index=False))
else:
    print("\nNo >80% calculus locks found with 20+ samples. Showing best 70%+ volume angles:")
    best = grouped[(grouped['Total'] >= 30) & (grouped['Win_Rate'] >= 0.70)].sort_values(by='Win_Rate', ascending=False)
    print(best.head(10).to_string(index=False))

