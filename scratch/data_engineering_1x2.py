import pandas as pd
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def test_grouping(df, group_cols, min_occurrences=20):
    # Group the dataframe
    grouped = df.groupby(group_cols)
    
    max_hit_rate = 0
    best_lock = None
    
    for name, group in grouped:
        matches = len(group)
        if matches < min_occurrences:
            continue
            
        hw = sum(group['h'] > group['a']) / matches
        dr = sum(group['h'] == group['a']) / matches
        aw = sum(group['h'] < group['a']) / matches
        
        dominant = max(hw, dr, aw)
        if dominant > max_hit_rate:
            max_hit_rate = dominant
            best_lock = f"{name} ({dominant*100:.1f}%)"
            
    return max_hit_rate * 100, best_lock

def main():
    df, _ = extract_panel_data_with_standings()
    
    grouping_strategies = [
        ("1. Exact Teams Only", ['home', 'away']),
        ("2. Exact Tiers Only", ['home_tier', 'away_tier']),
        ("3. Home Team vs Away Tier", ['home', 'away_tier']),
        ("4. Home Tier vs Away Team", ['home_tier', 'away']),
        ("5. Home Team + Home Tier", ['home', 'home_tier']),
        ("6. Away Team + Away Tier", ['away', 'away_tier']),
        ("7. Home Team + Exact Tiers", ['home', 'home_tier', 'away_tier']),
        ("8. Away Team + Exact Tiers", ['away', 'home_tier', 'away_tier'])
    ]
    
    print("\n========================================================")
    print(" 🧬 THE MATHEMATICAL CEILING OF VIRTUAL FOOTBALL")
    print(" Minimum Occurrences: 20 Matches")
    print("========================================================")
    
    results = []
    for name, cols in grouping_strategies:
        max_rate, best_lock = test_grouping(df, cols, min_occurrences=20)
        results.append((name, max_rate, best_lock))
        
    results.sort(key=lambda x: x[1], reverse=True)
    
    print(f"{'GROUPING STRUCTURE':<35} | {'MAX HIT RATE':<15} | {'BEST EXAMPLE'}")
    print("-" * 85)
    for name, rate, best_lock in results:
        print(f"{name:<35} | {rate:>12.1f}% | {best_lock}")

if __name__ == '__main__':
    main()
