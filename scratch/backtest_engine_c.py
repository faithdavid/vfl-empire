import pandas as pd
import json
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def main():
    print("Loading historical data...")
    df, max_s = extract_panel_data_with_standings()
    
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json", "r") as f:
        micro_data = json.load(f)
    micro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in micro_data if r['occurrences'] >= 10 }
    
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", "r") as f:
        macro_data = json.load(f)
    macro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in macro_data if r['occurrences'] >= 10 }

    # Find the most recently completed FULL season (meaning it has ~30 matchdays recorded)
    # The absolute max_season might still be ongoing.
    season_counts = df['season'].value_counts()
    recent_seasons = sorted(df['season'].unique(), key=lambda s: float(str(s).replace('vf:season:', '').replace('VFLM ', '0')) if 'VFLM' not in str(s) else 0, reverse=True)
    
    # Pick the most recent season that has at least 200 matches (full season has 240)
    target_season = None
    for s in recent_seasons:
        if season_counts[s] > 200:
            target_season = s
            break
            
    if not target_season:
        print("No full season found.")
        return

    print(f"\n--- BACKTESTING ENGINE C ON SEASON: {target_season} ---")
    
    season_df = df[df['season'] == target_season].copy()
    season_df.sort_values('day', inplace=True)
    
    stats = {
        'confluence': {'total': 0, 'hits': 0},
        'micro': {'total': 0, 'hits': 0},
        'macro': {'total': 0, 'hits': 0}
    }
    
    markets = [
        ('u15_ind', 'w_u15_rate'), ('o15_ind', 'w_o15_rate'),
        ('u25_ind', 'w_u25_rate'), ('o25_ind', 'w_o25_rate'),
        ('u35_ind', 'w_u35_rate'), ('o35_ind', 'w_o35_rate'),
        ('gg', 'w_gg_rate')
    ]
    
    for day in sorted(season_df['day'].unique()):
        day_df = season_df[season_df['day'] == day]
        for _, match in day_df.iterrows():
            # Actual results
            actual_results = {
                'u15_ind': match['total'] < 1.5,
                'o15_ind': match['total'] > 1.5,
                'u25_ind': match['total'] < 2.5,
                'o25_ind': match['total'] > 2.5,
                'u35_ind': match['total'] < 3.5,
                'o35_ind': match['total'] > 3.5,
                'gg': match['gg'] == 1,
            }
            
            macro_k = (match['home'], match['away'], match['home_tier'], match['away_tier'])
            micro_k = (match['home'], match['away'], match['home_micro'], match['away_micro'])
            
            mac_r = macro_lookup.get(macro_k, {})
            mic_r = micro_lookup.get(micro_k, {})
            
            for act_key, rate_key in markets:
                mac_val = mac_r.get(rate_key, 0)
                mic_val = mic_r.get(rate_key, 0)
                
                # Confluence
                if mac_val >= 0.80 and mic_val >= 0.80:
                    stats['confluence']['total'] += 1
                    if actual_results[act_key]:
                        stats['confluence']['hits'] += 1
                elif mic_val >= 0.85:
                    stats['micro']['total'] += 1
                    if actual_results[act_key]:
                        stats['micro']['hits'] += 1
                elif mac_val >= 0.85:
                    stats['macro']['total'] += 1
                    if actual_results[act_key]:
                        stats['macro']['hits'] += 1

    print("\n--- RESULTS ---")
    for cat, data in stats.items():
        if data['total'] > 0:
            print(f"{cat.upper()} LOCKS: {data['hits']} / {data['total']} ({data['hits']/data['total']*100:.1f}%)")
        else:
            print(f"{cat.upper()} LOCKS: 0")

if __name__ == '__main__':
    main()
