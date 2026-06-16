import sqlite3
import pandas as pd
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome, oh, od, oa, o_o25, o_u25, o_gg, o_ng FROM matches ORDER BY season, day", conn_hist)

match_states = []
print("Calculating team states & integrating odds...")

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
            if pd.isna(row['oh']) or pd.isna(row['oa']): continue
            
            h_team, a_team = row['home'], row['away']
            if h_team in team_stats and a_team in team_stats:
                h_rank = ranks.get(h_team, -1)
                a_rank = ranks.get(a_team, -1)
                
                def get_rank_bracket(r):
                    if r <= 4: return 'Top 4'
                    if r <= 8: return 'Upper Mid'
                    if r <= 12: return 'Lower Mid'
                    return 'Bottom 4'
                    
                match_states.append({
                    'h_rank': h_rank,
                    'a_rank': a_rank,
                    'h_rank_bracket': get_rank_bracket(h_rank),
                    'a_rank_bracket': get_rank_bracket(a_rank),
                    'oh': round(row['oh'], 2),
                    'od': round(row['od'], 2),
                    'oa': round(row['oa'], 2),
                    'outcome': row['outcome']
                })

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

def analyze_angle(group_cols, min_samples=15, min_win_rate=0.85):
    grouped = df_states.groupby(group_cols)['outcome'].agg(
        Total='count',
        Most_Common=lambda x: x.mode()[0] if not x.mode().empty else None,
        Count_Most_Common=lambda x: (x == x.mode()[0]).sum() if not x.mode().empty else 0
    ).reset_index()
    
    grouped['Win_Rate'] = grouped['Count_Most_Common'] / grouped['Total']
    
    filtered = grouped[(grouped['Total'] >= min_samples) & (grouped['Win_Rate'] >= min_win_rate)]
    filtered = filtered.sort_values(by=['Win_Rate', 'Total'], ascending=[False, False])
    return filtered

print("\n--- ANGLE 1: EXACT MATCH ODDS (oh, od, oa) > 85% Win Rate ---")
res1 = analyze_angle(['oh', 'od', 'oa'], min_samples=20, min_win_rate=0.85)
print(res1.head(15).to_string(index=False) if not res1.empty else "No >85% exact odds locks found with 20+ samples.")

print("\n--- ANGLE 2: HOME ODDS BINNED BY RANK > 85% Win Rate ---")
res2 = analyze_angle(['h_rank', 'oh'], min_samples=20, min_win_rate=0.85)
print(res2.head(15).to_string(index=False) if not res2.empty else "No >85% Rank+Odds locks found with 20+ samples.")

print("\n--- ANGLE 3: RANK BRACKETS + HOME ODDS > 80% Win Rate ---")
res3 = analyze_angle(['h_rank_bracket', 'a_rank_bracket', 'oh'], min_samples=30, min_win_rate=0.80)
print(res3.head(15).to_string(index=False) if not res3.empty else "No >80% Rank Bracket+Odds locks found.")
