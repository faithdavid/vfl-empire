import pandas as pd
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def main():
    df, _ = extract_panel_data_with_standings()
    
    fixture_stats = {}
    
    for _, match in df.iterrows():
        fixture = (match['home'], match['away'])
        
        if fixture not in fixture_stats:
            fixture_stats[fixture] = {'hw': 0, 'dr': 0, 'aw': 0, 'total': 0}
            
        h_goals = match['h']
        a_goals = match['a']
        
        fixture_stats[fixture]['total'] += 1
        if h_goals > a_goals:
            fixture_stats[fixture]['hw'] += 1
        elif h_goals == a_goals:
            fixture_stats[fixture]['dr'] += 1
        else:
            fixture_stats[fixture]['aw'] += 1

    buckets = {
        'hw': {'100': 0, '90-99': 0, '80-89': 0, '70-79': 0, '60-69': 0, '50-59': 0},
        'dr': {'100': 0, '90-99': 0, '80-89': 0, '70-79': 0, '60-69': 0, '50-59': 0},
        'aw': {'100': 0, '90-99': 0, '80-89': 0, '70-79': 0, '60-69': 0, '50-59': 0}
    }
    
    examples = { 'hw': [], 'dr': [], 'aw': [] }

    for fixture, stats in fixture_stats.items():
        total = stats['total']
        if total < 5: continue # Require minimum matches
        
        hw_pct = (stats['hw'] / total) * 100
        dr_pct = (stats['dr'] / total) * 100
        aw_pct = (stats['aw'] / total) * 100
        
        # A fixture only has one dominant outcome
        dominant_market = None
        dominant_pct = max(hw_pct, dr_pct, aw_pct)
        
        if dominant_pct == hw_pct: dominant_market = 'hw'
        elif dominant_pct == aw_pct: dominant_market = 'aw'
        else: dominant_market = 'dr'
        
        if dominant_pct >= 50:
            if dominant_pct == 100:
                buckets[dominant_market]['100'] += 1
                examples[dominant_market].append(f"{fixture[0]} vs {fixture[1]} ({total} matches)")
            elif dominant_pct >= 90:
                buckets[dominant_market]['90-99'] += 1
                if len(examples[dominant_market]) < 10:
                    examples[dominant_market].append(f"{fixture[0]} vs {fixture[1]} ({dominant_pct:.1f}%)")
            elif dominant_pct >= 80:
                buckets[dominant_market]['80-89'] += 1
            elif dominant_pct >= 70:
                buckets[dominant_market]['70-79'] += 1
            elif dominant_pct >= 60:
                buckets[dominant_market]['60-69'] += 1
            else:
                buckets[dominant_market]['50-59'] += 1

    print("\n--- FIXTURE DOMINANCE BUCKETS (Minimum 5 matches) ---")
    print(f"Total Unique Fixtures Analyzed: {len(fixture_stats)}")
    
    for mkt_name, mkt_key in [("HOME WIN", "hw"), ("AWAY WIN", "aw"), ("DRAW", "dr")]:
        print(f"\n[{mkt_name} DOMINANCE]")
        print(f"  100% Hit Rate: {buckets[mkt_key]['100']} fixtures")
        print(f"  90-99% Rate:   {buckets[mkt_key]['90-99']} fixtures")
        print(f"  80-89% Rate:   {buckets[mkt_key]['80-89']} fixtures")
        print(f"  70-79% Rate:   {buckets[mkt_key]['70-79']} fixtures")
        print(f"  60-69% Rate:   {buckets[mkt_key]['60-69']} fixtures")
        print(f"  50-59% Rate:   {buckets[mkt_key]['50-59']} fixtures")
        
        if buckets[mkt_key]['100'] > 0 or buckets[mkt_key]['90-99'] > 0:
            print(f"  -> Top Examples: {', '.join(examples[mkt_key][:5])}")

if __name__ == '__main__':
    main()
