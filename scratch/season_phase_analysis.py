import pandas as pd
import sys
import numpy as np

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def analyze_seasonal_phases(df):
    """
    Analyzes how W/D/L outcomes are allocated across different phases of the season.
    Divides the season into 3 phases:
    - Phase 1 (MD 1-10): Early Season (Table Formation)
    - Phase 2 (MD 11-20): Mid Season (Stable Tiers)
    - Phase 3 (MD 21-30+): Late Season (Quota Enforcement)
    """
    # Remove MD 1 and 2 as the user suggested skipping them
    df = df[df['day'] >= 3].copy()
    
    # Create Phase column
    def get_phase(day):
        if day <= 10: return 'PHASE 1 (MD 3-10): Formation'
        elif day <= 20: return 'PHASE 2 (MD 11-20): Stability'
        else: return 'PHASE 3 (MD 21+): Quota Enforcement'
        
    df['season_phase'] = df['day'].apply(get_phase)
    
    # We will look at how TIER Matchups behave across the 3 phases
    # E.g., does T1 vs T4 act differently in Phase 3 vs Phase 2?
    
    grouped = df.groupby(['home_tier', 'away_tier', 'season_phase'])
    
    results = []
    
    for name, group in grouped:
        h_tier, a_tier, phase = name
        matches = len(group)
        
        if matches < 50:
            continue
            
        hw = sum(group['h'] > group['a']) / matches
        dr = sum(group['h'] == group['a']) / matches
        aw = sum(group['h'] < group['a']) / matches
        
        results.append({
            'matchup': f"{h_tier} vs {a_tier}",
            'phase': phase,
            'matches': matches,
            'hw': hw * 100,
            'dr': dr * 100,
            'aw': aw * 100
        })
        
    df_results = pd.DataFrame(results)
    
    print("\n==================================================================================")
    print(" ⏳ SEASONAL PHASE ALLOCATION: HOW QUOTAS SHIFT PROBABILITIES")
    print("==================================================================================")
    
    # Let's compare Phase 1, 2, and 3 for key matchups!
    key_matchups = ['T1 vs T4', 'T1 vs T3', 'T2 vs T4', 'T1 vs T1', 'T4 vs T1']
    
    print(f"{'MATCHUP':<12} | {'SEASON PHASE':<35} | {'HW%':<6} | {'DR%':<6} | {'AW%':<6}")
    print("-" * 75)
    
    for matchup in key_matchups:
        matchup_data = df_results[df_results['matchup'] == matchup].sort_values(by='phase')
        if matchup_data.empty:
            continue
            
        for _, row in matchup_data.iterrows():
            print(f"{row['matchup']:<12} | {row['phase']:<35} | {row['hw']:<6.1f} | {row['dr']:<6.1f} | {row['aw']:<6.1f}")
        print("-" * 75)

def main():
    print("Loading historical data...")
    df, _ = extract_panel_data_with_standings()
    analyze_seasonal_phases(df)

if __name__ == '__main__':
    main()
