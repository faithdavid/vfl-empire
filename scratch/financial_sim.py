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
        if len(target_seasons) == 2:
            break

    markets = [
        ('u15_ind', 'w_u15_rate', 1.30), ('o15_ind', 'w_o15_rate', 1.25),
        ('u25_ind', 'w_u25_rate', 1.75), ('o25_ind', 'w_o25_rate', 1.80),
        ('u35_ind', 'w_u35_rate', 1.25), ('o35_ind', 'w_o35_rate', 2.50),
        ('gg', 'w_gg_rate', 1.85),
        ('hw', 'w_1_rate', 2.00), ('dr', 'w_x_rate', 3.20), ('aw', 'w_2_rate', 2.80)
    ]
    
    stake_per_bet = 10
    
    unfilt_bankroll = 0
    filt_bankroll = 0
    
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
            best_odds = 1.30 # Fallback conservative odds
            
            for act_key, rate_key, avg_odds in markets:
                mac_val = mac_r.get(rate_key, 0)
                mic_val = mic_r.get(rate_key, 0)
                score = (mac_val + mic_val) / 2 if (mac_val > 0 and mic_val > 0) else max(mac_val, mic_val)
                if 'hw' in act_key or 'aw' in act_key or 'dr' in act_key or '35' in act_key or '15' in act_key:
                    score *= 0.85
                    
                if score > best_score:
                    best_score = score
                    best_market = act_key
                    # We penalize odds slightly since our bot picks high-probability outcomes
                    best_odds = avg_odds * 0.85 
                    if best_odds < 1.15: best_odds = 1.15
                    
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
            
            # UNFILTERED: Place 10 Naira
            unfilt_bankroll -= stake_per_bet
            if is_hit:
                unfilt_bankroll += (stake_per_bet * best_odds)
                
            # FILTERED: Place 10 Naira only if safe
            if not chaos_flag:
                filt_bankroll -= stake_per_bet
                if is_hit:
                    filt_bankroll += (stake_per_bet * best_odds)

    print("\n=========================================")
    print(" FINANCIAL SIMULATION (2 SEASONS: 480 MATCHES)")
    print(f" Strategy: Flat Betting (10 Naira per pick)")
    print("=========================================")
    print(f"UNFILTERED PROFIT/LOSS: {unfilt_bankroll:.2f} Naira")
    print(f"FILTERED PROFIT/LOSS:   {filt_bankroll:.2f} Naira")

if __name__ == '__main__':
    main()
