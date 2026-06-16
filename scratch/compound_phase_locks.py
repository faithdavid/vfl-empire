import pandas as pd
import sys
import numpy as np
import json

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def run_compounding_backtest(df):
    try:
        with open('/home/ubuntu/faith-workspace/vfl-empire/data/phase_fixture_locks.json', 'r') as f:
            locks_list = json.load(f)
    except FileNotFoundError:
        print("Locks database not found.")
        return
        
    locks_db = {}
    for lock in locks_list:
        key = (lock['home'], lock['away'], lock['home_tier'], lock['away_tier'], lock['phase'])
        locks_db[key] = lock['lock']
        
    df['season_phase'] = np.ceil(df['day'] / 2.0).astype(int)
    
    # Get the last 20 full seasons
    all_seasons = sorted(df['season_num'].dropna().unique())
    test_seasons = all_seasons[-20:]
    df_test = df[df['season_num'].isin(test_seasons)].copy()
    
    # Sort CHRONOLOGICALLY! This is critical for compounding!
    df_test = df_test.sort_values(by=['season_num', 'day'])
    
    print("\n===================================================================================================")
    print(" 🚀 PHASE-AWARE ORACLE: FULL COMPOUNDING BACKTEST (LAST 20 SEASONS)")
    print("===================================================================================================")
    
    bankroll = 50.0  # Starting with 50 Naira
    total_bets = 0
    
    print(f"{'SEASON':<8} | {'MD':<3} | {'FIXTURE':<30} | {'PREDICTION':<10} | {'ODDS':<5} | {'RESULT':<6} | {'BANKROLL'}")
    print("-" * 100)
    
    for _, row in df_test.iterrows():
        key = (row['home'], row['away'], row['home_tier'], row['away_tier'], row['season_phase'])
        
        if key in locks_db:
            prediction = locks_db[key]
            
            h_goals = row['h']
            a_goals = row['a']
            if h_goals > a_goals: actual = 'hw'
            elif h_goals == a_goals: actual = 'dr'
            else: actual = 'aw'
            
            # Simulate odds based on market
            if prediction == 'hw':
                odds = 1.70
                pred_str = 'HOME WIN'
            elif prediction == 'aw':
                odds = 2.10
                pred_str = 'AWAY WIN'
            else:
                odds = 3.00
                pred_str = 'DRAW'
                
            total_bets += 1
            fixture_str = f"{row['home']} vs {row['away']}"
            
            if prediction == actual:
                # Compound the returns! (Bet the entire bankroll)
                profit = bankroll * odds
                bankroll = profit
                
                print(f"{int(row['season_num']):<8} | {int(row['day']):<3} | {fixture_str:<30} | {pred_str:<10} | {odds:<5.2f} | {'✅ WON':<6} | ₦{bankroll:,.2f}")
            else:
                bankroll = 0
                print(f"{int(row['season_num']):<8} | {int(row['day']):<3} | {fixture_str:<30} | {pred_str:<10} | {odds:<5.2f} | {'❌ LOST':<6} | ₦{bankroll:,.2f}")
                print("\nBANKRUPT! Compounding failed.")
                break

    print("\n===================================================================================================")
    print(" 🏁 FINAL RESULTS")
    print("===================================================================================================")
    print(f"Total Seasons:      20")
    print(f"Total Bets Placed:  {total_bets}")
    print(f"Starting Bankroll:  ₦50.00")
    print(f"Ending Bankroll:    ₦{bankroll:,.2f}")

def main():
    df, _ = extract_panel_data_with_standings()
    run_compounding_backtest(df)

if __name__ == '__main__':
    main()
