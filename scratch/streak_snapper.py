import sqlite3
import pandas as pd
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

print("Analyzing Team Oscillations and Streak Snapping...")

match_records = []

for season, season_group in df_all.groupby('season'):
    team_stats = {} # pts, gd, gf
    
    # Track current streak: tuple (type, length) e.g., ('W', 3)
    team_streaks = {team: ('-', 0) for team in df_all['home'].unique()}
    
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
            
            if h_team in team_stats and a_team in team_stats and day > 3:
                h_rank = ranks.get(h_team, 16)
                a_rank = ranks.get(a_team, 16)
                
                h_streak_type, h_streak_len = team_streaks[h_team]
                a_streak_type, a_streak_len = team_streaks[a_team]
                
                def get_rank_bracket(r):
                    if r <= 4: return 'Top4'
                    if r <= 8: return 'UpMid'
                    if r <= 12: return 'LowMid'
                    return 'Bot4'
                    
                match_records.append({
                    'season': season,
                    'day': day,
                    'h_rank': get_rank_bracket(h_rank),
                    'a_rank': get_rank_bracket(a_rank),
                    'h_streak': f"{h_streak_type}{h_streak_len}",
                    'a_streak': f"{a_streak_type}{a_streak_len}",
                    'outcome': outcome
                })

        # Update stats and streaks
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            
            team_stats[h_team]['gf'] += h; team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a; team_stats[a_team]['gd'] += (a - h)
            
            def update_streak(team, result):
                curr_type, curr_len = team_streaks[team]
                if curr_type == result:
                    team_streaks[team] = (result, curr_len + 1)
                else:
                    team_streaks[team] = (result, 1)
            
            if h > a: 
                team_stats[h_team]['pts'] += 3
                update_streak(h_team, 'W'); update_streak(a_team, 'L')
            elif h == a:
                team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
                update_streak(h_team, 'D'); update_streak(a_team, 'D')
            else: 
                team_stats[a_team]['pts'] += 3
                update_streak(h_team, 'L'); update_streak(a_team, 'W')

df_osc = pd.DataFrame(match_records)

# Find what happens when streaks collide with ranks
# Focus on long streaks (>= 3 matches)
print("\nScanning for Streak-Snapping / Mean Reversion Points...")

# Example: Home has won 3+ in a row
df_long_streaks = df_osc[df_osc['h_streak'].str.contains('3|4|5|6|7')]

group_cols = ['h_rank', 'a_rank', 'h_streak', 'a_streak']
grouped = df_osc.groupby(group_cols)['outcome'].agg(
    Total='count',
    Most_Common=lambda x: x.mode()[0] if not x.mode().empty else None,
    Count_Most_Common=lambda x: (x == x.mode()[0]).sum() if not x.mode().empty else 0
).reset_index()

grouped['Win_Rate'] = grouped['Count_Most_Common'] / grouped['Total']

# High confidence locks based on streaks
locks = grouped[(grouped['Total'] >= 15) & (grouped['Win_Rate'] >= 0.85)].sort_values(by=['Win_Rate', 'Total'], ascending=[False, False])

if not locks.empty:
    print(f"\nFound {len(locks)} oscillation/streak traps (>85% certainty, >=15 samples):")
    print(locks.head(15).to_string(index=False))
else:
    print("\nNo absolute >85% locks found for simple streak combinations.")
    
# Let's specifically look for "Guaranteed Draws" when streaks collide
draws = grouped[(grouped['Most_Common'] == 'DRAW') & (grouped['Total'] >= 10)].sort_values(by='Win_Rate', ascending=False)
if not draws.empty:
    print("\nTop 5 Oscillation Sequences that force a Guaranteed DRAW:")
    print(draws.head(5).to_string(index=False))

