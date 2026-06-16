import pandas as pd
import sys
import numpy as np

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def analyze_15_phases(df):
    """
    Analyzes how W/D/L outcomes are allocated across 15 phases of the season.
    Each phase consists of exactly 2 matchdays (Phase 1 = MD 1-2, Phase 15 = MD 29-30).
    """
    # Create Phase column (1 to 15)
    df['season_phase'] = np.ceil(df['day'] / 2.0).astype(int)
    
    # We want to see how the Tier Matchups behave across all 15 phases
    grouped = df.groupby(['home_tier', 'away_tier', 'season_phase'])
    
    results = []
    
    for name, group in grouped:
        h_tier, a_tier, phase = name
        matches = len(group)
        
        if matches < 20: # Lowered threshold because we sliced into 15 buckets
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
    print(" 📊 15-PHASE ALLOCATION: THE EXACT QUOTA TIMELINE (2 Matchdays per Phase)")
    print("==================================================================================")
    
    # Print the exact timeline for T1 vs T4 and T4 vs T1
    key_matchups = ['T1 vs T4', 'T4 vs T1']
    
    print(f"{'MATCHUP':<10} | {'PHASE (MATCHDAYS)':<22} | {'HW%':<6} | {'DR%':<6} | {'AW%':<6}")
    print("-" * 65)
    
    for matchup in key_matchups:
        matchup_data = df_results[df_results['matchup'] == matchup].sort_values(by='phase')
        if matchup_data.empty:
            continue
            
        for _, row in matchup_data.iterrows():
            phase_num = row['phase']
            md_start = (phase_num * 2) - 1
            md_end = phase_num * 2
            phase_label = f"Phase {phase_num:02d} (MD {md_start:02d}-{md_end:02d})"
            
            print(f"{row['matchup']:<10} | {phase_label:<22} | {row['hw']:<6.1f} | {row['dr']:<6.1f} | {row['aw']:<6.1f}")
        print("-" * 65)

def main():
    df, _ = extract_panel_data_with_standings()
    analyze_15_phases(df)

if __name__ == '__main__':
    main()
