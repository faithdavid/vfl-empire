import pandas as pd
import json
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def main():
    print("Extracting data and standings...")
    df, max_s = extract_panel_data_with_standings()
    
    # Find seasons with exactly 240 matches (30 matchdays * 8 fixtures)
    season_counts = df.groupby('season_num').size()
    full_seasons = season_counts[season_counts == 240].index.sort_values(ascending=False)
    
    if len(full_seasons) < 2:
        print("Not enough full seasons found!")
        return
        
    s1, s2 = full_seasons[0], full_seasons[1]
    test_df = df[df['season_num'].isin([s1, s2])].copy()
    print(f"Testing on {len(test_df)} matches from full seasons {s1} and {s2}...")
    
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", "r") as f:
        macro_data = json.load(f)
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json", "r") as f:
        micro_data = json.load(f)
        
    macro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in macro_data if r['occurrences'] >= 10 }
    micro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in micro_data if r['occurrences'] >= 10 }
    
    results = {
        'Under 1.5': {'w': 0, 't': 0},
        'Over 1.5': {'w': 0, 't': 0},
        'Under 2.5': {'w': 0, 't': 0},
        'Over 2.5': {'w': 0, 't': 0},
        'Under 3.5': {'w': 0, 't': 0},
        'Over 3.5': {'w': 0, 't': 0},
        'GG': {'w': 0, 't': 0},
        'Home Win': {'w': 0, 't': 0},
        'Draw': {'w': 0, 't': 0},
        'Away Win': {'w': 0, 't': 0},
        'Exact Score': {'w': 0, 't': 0}
    }
    
    def infer_exact_score(row: dict) -> str:
        u15 = row.get('w_u15_rate', 0) >= 0.95
        u25 = row.get('w_u25_rate', 0) >= 0.95
        u35 = row.get('w_u35_rate', 0) >= 0.95
        o15 = row.get('w_o15_rate', 0) >= 0.95
        o25 = row.get('w_o25_rate', 0) >= 0.95
        o35 = row.get('w_o35_rate', 0) >= 0.95
        gg = row.get('w_gg_rate', 0) >= 0.95
        ng = row.get('w_gg_rate', 1) <= 0.05
        hw = row.get('w_1_rate', 0) >= 0.95
        dr = row.get('w_x_rate', 0) >= 0.95
        aw = row.get('w_2_rate', 0) >= 0.95
        
        if dr and u15: return "0-0"
        if dr and u25 and gg: return "1-1"
        if dr and o35: return "2-2" # Simplified for backtest exact match
        if hw and u15: return "1-0"
        if aw and u15: return "0-1"
        if hw and u25 and o15 and ng: return "2-0"
        if aw and u25 and o15 and ng: return "0-2"
        if hw and o25 and u35 and gg: return "2-1"
        if aw and o25 and u35 and gg: return "1-2"
        if hw and o25 and u35 and ng: return "3-0"
        if aw and o25 and u35 and ng: return "0-3"
        return None

    for _, match in test_df.iterrows():
        mac_k = (match['home'], match['away'], match['home_tier'], match['away_tier'])
        mic_k = (match['home'], match['away'], match['home_micro'], match['away_micro'])
        
        preds_made = set() # To avoid double counting if macro and micro predict same thing
        
        for p_key, lookup in [(mac_k, macro_lookup), (mic_k, micro_lookup)]:
            if p_key in lookup:
                row = lookup[p_key]
                
                # Check goals
                if row['w_u15_rate'] >= 0.95 and 'u15' not in preds_made:
                    results['Under 1.5']['t'] += 1
                    if match['total'] < 1.5: results['Under 1.5']['w'] += 1
                    preds_made.add('u15')
                if row['w_o15_rate'] >= 0.95 and 'o15' not in preds_made:
                    results['Over 1.5']['t'] += 1
                    if match['total'] > 1.5: results['Over 1.5']['w'] += 1
                    preds_made.add('o15')
                if row['w_u25_rate'] >= 0.95 and 'u25' not in preds_made:
                    results['Under 2.5']['t'] += 1
                    if match['total'] < 2.5: results['Under 2.5']['w'] += 1
                    preds_made.add('u25')
                if row['w_o25_rate'] >= 0.95 and 'o25' not in preds_made:
                    results['Over 2.5']['t'] += 1
                    if match['total'] > 2.5: results['Over 2.5']['w'] += 1
                    preds_made.add('o25')
                if row['w_u35_rate'] >= 0.95 and 'u35' not in preds_made:
                    results['Under 3.5']['t'] += 1
                    if match['total'] < 3.5: results['Under 3.5']['w'] += 1
                    preds_made.add('u35')
                if row['w_o35_rate'] >= 0.95 and 'o35' not in preds_made:
                    results['Over 3.5']['t'] += 1
                    if match['total'] > 3.5: results['Over 3.5']['w'] += 1
                    preds_made.add('o35')
                if row['w_gg_rate'] >= 0.95 and 'gg' not in preds_made:
                    results['GG']['t'] += 1
                    if match['gg'] == 1: results['GG']['w'] += 1
                    preds_made.add('gg')
                    
                # Check 1X2
                if row['w_1_rate'] >= 0.95 and '1' not in preds_made:
                    results['Home Win']['t'] += 1
                    if match['h'] > match['a']: results['Home Win']['w'] += 1
                    preds_made.add('1')
                if row['w_x_rate'] >= 0.95 and 'x' not in preds_made:
                    results['Draw']['t'] += 1
                    if match['h'] == match['a']: results['Draw']['w'] += 1
                    preds_made.add('x')
                if row['w_2_rate'] >= 0.95 and '2' not in preds_made:
                    results['Away Win']['t'] += 1
                    if match['h'] < match['a']: results['Away Win']['w'] += 1
                    preds_made.add('2')
                    
                # Exact Score
                exact = infer_exact_score(row)
                if exact and 'exact' not in preds_made:
                    results['Exact Score']['t'] += 1
                    actual_score = f"{int(match['h'])}-{int(match['a'])}"
                    if actual_score == exact:
                        results['Exact Score']['w'] += 1
                    preds_made.add('exact')
                    
    print("\n--- LAST 2 SEASONS BACKTEST RESULTS ---")
    for market, counts in results.items():
        if counts['t'] > 0:
            print(f"{market}: {counts['w']} Wins / {counts['t']} Picks")

if __name__ == '__main__':
    main()
