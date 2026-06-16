import sqlite3
import pandas as pd

DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"
conn = sqlite3.connect(DB_PATH)

# Get the last 4 fully completed seasons
query = "SELECT DISTINCT season FROM matches WHERE season IS NOT NULL ORDER BY season DESC LIMIT 4"
seasons_df = pd.read_sql_query(query, conn)
seasons = seasons_df['season'].tolist()

total_bets = 0
total_wins = 0

for season in seasons:
    query = f"SELECT home as team, h as gf, a as ga FROM matches WHERE season = '{season}' AND day <= 15"
    h_df = pd.read_sql_query(query, conn)
    query = f"SELECT away as team, a as gf, h as ga FROM matches WHERE season = '{season}' AND day <= 15"
    a_df = pd.read_sql_query(query, conn)
    
    h_df['pts'] = h_df.apply(lambda x: 3 if x['gf'] > x['ga'] else (1 if x['gf'] == x['ga'] else 0), axis=1)
    a_df['pts'] = a_df.apply(lambda x: 3 if x['gf'] > x['ga'] else (1 if x['gf'] == x['ga'] else 0), axis=1)
    
    df_pts = pd.concat([h_df, a_df])
    pts = df_pts.groupby('team')['pts'].sum().sort_values(ascending=False).reset_index()
    pts['rank'] = pts.index + 1
    
    def get_tier(rank):
        if rank <= 6: return "Top 6"
        if rank <= 12: return "Mid 6"
        return "Bottom 4"
        
    rank_map = dict(zip(pts['team'], pts['rank']))
    tier_map = {t: get_tier(r) for t, r in rank_map.items()}
    
    query = f"SELECT home, away, h as hg, a as ag, day FROM matches WHERE season = '{season}' AND day <= 15"
    l1_df = pd.read_sql_query(query, conn)
    l1_dict = {}
    for _, row in l1_df.iterrows():
        l1_dict[(row['home'], row['away'])] = (row['hg'], row['ag'])

    query = f"SELECT home, away, h as hg, a as ag, day FROM matches WHERE season = '{season}' AND day > 15"
    l2_df = pd.read_sql_query(query, conn)
    
    season_bets = 0
    season_wins = 0
    
    for _, row in l2_df.iterrows():
        h2 = row['home']
        a2 = row['away']
        hg2 = row['hg']
        ag2 = row['ag']
        
        l1_res = l1_dict.get((a2, h2))
        if not l1_res: continue
        
        hg1, ag1 = l1_res
        
        h2_tier = tier_map.get(h2)
        a2_tier = tier_map.get(a2)
        
        # Also need Quota status for strict Point-Aware testing
        h2_pts = pts[pts['team'] == h2]['pts'].values[0]
        a2_pts = pts[pts['team'] == a2]['pts'].values[0]
        
        bet_placed = False
        won = False
        
        # The true test uses Double Chance for the Trap underdogs
        
        # 1. Delayed Elite Win (Top 6 Home vs Mid 6, L1 0-0)
        if h2_tier == "Top 6" and a2_tier == "Mid 6" and hg1 == 0 and ag1 == 0:
            if h2_pts < 23.9: # Under-Quota Top 6
                bet_placed = True
                won = hg2 >= ag2 # Home Win or Draw
                
        # 2. Elite Vengeance Blowout (Top 6 Home vs Mid 6, L1 lost by 3+)
        elif h2_tier == "Top 6" and a2_tier == "Mid 6" and (ag1 - hg1) >= 3:
            bet_placed = True
            won = hg2 >= ag2 # Home Win or Draw
            
        # 3. Away Revenge Trap (Top 6 Away vs Bottom 4 Home, L1 lost by 1)
        elif h2_tier == "Bottom 4" and a2_tier == "Top 6" and (hg1 - ag1) == 1:
            if h2_pts >= 9.4: # Bottom 4 is Over-Quota/Safe
                bet_placed = True
                won = ag2 >= hg2 # Away Win or Draw
                
        if bet_placed:
            season_bets += 1
            if won: season_wins += 1
            
    print(f"Season {season}: {season_wins} / {season_bets} Hits ({(season_wins/max(1, season_bets))*100:.1f}%)")
    total_bets += season_bets
    total_wins += season_wins

print(f"\nOverall Point-Aware Double-Chance Hit Rate: {(total_wins/max(1, total_bets))*100:.2f}% ({total_wins}/{total_bets})")
