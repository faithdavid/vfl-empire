import pandas as pd
import numpy as np
import sqlite3
import json

def test_true_bulletproof_locks():
    DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT season, day, home, away, h, a, total, gg, o25 FROM matches WHERE season IS NOT NULL AND total IS NOT NULL"
    df = pd.read_sql_query(query, conn)
    conn.close()

    df['season_num'] = df['season'].astype(str).str.extract(r'(\d+)').astype(float)
    max_season = df['season_num'].max()
    df['season_num'] = df['season_num'].fillna(max_season)

    home_results = df[['season', 'season_num', 'day', 'home', 'h', 'a']].copy()
    home_results.rename(columns={'home': 'team', 'h': 'gf', 'a': 'ga'}, inplace=True)
    home_results['pts'] = np.where(home_results['gf'] > home_results['ga'], 3, np.where(home_results['gf'] == home_results['ga'], 1, 0))

    away_results = df[['season', 'season_num', 'day', 'away', 'a', 'h']].copy()
    away_results.rename(columns={'away': 'team', 'a': 'gf', 'h': 'ga'}, inplace=True)
    away_results['pts'] = np.where(away_results['gf'] > away_results['ga'], 3, np.where(away_results['gf'] == away_results['ga'], 1, 0))

    df_teams = pd.concat([home_results, away_results], ignore_index=True)
    df_teams.sort_values(['season', 'day'], inplace=True)
    df_teams['gd'] = df_teams['gf'] - df_teams['ga']

    df_teams['cum_pts'] = df_teams.groupby(['season', 'team'])['pts'].cumsum()
    df_teams['cum_gd'] = df_teams.groupby(['season', 'team'])['gd'].cumsum()
    df_teams['cum_gf'] = df_teams.groupby(['season', 'team'])['gf'].cumsum()

    # The 1-Matchday Lag (shift(1)) so we use standings from the day before!
    df_teams['prev_pts'] = df_teams.groupby(['season', 'team'])['cum_pts'].shift(1).fillna(0)
    df_teams['prev_gd'] = df_teams.groupby(['season', 'team'])['cum_gd'].shift(1).fillna(0)
    df_teams['prev_gf'] = df_teams.groupby(['season', 'team'])['cum_gf'].shift(1).fillna(0)

    df_teams.sort_values(['season', 'day', 'prev_pts', 'prev_gd', 'prev_gf'], ascending=[True, True, False, False, False], inplace=True)
    df_teams['rank'] = df_teams.groupby(['season', 'day']).cumcount() + 1
    
    df_teams['lag_tier'] = pd.cut(df_teams['rank'], bins=[0, 4, 8, 12, 16], labels=['T1', 'T2', 'T3', 'T4'])

    home_ranks = df_teams[['season', 'day', 'team', 'lag_tier']].rename(columns={'team': 'home', 'lag_tier': 'home_tier'})
    away_ranks = df_teams[['season', 'day', 'team', 'lag_tier']].rename(columns={'team': 'away', 'lag_tier': 'away_tier'})

    df = df.merge(home_ranks, on=['season', 'day', 'home'], how='left')
    df = df.merge(away_ranks, on=['season', 'day', 'away'], how='left')
    
    df['phase'] = np.ceil(df['day'] / 2.0).astype(int)
    
    # Filter only phase >= 2 since MD 1 has no "day before"
    df_valid = df[df['phase'] >= 2].copy()
    
    all_seasons = sorted(df_valid['season_num'].dropna().unique())
    test_seasons = all_seasons[-15:]
    df_train = df_valid[~df_valid['season_num'].isin(test_seasons)].copy()
    df_test = df_valid[df_valid['season_num'].isin(test_seasons)].sort_values(by=['season_num', 'day'])

    print(f"Training on {len(all_seasons)-15} seasons. Testing on last 15 seasons...")

    grouped = df_train.groupby(['home', 'away', 'home_tier', 'away_tier', 'phase'], observed=False)
    locks_db = {}
    locks_count = 0
    
    for name, group in grouped:
        home, away, h_tier, a_tier, phase = name
        matches = len(group)
        if matches < 10: continue
            
        hw = sum(group['h'] > group['a']) / matches
        dr = sum(group['h'] == group['a']) / matches
        aw = sum(group['h'] < group['a']) / matches
        
        lock_code = None
        if hw == 1.0: lock_code = 'hw'
        elif dr == 1.0: lock_code = 'dr'
        elif aw == 1.0: lock_code = 'aw'
        
        if lock_code:
            key = (str(home), str(away), str(h_tier), str(a_tier), int(phase))
            locks_db[key] = lock_code
            locks_count += 1

    print(f"Total 100% Locks Found on Training Set: {locks_count}")
    
    print("\n===================================================================================================")
    print(" 🎯 INDEPENDENT BULLETPROOF ORACLE: LAST 15 SEASONS BACKTEST")
    print("===================================================================================================")
    
    total_bets = 0
    wins = 0
    losses = 0
    
    print(f"{'SEASON':<8} | {'MD':<3} | {'FIXTURE':<30} | {'LAG TIERS':<10} | {'PREDICTION':<10} | {'SCORE':<5} | {'RESULT'}")
    print("-" * 100)
    
    for _, row in df_test.iterrows():
        key = (str(row['home']), str(row['away']), str(row['home_tier']), str(row['away_tier']), int(row['phase']))
        
        if key in locks_db:
            prediction = locks_db[key]
            
            h_goals = row['h']
            a_goals = row['a']
            if h_goals > a_goals: actual = 'hw'
            elif h_goals == a_goals: actual = 'dr'
            else: actual = 'aw'
            
            total_bets += 1
            if prediction == actual:
                wins += 1
                match_result = "✅ WON"
            else:
                losses += 1
                match_result = "❌ LOST"
                
            pred_str = "HOME WIN" if prediction == 'hw' else "AWAY WIN" if prediction == 'aw' else "DRAW"
            score = f"{int(h_goals)}-{int(a_goals)}"
            fixture_str = f"{row['home']} vs {row['away']}"
            tiers_str = f"{row['home_tier']} v {row['away_tier']}"
            
            print(f"{int(row['season_num']):<8} | {int(row['day']):<3} | {fixture_str:<30} | {tiers_str:<10} | {pred_str:<10} | {score:<5} | {match_result}")

    print("\n===================================================================================================")
    print(" 🏁 FINAL RESULTS (LAST 15 SEASONS OOS)")
    print("===================================================================================================")
    print(f"Total Bets Placed:     {total_bets}")
    print(f"Total Wins:            {wins}")
    print(f"Total Losses:          {losses}")
    if total_bets > 0:
        print(f"Accuracy:              {(wins/total_bets)*100:.2f}%")

if __name__ == '__main__':
    test_true_bulletproof_locks()
