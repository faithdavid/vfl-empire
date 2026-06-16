import sqlite3
import pandas as pd

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
                
                # Top 4 Home (D2) vs Top 4 Away (W2)
                if h_rank <= 4 and a_rank <= 4 and h_streak_type == 'D' and h_streak_len == 2 and a_streak_type == 'W' and a_streak_len == 2:
                    match_records.append({
                        'season': season,
                        'day': day,
                        'h_team': h_team,
                        'a_team': a_team,
                        'outcome': outcome,
                        'h_score': row['h'],
                        'a_score': row['a']
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

df_snap = pd.DataFrame(match_records)
if df_snap.empty:
    print("No matches found for this condition.")
else:
    print(f"Total occurrences of 'Heavyweight Standoff': {len(df_snap)}")
    counts = df_snap['outcome'].value_counts()
    for outcome, count in counts.items():
        print(f"{outcome}: {count} ({count/len(df_snap)*100:.1f}%)")
    
    print("\nDeep Dive into the non-Draws:")
    print(df_snap[df_snap['outcome'] != 'DRAW'].to_string(index=False))
