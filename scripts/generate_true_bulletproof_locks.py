import pandas as pd
import numpy as np
import sqlite3
import json

def generate_true_bulletproof_locks():
    DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT season, day, home, away, h, a, total, gg, o25 FROM matches WHERE season IS NOT NULL AND total IS NOT NULL"
    df = pd.read_sql_query(query, conn)
    conn.close()

    df['season_num'] = df['season'].astype(str).str.extract(r'(\d+)').astype(float)
    max_season = df['season_num'].max()
    df['season_num'] = df['season_num'].fillna(max_season)

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

    # The 1-Matchday Lag (shift(1)) so we use standings from the day before!
    df_teams['prev_pts'] = df_teams.groupby(['season', 'team'])['cum_pts'].shift(1).fillna(0)
    df_teams['prev_gd'] = df_teams.groupby(['season', 'team'])['cum_gd'].shift(1).fillna(0)
    df_teams['prev_gf'] = df_teams.groupby(['season', 'team'])['cum_gf'].shift(1).fillna(0)

    df_teams.sort_values(['season', 'day', 'prev_pts', 'prev_gd', 'prev_gf'], ascending=[True, True, False, False, False], inplace=True)
    df_teams['rank'] = df_teams.groupby(['season', 'day']).cumcount() + 1
    
    df_teams['lag_tier'] = pd.cut(df_teams['rank'], bins=[0, 4, 8, 12, 16], labels=['T1', 'T2', 'T3', 'T4'])

    home_ranks = df_teams[['season', 'day', 'team', 'lag_tier']].rename(columns={'team': 'home', 'lag_tier': 'home_tier'})
    away_ranks = df_teams[['season', 'day', 'team', 'lag_tier']].rename(columns={'team': 'away', 'lag_tier': 'away_tier'})

    df = df.merge(home_ranks, on=['season', 'day', 'home'], how='left')
    df = df.merge(away_ranks, on=['season', 'day', 'away'], how='left')
    
    df['phase'] = np.ceil(df['day'] / 2.0).astype(int)
    
    # "what happen a day before" -> so we use shift(1) and phase >= 2 (since MD1 has no "day before")
    df_valid = df[df['phase'] >= 2].copy()
    
    grouped = df_valid.groupby(['home', 'away', 'home_tier', 'away_tier', 'phase'], observed=False)
    locks = []
    
    for name, group in grouped:
        home, away, h_tier, a_tier, phase = name
        matches = len(group)
        if matches < 5: continue
            
        hw = sum(group['h'] > group['a']) / matches
        dr = sum(group['h'] == group['a']) / matches
        aw = sum(group['h'] < group['a']) / matches
        
        lock_code = None
        if hw == 1.0: lock_code = 'hw'
        elif dr == 1.0: lock_code = 'dr'
        elif aw == 1.0: lock_code = 'aw'
        
        if lock_code:
            locks.append({
                'home': str(home), 'away': str(away), 
                'home_tier': str(h_tier), 'away_tier': str(a_tier), 
                'phase': int(phase), 'lock': lock_code, 'occurrences': int(matches)
            })

    print(f"Total 100% Locks Found with 1-Day Lag: {len(locks)}")
    
    out_path = '/home/ubuntu/faith-workspace/vfl-empire/data/phase_fixture_locks_bulletproof.json'
    with open(out_path, 'w') as f:
        json.dump(locks, f, indent=4)
    print(f"Saved to {out_path}")

if __name__ == '__main__':
    generate_true_bulletproof_locks()
