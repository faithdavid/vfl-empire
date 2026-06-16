import pandas as pd
import sys
import numpy as np
import json

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def run_phase_locks_backtest(df):
    # Load the locks we generated
    try:
        with open('/home/ubuntu/faith-workspace/vfl-empire/data/phase_fixture_locks.json', 'r') as f:
            locks_list = json.load(f)
    except FileNotFoundError:
        print("Locks database not found.")
        return
        
    # Convert list of dicts to a fast lookup dictionary
    # Key: (home, away, home_tier, away_tier, phase) -> Value: lock type
    locks_db = {}
    for lock in locks_list:
        key = (lock['home'], lock['away'], lock['home_tier'], lock['away_tier'], lock['phase'])
        locks_db[key] = lock['lock']
        
    df['season_phase'] = np.ceil(df['day'] / 2.0).astype(int)
    
    # Get the last 10 full seasons
    all_seasons = sorted(df['season_num'].dropna().unique())
    test_seasons = all_seasons[-10:]
    df_test = df[df['season_num'].isin(test_seasons)].copy()
    
    print("\n==================================================================================")
    print(" 🎯 PHASE-AWARE ORACLE: BACKTESTING THE LAST 10 SEASONS")
    print("==================================================================================")
    
    total_bets = 0
    wins = 0
    losses = 0
    
    bets_per_season = {season: 0 for season in test_seasons}
    
    for _, row in df_test.iterrows():
        key = (row['home'], row['away'], row['home_tier'], row['away_tier'], row['season_phase'])
        
        if key in locks_db:
            prediction = locks_db[key]
            
            # Determine actual result
            h_goals = row['h']
            a_goals = row['a']
            if h_goals > a_goals: actual = 'hw'
            elif h_goals == a_goals: actual = 'dr'
            else: actual = 'aw'
            
            total_bets += 1
            bets_per_season[row['season_num']] += 1
            
            if prediction == actual:
                wins += 1
            else:
                losses += 1
                
    print(f"Total Seasons Tested:  10")
    print(f"Total Bets Placed:     {total_bets}")
    print(f"Total Wins:            {wins}")
    print(f"Total Losses:          {losses}")
    
    if total_bets > 0:
        print(f"Overall Accuracy:      {(wins/total_bets)*100:.1f}%")
        
    print("\nBETS PLACED PER SEASON:")
    for season in test_seasons:
        print(f"  Season {int(season)}: {bets_per_season[season]} bets placed")

def main():
    print("Extracting panel data...")
    df, _ = extract_panel_data_with_standings()
    run_phase_locks_backtest(df)

if __name__ == '__main__':
    main()
