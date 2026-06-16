import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"

def extract_panel_data_with_standings():
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT season, day, home, away, h, a, total, gg, o25
    FROM matches
    WHERE season IS NOT NULL AND total IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    # Ensure deduplication (Drop duplicate matches on same season/day between same teams)
    df.drop_duplicates(subset=['season', 'day', 'home', 'away'], inplace=True)
    conn.close()

    # Calculate points
    df_home = df[['season', 'day', 'home', 'h', 'a']].copy()
    df_home.columns = ['season', 'day', 'team', 'gf', 'ga']
    df_home['pts'] = np.where(df_home['gf'] > df_home['ga'], 3, np.where(df_home['gf'] == df_home['ga'], 1, 0))

    df_away = df[['season', 'day', 'away', 'a', 'h']].copy()
    df_away.columns = ['season', 'day', 'team', 'gf', 'ga']
    df_away['pts'] = np.where(df_away['gf'] > df_away['ga'], 3, np.where(df_away['gf'] == df_away['ga'], 1, 0))

    df_teams = pd.concat([df_home, df_away])
    df_teams.sort_values(['season', 'team', 'day'], inplace=True)
    df_teams['gd'] = df_teams['gf'] - df_teams['ga']

    # Cumulative stats
    df_teams['cum_pts'] = df_teams.groupby(['season', 'team'])['pts'].cumsum()
    df_teams['cum_gd'] = df_teams.groupby(['season', 'team'])['gd'].cumsum()
    df_teams['cum_gf'] = df_teams.groupby(['season', 'team'])['gf'].cumsum()

    # Previous match stats (standings going into the match)
    df_teams['prev_pts'] = df_teams.groupby(['season', 'team'])['cum_pts'].shift(1).fillna(0)
    df_teams['prev_gd'] = df_teams.groupby(['season', 'team'])['cum_gd'].shift(1).fillna(0)
    df_teams['prev_gf'] = df_teams.groupby(['season', 'team'])['cum_gf'].shift(1).fillna(0)

    # Rank teams per matchday
    df_teams.sort_values(['season', 'day', 'prev_pts', 'prev_gd', 'prev_gf'], ascending=[True, True, False, False, False], inplace=True)
    df_teams['rank'] = df_teams.groupby(['season', 'day']).cumcount() + 1
    
    # Bucket rankings into 4 tiers for 16 teams: Top (1-4), Upper Mid (5-8), Lower Mid (9-12), Relegation (13-16)
    df_teams['tier'] = pd.cut(df_teams['rank'], bins=[0, 4, 8, 12, 16], labels=['T1', 'T2', 'T3', 'T4'])
    
    # Bucket rankings into 8 micro-tiers (bins of 2) to catch granular position matchups
    df_teams['micro_tier'] = pd.cut(df_teams['rank'], bins=[0, 2, 4, 6, 8, 10, 12, 14, 16], labels=['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'])

    home_ranks = df_teams[['season', 'day', 'team', 'tier', 'micro_tier']].rename(columns={'team': 'home', 'tier': 'home_tier', 'micro_tier': 'home_micro'})
    away_ranks = df_teams[['season', 'day', 'team', 'tier', 'micro_tier']].rename(columns={'team': 'away', 'tier': 'away_tier', 'micro_tier': 'away_micro'})

    df = df.merge(home_ranks, on=['season', 'day', 'home'], how='left')
    df = df.merge(away_ranks, on=['season', 'day', 'away'], how='left')

    # Data coding: Convert season strings to integers
    df['season_num'] = df['season'].astype(str).str.extract(r'(\d+)').astype(float)
    max_season = df['season_num'].max()
    df['season_num'].fillna(max_season, inplace=True)

    return df, max_season

def mine_fixture_patterns(df, max_season, tier_type="macro"):
    df['u15_ind'] = (df['total'] < 1.5).astype(int)
    df['o15_ind'] = (df['total'] > 1.5).astype(int)
    df['u25_ind'] = (df['total'] < 2.5).astype(int)
    df['u35_ind'] = (df['total'] < 3.5).astype(int)
    df['o25_ind'] = (df['total'] > 2.5).astype(int)
    df['o35_ind'] = (df['total'] > 3.5).astype(int)
    df['gg_ind'] = df['gg']
    df['hw_ind'] = (df['h'] > df['a']).astype(int)
    df['dr_ind'] = (df['h'] == df['a']).astype(int)
    df['aw_ind'] = (df['h'] < df['a']).astype(int)
        
    # Group by fixture AND tiers
    if tier_type == "macro":
        grouped = df.groupby(['home', 'away', 'home_tier', 'away_tier'])
    else:
        grouped = df.groupby(['home', 'away', 'home_micro', 'away_micro'])
    
    results = []
    for name, group in grouped:
        count = len(group)
        if count < 5:  # require at least 5 instances of this specific tier matchup
            continue
            
        # Calculate pure historical hit rates
        sum_count = float(count)
        
        w_u15_rate = group['u15_ind'].sum() / sum_count
        w_o15_rate = group['o15_ind'].sum() / sum_count
        w_u25_rate = group['u25_ind'].sum() / sum_count
        w_u35_rate = group['u35_ind'].sum() / sum_count
        w_o25_rate = group['o25_ind'].sum() / sum_count
        w_o35_rate = group['o35_ind'].sum() / sum_count
        w_gg_rate = group['gg_ind'].sum() / sum_count
        w_hw_rate = group['hw_ind'].sum() / sum_count
        w_dr_rate = group['dr_ind'].sum() / sum_count
        w_aw_rate = group['aw_ind'].sum() / sum_count
        w_avg_goals = group['total'].sum() / sum_count
        
        results.append({
            'home': name[0],
            'away': name[1],
            'home_tier': name[2],
            'away_tier': name[3],
            'occurrences': count,
            'w_avg_goals': w_avg_goals,
            'w_1_rate': w_hw_rate,
            'w_x_rate': w_dr_rate,
            'w_2_rate': w_aw_rate,
            'w_u15_rate': w_u15_rate,
            'w_o15_rate': w_o15_rate,
            'w_u25_rate': w_u25_rate,
            'w_u35_rate': w_u35_rate,
            'w_o25_rate': w_o25_rate,
            'w_o35_rate': w_o35_rate,
            'w_gg_rate': w_gg_rate
        })
        
    res_df = pd.DataFrame(results)
    
    # Save to JSON for the live predictor to use
    if tier_type == "macro":
        res_df.to_json("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", orient="records")
    else:
        res_df.to_json("/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json", orient="records")
        
    return res_df

def main():
    print("Extracting history and computing standings...")
    df, max_s = extract_panel_data_with_standings()
    print(f"Extracted {len(df)} matches. Max season: {max_s}")
    
    print("Mining MACRO patterns with standing context (T1-T4)...")
    patterns = mine_fixture_patterns(df, max_s, tier_type="macro")
    
    print("Mining MICRO patterns with standing context (A-H)...")
    micro_patterns = mine_fixture_patterns(df, max_s, tier_type="micro")
    
    print("\n--- TOP UNDER 2.5 PATTERNS (Tier Context) ---")
    u25_top = patterns[patterns['occurrences'] >= 10].sort_values('w_u25_rate', ascending=False).head(15)
    print(u25_top[['home', 'away', 'home_tier', 'away_tier', 'occurrences', 'w_u25_rate', 'w_u15_rate']].to_string(index=False))
    
    print("\n--- TOP OVER 2.5 PATTERNS (Tier Context) ---")
    o25_top = patterns[patterns['occurrences'] >= 10].sort_values('w_o25_rate', ascending=False).head(15)
    print(o25_top[['home', 'away', 'home_tier', 'away_tier', 'occurrences', 'w_o25_rate', 'w_gg_rate']].to_string(index=False))

if __name__ == '__main__':
    main()
