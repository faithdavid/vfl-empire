import sqlite3
import pandas as pd
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

# We want to collect team-agnostic features before every match
# Features: Home Rank, Away Rank, Home Points, Away Points, Matchday

match_states = []

print("Calculating team states...")
for season, season_group in df_all.groupby('season'):
    team_stats = {}
    
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
                h_pts = team_stats[h_team]['pts']
                a_pts = team_stats[a_team]['pts']
                
                # Group points into brackets of 5 to increase sample sizes
                h_pts_bracket = (h_pts // 5) * 5
                a_pts_bracket = (a_pts // 5) * 5
                
                # Rank brackets (Top 4, Upper Mid 5-8, Lower Mid 9-12, Bottom 13-16)
                def get_rank_bracket(r):
                    if r <= 4: return 'Top 4'
                    if r <= 8: return 'Upper Mid'
                    if r <= 12: return 'Lower Mid'
                    return 'Bottom 4'
                    
                match_states.append({
                    'day': day,
                    'h_rank': h_rank,
                    'a_rank': a_rank,
                    'h_rank_bracket': get_rank_bracket(h_rank),
                    'a_rank_bracket': get_rank_bracket(a_rank),
                    'h_pts_bracket': h_pts_bracket,
                    'a_pts_bracket': a_pts_bracket,
                    'outcome': outcome
                })

        # Update stats
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

df_states = pd.DataFrame(match_states)

print(f"Total valid historical matches with state data: {len(df_states)}")

def analyze_angle(group_cols, min_samples=20, min_win_rate=0.75):
    grouped = df_states.groupby(group_cols)['outcome'].agg(
        Total='count',
        Most_Common=lambda x: x.mode()[0],
        Count_Most_Common=lambda x: (x == x.mode()[0]).sum()
    ).reset_index()
    
    grouped['Win_Rate'] = grouped['Count_Most_Common'] / grouped['Total']
    
    filtered = grouped[(grouped['Total'] >= min_samples) & (grouped['Win_Rate'] >= min_win_rate)]
    filtered = filtered.sort_values(by=['Win_Rate', 'Total'], ascending=[False, False])
    return filtered

print("\n--- ANGLE 1: Exact Home Rank vs Exact Away Rank ---")
res1 = analyze_angle(['h_rank', 'a_rank'], min_samples=30, min_win_rate=0.70)
print(res1.head(10).to_string(index=False) if not res1.empty else "No angles > 70% found.")

print("\n--- ANGLE 2: Home Rank + Matchday ---")
res2 = analyze_angle(['h_rank', 'day'], min_samples=30, min_win_rate=0.70)
print(res2.head(10).to_string(index=False) if not res2.empty else "No angles > 70% found.")

print("\n--- ANGLE 3: Rank Bracket vs Rank Bracket + Points Gap ---")
# Let's add points gap as a feature
df_states['pts_gap'] = df_states['h_pts_bracket'] - df_states['a_pts_bracket']
res3 = analyze_angle(['h_rank_bracket', 'a_rank_bracket', 'pts_gap'], min_samples=50, min_win_rate=0.70)
print(res3.head(10).to_string(index=False) if not res3.empty else "No angles > 70% found.")

print("\n--- ANGLE 4: Extremely High Volume Broad Patterns (Min 200 samples) ---")
res4 = analyze_angle(['h_rank_bracket', 'a_rank_bracket'], min_samples=200, min_win_rate=0.60)
print(res4.head(10).to_string(index=False) if not res4.empty else "No broad patterns > 60% found.")

