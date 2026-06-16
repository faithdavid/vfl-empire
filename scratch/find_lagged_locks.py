import pandas as pd
import sys
import numpy as np
import json

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

def find_lagged_locks():
    print("Extracting raw data and calculating 2-Matchday Lag Tiers...")
    
    import sqlite3
    DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT season, day, home, away, h, a, total, gg, o25
    FROM matches
    WHERE season IS NOT NULL AND total IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    df['season_num'] = df['season'].astype(str).str.extract(r'(\d+)').astype(float)
    max_season = df['season_num'].max()
    df['season_num'].fillna(max_season, inplace=True)

    home_results = df[['season', 'season_num', 'day', 'home', 'h', 'a']].copy()
    home_results.rename(columns={'home': 'team', 'h': 'gf', 'a': 'ga'}, inplace=True)
    home_results['pts'] = np.where(home_results['gf'] > home_results['ga'], 3, np.where(home_results['gf'] == home_results['ga'], 1, 0))

    away_results = df[['season', 'season_num', 'day', 'away', 'a', 'h']].copy()
    away_results.rename(columns={'away': 'team', 'a': 'gf', 'h': 'ga'}, inplace=True)
    away_results['pts'] = np.where(away_results['gf'] > away_results['ga'], 3, np.where(away_results['gf'] == away_results['ga'], 1, 0))

    df_teams = pd.concat([home_results, away_results], ignore_index=True)
    df_teams.sort_values(['season', 'day'], inplace=True)
    df_teams['gd'] = df_teams['gf'] - df_teams['ga']

    df_teams['cum_pts'] = df_teams.groupby(['season', 'team'])['pts'].cumsum()
    df_teams['cum_gd'] = df_teams.groupby(['season', 'team'])['gd'].cumsum()
    df_teams['cum_gf'] = df_teams.groupby(['season', 'team'])['gf'].cumsum()

    # The 2-Matchday Lag (shift(2))
    df_teams['prev_pts'] = df_teams.groupby(['season', 'team'])['cum_pts'].shift(2).fillna(0)
    df_teams['prev_gd'] = df_teams.groupby(['season', 'team'])['cum_gd'].shift(2).fillna(0)
    df_teams['prev_gf'] = df_teams.groupby(['season', 'team'])['cum_gf'].shift(2).fillna(0)

    df_teams.sort_values(['season', 'day', 'prev_pts', 'prev_gd', 'prev_gf'], ascending=[True, True, False, False, False], inplace=True)
    df_teams['rank'] = df_teams.groupby(['season', 'day']).cumcount() + 1
    
    df_teams['lag_tier'] = pd.cut(df_teams['rank'], bins=[0, 4, 8, 12, 16], labels=['T1', 'T2', 'T3', 'T4'])

    home_ranks = df_teams[['season', 'day', 'team', 'lag_tier']].rename(columns={'team': 'home', 'lag_tier': 'lag_home_tier'})
    away_ranks = df_teams[['season', 'day', 'team', 'lag_tier']].rename(columns={'team': 'away', 'lag_tier': 'lag_away_tier'})

    df = df.merge(home_ranks, on=['season', 'day', 'home'], how='left')
    df = df.merge(away_ranks, on=['season', 'day', 'away'], how='left')
    
    df['season_phase'] = np.ceil(df['day'] / 2.0).astype(int)
    
    # We must only look at MD >= 4, because a 2-matchday lag means MD1, 2, and 3 have basically zero meaningful table data
    df = df[df['season_phase'] >= 3]
    
    # Group by Fixture + LAGGED Tiers + Phase
    grouped = df.groupby(['home', 'away', 'lag_home_tier', 'lag_away_tier', 'season_phase'])
    
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
            locks.append({'fixture': f"{home} vs {away}", 'lag_tiers': f"{h_tier} vs {a_tier}", 'phase': phase, 'matches': matches, 'lock': 'HOME WIN', 'lock_code': 'hw'})
        elif dr == 1.0:
            locks.append({'fixture': f"{home} vs {away}", 'lag_tiers': f"{h_tier} vs {a_tier}", 'phase': phase, 'matches': matches, 'lock': 'DRAW', 'lock_code': 'dr'})
        elif aw == 1.0:
            locks.append({'fixture': f"{home} vs {away}", 'lag_tiers': f"{h_tier} vs {a_tier}", 'phase': phase, 'matches': matches, 'lock': 'AWAY WIN', 'lock_code': 'aw'})
            
    df_locks = pd.DataFrame(locks)
    
    print("\n==================================================================================")
    print(" 🛡️ THE BULLETPROOF ORACLE: 2-MATCHDAY LAGGED LOCKS")
    print("==================================================================================")
    
    if df_locks.empty:
        print("No 100% locks found with >= 5 occurrences using lagged tiers.")
        return
        
    df_locks = df_locks.sort_values(by=['phase', 'matches'], ascending=[True, False])
    
    print(f"Total 100% Bulletproof Locks Found: {len(df_locks)}")
    print(f"\n{'PHASE':<10} | {'FIXTURE':<30} | {'LAG TIERS':<10} | {'LOCK':<10} | {'FREQ'}")
    print("-" * 75)
    
    for _, row in df_locks.head(20).iterrows():
        phase_str = f"Phase {row['phase']:02d}"
        print(f"{phase_str:<10} | {row['fixture']:<30} | {row['lag_tiers']:<10} | {row['lock']:<10} | {row['matches']}")

if __name__ == '__main__':
    find_lagged_locks()
