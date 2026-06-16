import pandas as pd
import json
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def main():
    df, max_s = extract_panel_data_with_standings()
    
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json", "r") as f:
        micro_data = json.load(f)
    micro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in micro_data if r['occurrences'] >= 5 }
    
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", "r") as f:
        macro_data = json.load(f)
    macro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in macro_data if r['occurrences'] >= 5 }

    season_counts = df['season'].value_counts()
    recent_seasons = sorted(df['season'].unique(), key=lambda s: float(str(s).replace('vf:season:', '').replace('VFLM ', '0')) if 'VFLM' not in str(s) else 0, reverse=True)
    
    target_seasons = []
    for s in recent_seasons:
        if season_counts[s] >= 200:
            target_seasons.append(s)
        if len(target_seasons) == 10:
            break

    markets = [
        ('u15_ind', 'w_u15_rate'), ('o15_ind', 'w_o15_rate'),
        ('u25_ind', 'w_u25_rate'), ('o25_ind', 'w_o25_rate'),
        ('u35_ind', 'w_u35_rate'), ('o35_ind', 'w_o35_rate'),
        ('gg', 'w_gg_rate'),
        ('hw', 'w_1_rate'), ('dr', 'w_x_rate'), ('aw', 'w_2_rate')
    ]
    
    grand_hits = 0
    grand_total = 0
    skipped_chaos = 0
    
    for target_season in target_seasons:
        season_df = df[df['season'] == target_season].copy()
        
        hits = 0
        total = 0
        
        for _, match in season_df.iterrows():
            actual_results = {
                'u15_ind': match['total'] < 1.5,
                'o15_ind': match['total'] > 1.5,
                'u25_ind': match['total'] < 2.5,
                'o25_ind': match['total'] > 2.5,
                'u35_ind': match['total'] < 3.5,
                'o35_ind': match['total'] > 3.5,
                'gg': match['gg'] == 1,
                'hw': match['h'] > match['a'],
                'dr': match['h'] == match['a'],
                'aw': match['h'] < match['a']
            }
            
            macro_k = (match['home'], match['away'], match['home_tier'], match['away_tier'])
            micro_k = (match['home'], match['away'], match['home_micro'], match['away_micro'])
            
            mac_r = macro_lookup.get(macro_k, {})
            mic_r = micro_lookup.get(micro_k, {})
            
            best_market = None
            best_score = -1
            
            for act_key, rate_key in markets:
                mac_val = mac_r.get(rate_key, 0)
                mic_val = mic_r.get(rate_key, 0)
                
                score = (mac_val + mic_val) / 2 if (mac_val > 0 and mic_val > 0) else max(mac_val, mic_val)
                if 'hw' in act_key or 'aw' in act_key or 'dr' in act_key or '35' in act_key or '15' in act_key:
                    score *= 0.85
                    
                if score > best_score:
                    best_score = score
                    best_market = act_key
                    
            if best_market:
                total += 1
                grand_total += 1
                if actual_results[best_market]:
                    hits += 1
                    grand_hits += 1
                    
        print(f"Season {target_season}: {hits}/{total} ({hits/total*100:.1f}%)")
        
    print(f"\n--- GRAND TOTAL (10 SEASONS w/ CHAOS FILTER) ---")
    print(f"Total Matches Skipped due to Chaos: {skipped_chaos}")
    print(f"Total Matches Predicted: {grand_total}")
    print(f"Successful Hits: {grand_hits}")
    print(f"Overall Hit Rate: {grand_hits/grand_total*100:.1f}%")

if __name__ == '__main__':
    main()
