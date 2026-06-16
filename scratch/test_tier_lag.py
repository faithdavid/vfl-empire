import pandas as pd
import sys
import numpy as np
import json

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def run_lag_test():
    # 1. We must recalculate the entire DF using a 2-matchday lag (shift(2))
    print("Extracting raw data and calculating Live Lag Tiers...")
    
    import sqlite3
    DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT season, day, home, away, h, a, total, gg, o25
    FROM matches
    WHERE season IS NOT NULL AND total IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    df['season_num'] = df['season'].astype(str).str.extract(r'(\d+)').astype(float)
    max_season = df['season_num'].max()
    df['season_num'].fillna(max_season, inplace=True)

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

    # THE CRITICAL CHANGE: shift(2) to simulate looking at the table while MD(N-1) is playing!
    df_teams['prev_pts'] = df_teams.groupby(['season', 'team'])['cum_pts'].shift(2).fillna(0)
    df_teams['prev_gd'] = df_teams.groupby(['season', 'team'])['cum_gd'].shift(2).fillna(0)
    df_teams['prev_gf'] = df_teams.groupby(['season', 'team'])['cum_gf'].shift(2).fillna(0)

    df_teams.sort_values(['season', 'day', 'prev_pts', 'prev_gd', 'prev_gf'], ascending=[True, True, False, False, False], inplace=True)
    df_teams['rank'] = df_teams.groupby(['season', 'day']).cumcount() + 1
    
    # Calculate Macro Tiers based on the Lagged Table
    df_teams['lagged_tier'] = pd.cut(df_teams['rank'], bins=[0, 4, 8, 12, 16], labels=['T1', 'T2', 'T3', 'T4'])

    home_ranks = df_teams[['season', 'day', 'team', 'lagged_tier']].rename(columns={'team': 'home', 'lagged_tier': 'home_tier'})
    away_ranks = df_teams[['season', 'day', 'team', 'lagged_tier']].rename(columns={'team': 'away', 'lagged_tier': 'away_tier'})

    df = df.merge(home_ranks, on=['season', 'day', 'home'], how='left')
    df = df.merge(away_ranks, on=['season', 'day', 'away'], how='left')
    
    # Now, test the original 226 locks against this new lagged dataframe
    try:
        with open('/home/ubuntu/faith-workspace/vfl-empire/data/phase_fixture_locks.json', 'r') as f:
            locks_list = json.load(f)
    except Exception as e:
        print("Locks database not found.")
        return

    locks_db = {}
    for lock in locks_list:
        key = (lock['home'], lock['away'], lock['home_tier'], lock['away_tier'], lock['phase'])
        locks_db[key] = lock['lock']
        
    df['season_phase'] = np.ceil(df['day'] / 2.0).astype(int)
    
    # We will backtest on the full 531 seasons to see the exact structural damage of the lag
    print("\n===================================================================================================")
    print(" 🚦 LIVE BOT BOTTLENECK TEST: 2-MATCHDAY LAG ANALYSIS")
    print("===================================================================================================")
    
    total_bets = 0
    wins = 0
    losses = 0
    
    for _, row in df.iterrows():
        # Match using the LAGGED tiers
        key = (row['home'], row['away'], row['home_tier'], row['away_tier'], row['season_phase'])
        
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
            else:
                losses += 1
                
    print(f"Total Bets Placed:     {total_bets}")
    print(f"Total Wins:            {wins}")
    print(f"Total Losses:          {losses}")
    
    if total_bets > 0:
        print(f"Accuracy with Lag:     {(wins/total_bets)*100:.2f}%")
        
if __name__ == '__main__':
    run_lag_test()
