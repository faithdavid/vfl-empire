import pandas as pd
import json
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def main():
    print("Extracting data...")
    df, max_s = extract_panel_data_with_standings()
    
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json", "r") as f:
        micro_data = json.load(f)
        
    micro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in micro_data if r['occurrences'] >= 10 }
    
    overlaps = {
        'O2.5 & U3.5': {'total': 0, 'o25_hit': 0, 'u35_hit': 0, 'both_hit': 0, 'o15_hit': 0},
        'GG & U2.5': {'total': 0, 'gg_hit': 0, 'u25_hit': 0, 'both_hit': 0, 'u35_hit': 0},
        'HomeWin & U2.5': {'total': 0, 'hw_hit': 0, 'u25_hit': 0, 'both_hit': 0, '1x_hit': 0},
        'AwayWin & U2.5': {'total': 0, 'aw_hit': 0, 'u25_hit': 0, 'both_hit': 0, 'x2_hit': 0},
        'GG & O2.5': {'total': 0, 'gg_hit': 0, 'o25_hit': 0, 'both_hit': 0, 'o15_hit': 0}
    }

    for _, match in df.iterrows():
        mic_k = (match['home'], match['away'], match['home_micro'], match['away_micro'])
        
        if mic_k in micro_lookup:
            row = micro_lookup[mic_k]
            
            o25_r = row.get('w_o25_rate') or 0
            u35_r = row.get('w_u35_rate') or 0
            u25_r = row.get('w_u25_rate') or 0
            gg_r = row.get('w_gg_rate') or 0
            hw_r = row.get('w_1_rate') or 0
            aw_r = row.get('w_2_rate') or 0
            
            if o25_r >= 0.95 and u35_r >= 0.95:
                overlaps['O2.5 & U3.5']['total'] += 1
                if match['total'] > 2.5: overlaps['O2.5 & U3.5']['o25_hit'] += 1
                if match['total'] < 3.5: overlaps['O2.5 & U3.5']['u35_hit'] += 1
                if match['total'] == 3: overlaps['O2.5 & U3.5']['both_hit'] += 1
                if match['total'] > 1.5: overlaps['O2.5 & U3.5']['o15_hit'] += 1
                
            if gg_r >= 0.95 and u25_r >= 0.95:
                overlaps['GG & U2.5']['total'] += 1
                if match['gg'] == 1: overlaps['GG & U2.5']['gg_hit'] += 1
                if match['total'] < 2.5: overlaps['GG & U2.5']['u25_hit'] += 1
                if match['gg'] == 1 and match['total'] < 2.5: overlaps['GG & U2.5']['both_hit'] += 1
                if match['total'] < 3.5: overlaps['GG & U2.5']['u35_hit'] += 1
                
            if hw_r >= 0.95 and u25_r >= 0.95:
                overlaps['HomeWin & U2.5']['total'] += 1
                if match['h'] > match['a']: overlaps['HomeWin & U2.5']['hw_hit'] += 1
                if match['total'] < 2.5: overlaps['HomeWin & U2.5']['u25_hit'] += 1
                if match['h'] > match['a'] and match['total'] < 2.5: overlaps['HomeWin & U2.5']['both_hit'] += 1
                if match['h'] >= match['a']: overlaps['HomeWin & U2.5']['1x_hit'] += 1
                
            if aw_r >= 0.95 and u25_r >= 0.95:
                overlaps['AwayWin & U2.5']['total'] += 1
                if match['h'] < match['a']: overlaps['AwayWin & U2.5']['aw_hit'] += 1
                if match['total'] < 2.5: overlaps['AwayWin & U2.5']['u25_hit'] += 1
                if match['h'] < match['a'] and match['total'] < 2.5: overlaps['AwayWin & U2.5']['both_hit'] += 1
                if match['h'] <= match['a']: overlaps['AwayWin & U2.5']['x2_hit'] += 1
                
            if gg_r >= 0.95 and o25_r >= 0.95:
                overlaps['GG & O2.5']['total'] += 1
                if match['gg'] == 1: overlaps['GG & O2.5']['gg_hit'] += 1
                if match['total'] > 2.5: overlaps['GG & O2.5']['o25_hit'] += 1
                if match['gg'] == 1 and match['total'] > 2.5: overlaps['GG & O2.5']['both_hit'] += 1
                if match['total'] > 1.5: overlaps['GG & O2.5']['o15_hit'] += 1

    for overlap, stats in overlaps.items():
        if stats['total'] > 0:
            print(f"\n--- OVERLAP: {overlap} ---")
            print(f"Total Occurrences: {stats['total']}")
            for k, v in stats.items():
                if k != 'total':
                    print(f"  {k}: {v} ({v/stats['total']*100:.1f}%)")

if __name__ == '__main__':
    main()
