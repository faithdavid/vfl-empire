import sys
import json
import pandas as pd
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def build_locks_dictionary(threshold=0.75, min_occurrences=3):
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", "r") as f:
        data = json.load(f)
        
    locks = {}
    for row in data:
        if row['occurrences'] < min_occurrences:
            continue
            
        key = (row['home'], row['away'], row['home_tier'], row['away_tier'])
        
        if row['w_1_rate'] >= threshold:
            locks[key] = ('hw', row['w_1_rate'])
        elif row['w_x_rate'] >= threshold:
            locks[key] = ('dr', row['w_x_rate'])
        elif row['w_2_rate'] >= threshold:
            locks[key] = ('aw', row['w_2_rate'])
            
    return locks

def main():
    print("Building 1X2 Independent Locks Dictionary (75%+ threshold)...")
    locks = build_locks_dictionary()
    print(f"Total Structural Locks Found: {len(locks)}")
    
    print("Loading historical panel data...")
    df, _ = extract_panel_data_with_standings()
    
    # Backtest over ALL seasons to see the full financial picture
    print(f"Backtesting over ALL Seasons...")
    
    total_bets = 0
    total_wins = 0
    total_losses = 0
    
    # Assume 10 Naira bet, assume average odds of 1.70 for Home/Away and 3.0 for Draw
    # Since we don't have historical odds, we use these conservative estimates to calculate equity.
    equity = 0
    stake = 10
    
    market_stats = {
        'hw': {'bets': 0, 'wins': 0, 'profit': 0},
        'dr': {'bets': 0, 'wins': 0, 'profit': 0},
        'aw': {'bets': 0, 'wins': 0, 'profit': 0}
    }
    
    for _, match in df.iterrows():
        key = (match['home'], match['away'], match['home_tier'], match['away_tier'])
        
        if key in locks:
            prediction, conf = locks[key]
            
            # Determine actual result
            h_goals = match['h']
            a_goals = match['a']
            if h_goals > a_goals: actual = 'hw'
            elif h_goals == a_goals: actual = 'dr'
            else: actual = 'aw'
            
            total_bets += 1
            market_stats[prediction]['bets'] += 1
            
            # Simulated Odds
            if prediction == 'dr': odds = 3.00
            elif prediction == 'aw': odds = 2.10
            else: odds = 1.70
            
            if prediction == actual:
                total_wins += 1
                market_stats[prediction]['wins'] += 1
                profit = (stake * odds) - stake
                equity += profit
                market_stats[prediction]['profit'] += profit
            else:
                total_losses += 1
                equity -= stake
                market_stats[prediction]['profit'] -= stake

    print("\n========================================================")
    print(" 🎯 1X2 INDEPENDENT LOCKS BACKTEST (ALL TIME)")
    print("========================================================")
    print(f"Total Locks Bet:       {total_bets}")
    print(f"Total Wins:            {total_wins}")
    print(f"Total Losses:          {total_losses}")
    
    if total_bets > 0:
        accuracy = (total_wins / total_bets) * 100
        print(f"OVERALL ACCURACY:      {accuracy:.2f}%")
        print(f"NET PROFIT (₦10/bet):  ₦{equity:.2f}\n")
        
        print("BREAKDOWN BY MARKET:")
        for mkt in ['hw', 'dr', 'aw']:
            bets = market_stats[mkt]['bets']
            wins = market_stats[mkt]['wins']
            profit = market_stats[mkt]['profit']
            if bets > 0:
                acc = (wins / bets) * 100
                mkt_name = "Home Win" if mkt == 'hw' else "Draw" if mkt == 'dr' else "Away Win"
                print(f"  {mkt_name:<10} - Bets: {bets:<4} | Wins: {wins:<4} | Accuracy: {acc:>5.1f}% | Profit: ₦{profit:.2f}")

if __name__ == '__main__':
    main()
