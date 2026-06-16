import pandas as pd
import sys
import numpy as np
import json

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def run_phase_locks_detailed_backtest(df):
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
    
    # Get the last 10 full seasons
    all_seasons = sorted(df['season_num'].dropna().unique())
    test_seasons = all_seasons[-10:]
    df_test = df[df['season_num'].isin(test_seasons)].copy()
    
    print("\n===================================================================================================")
    print(" 🔍 EXACT VFLM MATCH LOGS: THE 25 '100% LOCKS' FROM THE LAST 10 SEASONS")
    print("===================================================================================================")
    print(f"{'SEASON':<8} | {'MD':<3} | {'PHASE':<6} | {'FIXTURE':<30} | {'TIERS':<10} | {'PREDICTION':<10} | {'SCORE':<5} | {'RESULT'}")
    print("-" * 100)
    
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
            
            score = f"{int(h_goals)}-{int(a_goals)}"
            match_result = "✅ WON" if prediction == actual else "❌ LOST"
            
            pred_str = "HOME WIN" if prediction == 'hw' else "AWAY WIN" if prediction == 'aw' else "DRAW"
            tiers_str = f"{row['home_tier']} v {row['away_tier']}"
            fixture_str = f"{row['home']} vs {row['away']}"
            
            print(f"{int(row['season_num']):<8} | {int(row['day']):<3} | Ph {int(row['season_phase']):<2} | {fixture_str:<30} | {tiers_str:<10} | {pred_str:<10} | {score:<5} | {match_result}")

def main():
    df, _ = extract_panel_data_with_standings()
    run_phase_locks_detailed_backtest(df)

if __name__ == '__main__':
    main()
