import pandas as pd
import sys
import numpy as np
import json

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def dump_phase_locks_json(df):
    df['season_phase'] = np.ceil(df['day'] / 2.0).astype(int)
    df = df[df['season_phase'] >= 2]
    
    grouped = df.groupby(['home', 'away', 'home_tier', 'away_tier', 'season_phase'])
    
    locks = []
    for name, group in grouped:
        home, away, h_tier, a_tier, phase = name
        matches = len(group)
        
        if matches < 5:
            continue
            
        hw = sum(group['h'] > group['a']) / matches
        dr = sum(group['h'] == group['a']) / matches
        aw = sum(group['h'] < group['a']) / matches
        
        if hw == 1.0:
            lock_type = 'hw'
        elif dr == 1.0:
            lock_type = 'dr'
        elif aw == 1.0:
            lock_type = 'aw'
        else:
            continue
            
        locks.append({
            'home': str(home),
            'away': str(away),
            'home_tier': str(h_tier),
            'away_tier': str(a_tier),
            'phase': int(phase),
            'lock': lock_type,
            'occurrences': int(matches)
        })
        
    out_path = '/home/ubuntu/faith-workspace/vfl-empire/data/phase_fixture_locks.json'
    with open(out_path, 'w') as f:
        json.dump(locks, f, indent=4)
        
    print(f"Successfully dumped {len(locks)} Phase Locks to {out_path}")

def main():
    print("Extracting panel data...")
    df, _ = extract_panel_data_with_standings()
    dump_phase_locks_json(df)

if __name__ == '__main__':
    main()
