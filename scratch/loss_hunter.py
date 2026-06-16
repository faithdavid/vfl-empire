import sqlite3
import pandas as pd
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

match_records = []

for season, season_group in df_all.groupby('season'):
    team_stats = {} 
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
                    'outcome': outcome,
                    'h_loss': 1 if outcome == 'AWAY' else 0,
                    'a_loss': 1 if outcome == 'HOME' else 0
                })

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

print("Scanning for Guaranteed LOSSES (Hunting the Loser)...\n")

group_cols = ['h_rank', 'a_rank', 'h_streak', 'a_streak']
grouped = df_osc.groupby(group_cols).agg(
    Total=('outcome', 'count'),
    Home_Losses=('h_loss', 'sum'),
    Away_Losses=('a_loss', 'sum')
).reset_index()

grouped['Home_Loss_Rate'] = grouped['Home_Losses'] / grouped['Total']
grouped['Away_Loss_Rate'] = grouped['Away_Losses'] / grouped['Total']

# Look for Home Guaranteed Losses
home_loss_traps = grouped[(grouped['Total'] >= 10) & (grouped['Home_Loss_Rate'] >= 0.70)].sort_values(by='Home_Loss_Rate', ascending=False)
if not home_loss_traps.empty:
    print("--- HIGH PROBABILITY HOME LOSSES (Bet Away) ---")
    print(home_loss_traps[['h_rank', 'a_rank', 'h_streak', 'a_streak', 'Total', 'Home_Loss_Rate']].head(10).to_string(index=False))
else:
    print("No massive Home Loss traps found.")

print("\n")

# Look for Away Guaranteed Losses
away_loss_traps = grouped[(grouped['Total'] >= 10) & (grouped['Away_Loss_Rate'] >= 0.70)].sort_values(by='Away_Loss_Rate', ascending=False)
if not away_loss_traps.empty:
    print("--- HIGH PROBABILITY AWAY LOSSES (Bet Home) ---")
    print(away_loss_traps[['h_rank', 'a_rank', 'h_streak', 'a_streak', 'Total', 'Away_Loss_Rate']].head(10).to_string(index=False))
else:
    print("No massive Away Loss traps found.")
