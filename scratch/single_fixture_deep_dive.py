import sys
import pandas as pd
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def main():
    df, _ = extract_panel_data_with_standings()
    
    target_home = "Liverpool"
    target_away = "Chelsea"
    
    # Check if this exact fixture exists, if not use a common one
    fixture_df = df[(df['home'] == target_home) & (df['away'] == target_away)]
    
    if len(fixture_df) == 0:
        # Fallback to another big fixture if 'Chelsea' is named differently (e.g. London Blues)
        target_home = "Liverpool"
        target_away = "London Blues"
        fixture_df = df[(df['home'] == target_home) & (df['away'] == target_away)]
        if len(fixture_df) == 0:
             target_home = "Manchester Blue"
             target_away = "Manchester Red"
             fixture_df = df[(df['home'] == target_home) & (df['away'] == target_away)]

    print(f"\n--- FULL MACRO & MICRO BREAKDOWN FOR: {target_home} vs {target_away} ---")
    print(f"{'MACRO':<10} | {'MICRO':<10} | {'MATCHES':<7} | {'HW':<5} | {'DR':<5} | {'AW':<5}")
    print("-" * 60)
    
    # Group by both Macro and Micro
    grouped = fixture_df.groupby(['home_tier', 'away_tier', 'home_micro', 'away_micro'])
    
    results = []
    
    for (ht, at, hm, am), group in grouped:
        matches = len(group)
        hw = sum(group['h'] > group['a'])
        dr = sum(group['h'] == group['a'])
        aw = sum(group['h'] < group['a'])
        
        hw_pct = (hw / matches) * 100
        dr_pct = (dr / matches) * 100
        aw_pct = (aw / matches) * 100
        
        results.append({
            'mac': f"{ht} v {at}",
            'mic': f"{hm} v {am}",
            'matches': matches,
            'hw': hw_pct,
            'dr': dr_pct,
            'aw': aw_pct
        })
        
    # Sort by number of matches
    results.sort(key=lambda x: x['matches'], reverse=True)
    
    for r in results:
        print(f"{r['mac']:<10} | {r['mic']:<10} | {r['matches']:<7} | {r['hw']:>4.0f}% | {r['dr']:>4.0f}% | {r['aw']:>4.0f}%")

if __name__ == '__main__':
    main()
