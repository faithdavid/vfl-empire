import pandas as pd
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def main():
    df, _ = extract_panel_data_with_standings()
    
    tier_stats = {}
    
    for _, match in df.iterrows():
        mac_t = (match['home_tier'], match['away_tier'])
        
        if mac_t not in tier_stats:
            tier_stats[mac_t] = {'home_wins': 0, 'draws': 0, 'away_wins': 0, 'total': 0}
            
        h_goals = match['h']
        a_goals = match['a']
        
        tier_stats[mac_t]['total'] += 1
        if h_goals > a_goals:
            tier_stats[mac_t]['home_wins'] += 1
        elif h_goals == a_goals:
            tier_stats[mac_t]['draws'] += 1
        else:
            tier_stats[mac_t]['away_wins'] += 1
            
    print("\n--- 1X2 MARKET ANALYSIS BY MACRO TIER ---")
    
    # Sort logically T1 -> T4 for home, then T1 -> T4 for away
    sorted_tiers = sorted(list(tier_stats.keys()), key=lambda x: (x[0], x[1]))
    
    for mac_t in sorted_tiers:
        stats = tier_stats[mac_t]
        total = stats['total']
        if total == 0: continue
        
        hw_pct = (stats['home_wins'] / total) * 100
        dr_pct = (stats['draws'] / total) * 100
        aw_pct = (stats['away_wins'] / total) * 100
        
        print(f"{mac_t[0]:<3} vs {mac_t[1]:<3} | Total: {total:<5} | HW: {hw_pct:5.1f}% | DR: {dr_pct:5.1f}% | AW: {aw_pct:5.1f}%")

if __name__ == '__main__':
    main()
