import sqlite3
import pandas as pd

conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')

# Get latest 5 seasons
seasons_df = pd.read_sql_query("SELECT DISTINCT season FROM matches ORDER BY season DESC LIMIT 5", conn)
latest_seasons = seasons_df['season'].tolist()
latest_seasons.reverse() # Chronological

print(f"Backtesting over the latest 5 seasons: {latest_seasons}\\n")

query = f"""
    SELECT season, day, home, away, h, a, outcome 
    FROM matches 
    WHERE season IN ({','.join(['?']*len(latest_seasons))})
    ORDER BY season, day
"""
df_test = pd.read_sql_query(query, conn, params=latest_seasons)

# Betting logic
wallet = 100.0 # Starting units
unit_size = 5.0 # Bet 5 units per play
bet_history = []

for season in latest_seasons:
    season_df = df_test[df_test['season'] == season]
    team_stats = {}
    team_streaks = {team: ('-', 0) for team in season_df['home'].unique()}
    
    for day in range(1, 31):
        day_matches = season_df[season_df['day'] == day]
        if day_matches.empty: continue
            
        ranks = {}
        if len(team_stats) > 0:
            ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
            ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
            
        for _, row in day_matches.iterrows():
            h_team, a_team = row['home'], row['away']
            h_score, a_score = row['h'], row['a']
            outcome = row['outcome']
            total = h_score + a_score
            
            if h_team in team_stats and a_team in team_stats and day > 3:
                h_rank = ranks.get(h_team, 16)
                a_rank = ranks.get(a_team, 16)
                
                def get_rank_bracket(r):
                    if r <= 4: return 'Top4'
                    if r <= 8: return 'UpMid'
                    if r <= 12: return 'LowMid'
                    return 'Bot4'
                    
                hrb = get_rank_bracket(h_rank)
                arb = get_rank_bracket(a_rank)
                hst = f"{team_streaks[h_team][0]}{team_streaks[h_team][1]}"
                ast = f"{team_streaks[a_team][0]}{team_streaks[a_team][1]}"
                
                bet_placed = False
                won = False
                odds = 0.0
                bet_type = ""
                
                # 1. The Absolute Crush + U3.5
                if hrb == 'Top4' and arb == 'Bot4' and hst == 'W4' and ast == 'L3':
                    bet_type = "Absolute Crush (Home + U3.5)"
                    odds = 1.95
                    bet_placed = True
                    if outcome == 'HOME' and total < 3.5: won = True
                
                # 2. Gravity Correction
                elif hrb == 'Top4' and arb == 'LowMid' and hst == 'W2' and ast == 'W3':
                    bet_type = "Gravity Correction (Home Win)"
                    odds = 1.55
                    bet_placed = True
                    if outcome == 'HOME': won = True
                    
                # 3. False Hope
                elif hrb == 'Bot4' and arb == 'Top4' and hst == 'W2' and ast == 'W2':
                    bet_type = "False Hope (Away Win)"
                    odds = 1.60
                    bet_placed = True
                    if outcome == 'AWAY': won = True
                    
                # 4. Top 4 Streak Snap (X2 Double Chance)
                elif hrb == 'Top4' and arb == 'Top4' and hst == 'L1' and ast == 'W6':
                    bet_type = "Top 4 Snap (X2)"
                    odds = 1.45
                    bet_placed = True
                    if outcome in ['AWAY', 'DRAW']: won = True
                    
                # 5. Bottom 4 Stagnation (1X Double Chance)
                elif hrb == 'Bot4' and arb == 'Bot4' and hst == 'L5' and ast == 'L1':
                    bet_type = "Bot 4 Stagnation (1X)"
                    odds = 1.40
                    bet_placed = True
                    if outcome in ['HOME', 'DRAW']: won = True
                    
                # 6. Heavyweight Standoff (Draw)
                elif hrb == 'Top4' and arb == 'Top4' and hst == 'D2' and ast == 'W2':
                    bet_type = "Heavyweight Standoff (Draw)"
                    odds = 3.20
                    bet_placed = True
                    if outcome == 'DRAW': won = True

                if bet_placed:
                    if won:
                        profit = unit_size * (odds - 1)
                        wallet += profit
                        res = "WON"
                    else:
                        profit = -unit_size
                        wallet -= unit_size
                        res = "LOST"
                    
                    bet_history.append({
                        'season': season,
                        'day': day,
                        'bet': bet_type,
                        'odds': odds,
                        'result': res,
                        'profit': profit,
                        'wallet': wallet
                    })
                    
        # Update Stats
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            
            team_stats[h_team]['gf'] += h; team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a; team_stats[a_team]['gd'] += (a - h)
            
            def update_streak(team, result):
                curr_type, curr_len = team_streaks[team]
                if curr_type == result: team_streaks[team] = (result, curr_len + 1)
                else: team_streaks[team] = (result, 1)
            
            if h > a: 
                team_stats[h_team]['pts'] += 3
                update_streak(h_team, 'W'); update_streak(a_team, 'L')
            elif h == a:
                team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
                update_streak(h_team, 'D'); update_streak(a_team, 'D')
            else: 
                team_stats[a_team]['pts'] += 3
                update_streak(h_team, 'L'); update_streak(a_team, 'W')

df_res = pd.DataFrame(bet_history)

print("--- 5-SEASON BACKTEST RESULTS ---")
if len(df_res) == 0:
    print("No bets triggered in the last 5 seasons. (Streaks are rare).")
else:
    total_bets = len(df_res)
    total_wins = len(df_res[df_res['result'] == 'WON'])
    win_rate = total_wins / total_bets * 100
    
    print(f"Total Bets Placed: {total_bets}")
    print(f"Total Wins: {total_wins}")
    print(f"Total Losses: {total_bets - total_wins}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Starting Bankroll: 100.0 Units")
    print(f"Ending Bankroll: {wallet:.1f} Units")
    print(f"Total ROI: {((wallet - 100.0) / 100.0) * 100:.1f}%\n")
    
    print("Performance by Bet Type:")
    perf = df_res.groupby('bet').agg(
        Bets=('result', 'count'),
        Wins=('result', lambda x: (x=='WON').sum()),
        Profit=('profit', 'sum')
    )
    perf['Win%'] = (perf['Wins'] / perf['Bets'] * 100).round(1)
    print(perf.to_string())
    
    print("\nLast 10 Chronological Bets:")
    print(df_res.tail(10)[['season', 'day', 'bet', 'result', 'profit', 'wallet']].to_string(index=False))
