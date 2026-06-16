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
    
    total_unfilt_hits = 0
    total_unfilt_matches = 0
    total_filt_hits = 0
    total_filt_matches = 0
    
    perf_unfilt = 0
    perf_filt = 0 # 100% win rate on a day where at least 4 bets were placed
    
    for target_season in target_seasons:
        print(f"\n=========================================")
        print(f" SEASON: {target_season}")
        print(f"=========================================")
        
        season_df = df[df['season'] == target_season].copy()
        days = sorted(season_df['day'].unique())
        
        s_unfilt_hits = 0
        s_unfilt_matches = 0
        s_filt_hits = 0
        s_filt_matches = 0
        
        for day in days:
            day_df = season_df[season_df['day'] == day]
            
            d_unfilt_hits = 0
            d_unfilt_matches = 0
            d_filt_hits = 0
            d_filt_matches = 0
            
            for _, match in day_df.iterrows():
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
                        
                if not best_market:
                    continue

                mac_t = (match['home_tier'], match['away_tier'])
                mic_t = (match['home_micro'], match['away_micro'])
                teams = (match['home'], match['away'])
                
                chaos_flag = False
                if mac_t in [("T3", "T2"), ("T1", "T3"), ("T2", "T1")]:
                    chaos_flag = True
                elif mic_t in [("E", "D"), ("B", "A"), ("C", "A")]:
                    chaos_flag = True
                elif teams in [("Everton", "Manchester Blue"), ("Fulham", "West Ham"), ("Wolverhampton", "Tottenham")]:
                    chaos_flag = True
                    
                is_hit = actual_results[best_market]
                
                # Unfiltered Tracking
                d_unfilt_matches += 1
                if is_hit: d_unfilt_hits += 1
                
                # Filtered Tracking
                if not chaos_flag:
                    d_filt_matches += 1
                    if is_hit: d_filt_hits += 1

            # Tally Season & Grand Totals
            s_unfilt_matches += d_unfilt_matches
            s_unfilt_hits += d_unfilt_hits
            s_filt_matches += d_filt_matches
            s_filt_hits += d_filt_hits
            
            # Perfect Matchday Logic
            perf_u_flag = " "
            perf_f_flag = " "
            if d_unfilt_matches > 0 and d_unfilt_hits == d_unfilt_matches:
                perf_unfilt += 1
                perf_u_flag = "🔥"
            
            if d_filt_matches >= 4 and d_filt_hits == d_filt_matches:
                perf_filt += 1
                perf_f_flag = "🔥"
                
            print(f"MD {int(day):02d} | UNFILT: {d_unfilt_hits}/{d_unfilt_matches} {perf_u_flag} | FILT: {d_filt_hits}/{d_filt_matches} {perf_f_flag}")
            
        total_unfilt_matches += s_unfilt_matches
        total_unfilt_hits += s_unfilt_hits
        total_filt_matches += s_filt_matches
        total_filt_hits += s_filt_hits
        
        print(f"\n--- {target_season} SUMMARY ---")
        print(f"Unfiltered: {s_unfilt_hits}/{s_unfilt_matches} ({s_unfilt_hits/s_unfilt_matches*100:.1f}%)")
        if s_filt_matches > 0:
            print(f"Filtered:   {s_filt_hits}/{s_filt_matches} ({s_filt_hits/s_filt_matches*100:.1f}%)")
            
    print(f"\n=========================================")
    print(f" GRAND TOTAL (10 SEASONS)")
    print(f"=========================================")
    print(f"UNFILTERED: {total_unfilt_hits}/{total_unfilt_matches} ({total_unfilt_hits/total_unfilt_matches*100:.1f}%)")
    print(f"FILTERED:   {total_filt_hits}/{total_filt_matches} ({total_filt_hits/total_filt_matches*100:.1f}%)")
    print(f"")
    print(f"PERFECT UNFILTERED MATCHDAYS (8/8): {perf_unfilt}")
    print(f"PERFECT FILTERED MATCHDAYS (N/N, N>=4): {perf_filt}")

if __name__ == '__main__':
    main()
