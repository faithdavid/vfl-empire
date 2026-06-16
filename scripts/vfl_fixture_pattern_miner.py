import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"

def extract_panel_data():
    conn = sqlite3.connect(DB_PATH)
    
    # Extract match data
    query = """
    SELECT season, day, home, away, total, gg, o25
    FROM matches
    WHERE season IS NOT NULL AND total IS NOT NULL
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    # Data coding: Convert season strings to integers if they are not already
    # VFL seasons are usually sequential. We will just rank them to find recency.
    df['season_num'] = df['season'].astype(str).str.extract(r'(\d+)').astype(float)
    
    # Handle NaNs in season
    max_season = df['season_num'].max()
    df['season_num'].fillna(max_season, inplace=True)
    
    return df, max_season

def mine_fixture_patterns(df, max_season):
    # Recency weighting: exponential decay based on how many seasons ago
    # e.g., weight = 0.95 ^ (max_season - season_num)
    df['seasons_ago'] = max_season - df['season_num']
    df['weight'] = np.power(0.95, df['seasons_ago'])
    
    # Calculate indicators
    df['u15'] = (df['total'] < 1.5).astype(int)
    df['u25'] = (df['total'] < 2.5).astype(int)
    df['o25_ind'] = df['o25']
    df['gg_ind'] = df['gg']
    
    # We want to aggregate by (home, away)
    # Using weighted averages
    
    # Create weighted columns
    for col in ['u15', 'u25', 'o25_ind', 'gg_ind', 'total']:
        df[f'w_{col}'] = df[col] * df['weight']
        
    grouped = df.groupby(['home', 'away'])
    
    results = []
    for name, group in grouped:
        count = len(group)
        if count < 5:
            continue
            
        sum_weight = group['weight'].sum()
        
        w_u15_rate = group['w_u15'].sum() / sum_weight
        w_u25_rate = group['w_u25'].sum() / sum_weight
        w_o25_rate = group['w_o25_ind'].sum() / sum_weight
        w_gg_rate = group['w_gg_ind'].sum() / sum_weight
        w_avg_goals = group['w_total'].sum() / sum_weight
        
        results.append({
            'home': name[0],
            'away': name[1],
            'occurrences': count,
            'w_avg_goals': w_avg_goals,
            'w_u15_rate': w_u15_rate,
            'w_u25_rate': w_u25_rate,
            'w_o25_rate': w_o25_rate,
            'w_gg_rate': w_gg_rate
        })
        
    res_df = pd.DataFrame(results)
    return res_df

def main():
    df, max_s = extract_panel_data()
    print(f"Extracted {len(df)} matches. Max season: {max_s}")
    
    patterns = mine_fixture_patterns(df, max_s)
    
    print("\n--- TOP UNDER 2.5 PATTERNS (Weighted) ---")
    u25_top = patterns[patterns['occurrences'] >= 10].sort_values('w_u25_rate', ascending=False).head(10)
    print(u25_top[['home', 'away', 'occurrences', 'w_u25_rate', 'w_u15_rate']])
    
    print("\n--- TOP OVER 2.5 PATTERNS (Weighted) ---")
    o25_top = patterns[patterns['occurrences'] >= 10].sort_values('w_o25_rate', ascending=False).head(10)
    print(o25_top[['home', 'away', 'occurrences', 'w_o25_rate', 'w_gg_rate']])

if __name__ == '__main__':
    main()
