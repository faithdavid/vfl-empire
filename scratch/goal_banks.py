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
            h_score, a_score = row['h'], row['a']
            total = h_score + a_score
            
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
                    'h_rank': get_rank_bracket(h_rank),
                    'a_rank': get_rank_bracket(a_rank),
                    'h_streak': f"{h_streak_type}{h_streak_len}",
                    'a_streak': f"{a_streak_type}{a_streak_len}",
                    'total_goals': total,
                    'o05': 1 if total > 0.5 else 0,
                    'o15': 1 if total > 1.5 else 0,
                    'o25': 1 if total > 2.5 else 0,
                    'o35': 1 if total > 3.5 else 0,
                    'o45': 1 if total > 4.5 else 0,
                    'u05': 1 if total < 0.5 else 0,
                    'u15': 1 if total < 1.5 else 0,
                    'u25': 1 if total < 2.5 else 0,
                    'u35': 1 if total < 3.5 else 0,
                    'u45': 1 if total < 4.5 else 0
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

df_banks = pd.DataFrame(match_records)

# Define "Banks"
print("Generating Fixture Goal Banks (MSport Spectrum)...")

def analyze_bank(name, condition):
    bank_df = df_banks[condition]
    if bank_df.empty: return
    total = len(bank_df)
    
    print(f"\n==========================================")
    print(f"BANK: {name} (Matches: {total})")
    print(f"==========================================")
    print(f"O0.5: {bank_df['o05'].mean()*100:.1f}% | U0.5: {bank_df['u05'].mean()*100:.1f}%")
    print(f"O1.5: {bank_df['o15'].mean()*100:.1f}% | U1.5: {bank_df['u15'].mean()*100:.1f}%")
    print(f"O2.5: {bank_df['o25'].mean()*100:.1f}% | U2.5: {bank_df['u25'].mean()*100:.1f}%")
    print(f"O3.5: {bank_df['o35'].mean()*100:.1f}% | U3.5: {bank_df['u35'].mean()*100:.1f}%")
    print(f"O4.5: {bank_df['o45'].mean()*100:.1f}% | U4.5: {bank_df['u45'].mean()*100:.1f}%")

# Bank 1: The Absolute Crush (100% Home Win)
analyze_bank("The Absolute Crush (Top4 W4 vs Bot4 L3)", 
             (df_banks['h_rank'] == 'Top4') & (df_banks['a_rank'] == 'Bot4') & 
             (df_banks['h_streak'] == 'W4') & (df_banks['a_streak'] == 'L3'))

# Bank 2: General Top 4 vs Bottom 4 (The 74% Mismatch)
analyze_bank("General Mismatch (Top4 vs Bot4)", 
             (df_banks['h_rank'] == 'Top4') & (df_banks['a_rank'] == 'Bot4'))

# Bank 3: General Bottom 4 vs Bottom 4
analyze_bank("Basement Battle (Bot4 vs Bot4)", 
             (df_banks['h_rank'] == 'Bot4') & (df_banks['a_rank'] == 'Bot4'))

# Bank 4: Heavyweights
analyze_bank("Heavyweight Clash (Top4 vs Top4)", 
             (df_banks['h_rank'] == 'Top4') & (df_banks['a_rank'] == 'Top4'))

# Look for absolute 100% locks across all streak combinations for O1.5 or U3.5
grouped = df_banks.groupby(['h_rank', 'a_rank', 'h_streak', 'a_streak']).agg(
    Total=('total_goals', 'count'),
    O05=('o05', 'mean'),
    O15=('o15', 'mean'),
    O25=('o25', 'mean'),
    U25=('u25', 'mean'),
    U35=('u35', 'mean')
).reset_index()

print("\n\n--- 100% OVER 1.5 GOAL LOCKS (Min 10 Matches) ---")
o15_locks = grouped[(grouped['Total'] >= 10) & (grouped['O15'] == 1.0)]
print(o15_locks[['h_rank', 'a_rank', 'h_streak', 'a_streak', 'Total', 'O15']].to_string(index=False))

print("\n--- 100% UNDER 3.5 GOAL LOCKS (Min 10 Matches) ---")
u35_locks = grouped[(grouped['Total'] >= 10) & (grouped['U35'] == 1.0)]
print(u35_locks[['h_rank', 'a_rank', 'h_streak', 'a_streak', 'Total', 'U35']].to_string(index=False))
