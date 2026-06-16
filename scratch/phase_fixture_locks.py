import pandas as pd
import sys
import numpy as np

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def find_phase_fixture_locks(df):
    """
    Groups by EXACT Fixture + EXACT Tiers + 15-Phase Cluster.
    Searches for 100% locks with >= 5 occurrences.
    """
    # Create Phase column (1 to 15)
    df['season_phase'] = np.ceil(df['day'] / 2.0).astype(int)
    
    # We only care about matches from Matchday 3 onwards (Phases 2-15) as per user's earlier rule
    df = df[df['season_phase'] >= 2]
    
    grouped = df.groupby(['home', 'away', 'home_tier', 'away_tier', 'season_phase'])
    
    locks = []
    
    for name, group in grouped:
        home, away, h_tier, a_tier, phase = name
        matches = len(group)
        
        # We need at least 5 occurrences to consider it a structural lock
        if matches < 5:
            continue
            
        hw = sum(group['h'] > group['a']) / matches
        dr = sum(group['h'] == group['a']) / matches
        aw = sum(group['h'] < group['a']) / matches
        
        if hw == 1.0:
            locks.append({'fixture': f"{home} vs {away}", 'tiers': f"{h_tier} vs {a_tier}", 'phase': phase, 'matches': matches, 'lock': 'HOME WIN'})
        elif dr == 1.0:
            locks.append({'fixture': f"{home} vs {away}", 'tiers': f"{h_tier} vs {a_tier}", 'phase': phase, 'matches': matches, 'lock': 'DRAW'})
        elif aw == 1.0:
            locks.append({'fixture': f"{home} vs {away}", 'tiers': f"{h_tier} vs {a_tier}", 'phase': phase, 'matches': matches, 'lock': 'AWAY WIN'})
            
    df_locks = pd.DataFrame(locks)
    
    print("\n==================================================================================")
    print(" ⏰ PHASE + FIXTURE LOCKS: THE ULTIMATE CALENDAR CHEAT SHEET")
    print("==================================================================================")
    
    if df_locks.empty:
        print("No 100% locks found with >= 5 occurrences.")
        return
        
    df_locks = df_locks.sort_values(by=['phase', 'matches'], ascending=[True, False])
    
    print(f"Total 100% Locks Found: {len(df_locks)}")
    print(f"\n{'PHASE':<10} | {'FIXTURE':<30} | {'TIERS':<10} | {'LOCK':<10} | {'FREQ'}")
    print("-" * 75)
    
    # Print the top 30 most frequent locks across the calendar
    for _, row in df_locks.head(30).iterrows():
        phase_str = f"Phase {row['phase']:02d}"
        print(f"{phase_str:<10} | {row['fixture']:<30} | {row['tiers']:<10} | {row['lock']:<10} | {row['matches']}")

def main():
    print("Loading historical data (531 seasons)...")
    df, _ = extract_panel_data_with_standings()
    find_phase_fixture_locks(df)

if __name__ == '__main__':
    main()
