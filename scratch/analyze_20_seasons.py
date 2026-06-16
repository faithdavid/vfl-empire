import pandas as pd
import json
import sys
from collections import Counter
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
        if len(target_seasons) == 20:
            break

    markets = [
        ('u15_ind', 'w_u15_rate'), ('o15_ind', 'w_o15_rate'),
        ('u25_ind', 'w_u25_rate'), ('o25_ind', 'w_o25_rate'),
        ('u35_ind', 'w_u35_rate'), ('o35_ind', 'w_o35_rate'),
        ('gg', 'w_gg_rate'),
        ('hw', 'w_1_rate'), ('dr', 'w_x_rate'), ('aw', 'w_2_rate')
    ]
    
    remaining_missed_macro = []
    remaining_missed_micro = []
    remaining_missed_teams = []
    
    chaos_hits = {"T3 vs T2": 0, "T1 vs T3": 0, "T2 vs T1": 0, "Micro E vs D": 0, "Micro B vs A": 0, "Micro C vs A": 0}
    chaos_totals = {"T3 vs T2": 0, "T1 vs T3": 0, "T2 vs T1": 0, "Micro E vs D": 0, "Micro B vs A": 0, "Micro C vs A": 0}

    for target_season in target_seasons:
        season_df = df[df['season'] == target_season].copy()
        
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
                    
            if not best_market:
                continue

            mac_t = (match['home_tier'][-1], match['away_tier'][-1])
            mic_t = (match['home_micro'], match['away_micro'])
            teams = (match['home'], match['away'])
            
            is_hit = actual_results[best_market]
            
            # Chaos Tracker
            chaos_flag = False
            if mac_t == ("T3", "T2"):
                chaos_totals["T3 vs T2"] += 1
                if is_hit: chaos_hits["T3 vs T2"] += 1
                chaos_flag = True
            elif mac_t == ("T1", "T3"):
                chaos_totals["T1 vs T3"] += 1
                if is_hit: chaos_hits["T1 vs T3"] += 1
                chaos_flag = True
            elif mac_t == ("T2", "T1"):
                chaos_totals["T2 vs T1"] += 1
                if is_hit: chaos_hits["T2 vs T1"] += 1
                chaos_flag = True
                
            if mic_t == ("E", "D"):
                chaos_totals["Micro E vs D"] += 1
                if is_hit: chaos_hits["Micro E vs D"] += 1
                chaos_flag = True
            elif mic_t == ("B", "A"):
                chaos_totals["Micro B vs A"] += 1
                if is_hit: chaos_hits["Micro B vs A"] += 1
                chaos_flag = True
            elif mic_t == ("C", "A"):
                chaos_totals["Micro C vs A"] += 1
                if is_hit: chaos_hits["Micro C vs A"] += 1
                chaos_flag = True

            if teams in [("Everton", "Manchester Blue"), ("Fulham", "West Ham"), ("Wolverhampton", "Tottenham")]:
                chaos_flag = True

            # If it's NOT chaos, but it missed, record it for new insights
            if not chaos_flag and not is_hit:
                remaining_missed_macro.append(f"{mac_t[0]} vs {mac_t[1]}")
                remaining_missed_micro.append(f"{mic_t[0]} vs {mic_t[1]}")
                remaining_missed_teams.append(f"{teams[0]} vs {teams[1]}")

    print("\n--- NEW TRAPS: REMAINING MISSES (Filtered Test) ---")
    print("MACRO MATCHUPS CAUSING LOSSES:")
    for combo, count in Counter(remaining_missed_macro).most_common(5):
        print(f"  {combo}: {count} misses")

    print("\nMICRO MATCHUPS CAUSING LOSSES:")
    for combo, count in Counter(remaining_missed_micro).most_common(5):
        print(f"  {combo}: {count} misses")

    print("\nTEAMS CAUSING LOSSES:")
    for combo, count in Counter(remaining_missed_teams).most_common(5):
        print(f"  {combo}: {count} misses")

    print("\n--- CHAOS PERFORMANCE (Unfiltered Insight) ---")
    for category in chaos_totals:
        if chaos_totals[category] > 0:
            print(f"  {category}: {chaos_hits[category]} Hits / {chaos_totals[category]} Matches ({chaos_hits[category]/chaos_totals[category]*100:.1f}%)")

if __name__ == '__main__':
    main()
