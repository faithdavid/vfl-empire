import pandas as pd
import numpy as np
import psycopg2
import math

print("=== ODDS CLUSTER INTEGRATION ===")
print("Extracting Odds Fingerprints from vfl_odds_v2...")

# 1. Load Matrix
df = pd.read_parquet("/home/ubuntu/faith-workspace/vfl-empire/data/unified_ml_matrix.parquet")

# 2. Get Odds from DB
conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")
query = """
    SELECT season_id as season, matchday_number as day, home_team as home, away_team as away,
           o15, o25, gg, u35
    FROM vfl_odds_v2
    WHERE o15 IS NOT NULL AND o25 IS NOT NULL AND gg IS NOT NULL AND u35 IS NOT NULL
"""
odds_df = pd.read_sql_query(query, conn)
conn.close()

# The DB might store season_id as string (e.g. '3074000'). We need to match it.
# Convert season to string for matching
df['season'] = df['season'].astype(str)
odds_df['season'] = odds_df['season'].astype(str)

# Remove any 'vf:season:' prefixes if present
odds_df['season'] = odds_df['season'].str.replace('vf:season:', '')
df['season'] = df['season'].str.replace('vf:season:', '')

# 3. Apply Centroids
CLUSTER_CENTROIDS = [
    [0.8547, 0.6250, 0.5263, 0.6803],  # Cluster 0
    [0.6993, 0.4255, 0.4505, 0.8475],  # Cluster 1
    [0.6711, 0.3968, 0.4673, 0.8696],  # Cluster 2
    [0.8000, 0.5464, 0.5882, 0.7576],  # Cluster 3
    [0.7576, 0.4950, 0.4237, 0.8000],  # Cluster 4
    [0.7353, 0.4630, 0.4902, 0.8197],  # Cluster 5
    [0.8333, 0.5882, 0.5747, 0.7143],  # Cluster 6
    [0.8475, 0.6173, 0.6289, 0.6897],  # Cluster 7 (Gold Mine)
]

def classify(row):
    if any(pd.isna(x) or x <= 1.0 for x in [row['o15'], row['o25'], row['gg'], row['u35']]):
        return -1
    vec = [1.0/row['o15'], 1.0/row['o25'], 1.0/row['gg'], 1.0/row['u35']]
    
    best_dist = float('inf')
    best_cluster = -1
    for i, centroid in enumerate(CLUSTER_CENTROIDS):
        d = math.sqrt(sum((x - y) ** 2 for x, y in zip(vec, centroid)))
        if d < best_dist:
            best_dist = d
            best_cluster = i
    return best_cluster

print("Classifying historical matches into the 8 DNA Clusters...")
odds_df['odds_cluster'] = odds_df.apply(classify, axis=1)

# Deduplicate just in case
odds_df = odds_df.drop_duplicates(subset=['season', 'day', 'home', 'away'])

# Merge
df = df.merge(odds_df[['season', 'day', 'home', 'away', 'odds_cluster', 'o15', 'o25', 'gg', 'u35']], 
              on=['season', 'day', 'home', 'away'], how='left')

# Drop rows where we couldn't find odds
df = df[df['odds_cluster'].notna()]
df = df[df['odds_cluster'] != -1]

df.to_parquet("/home/ubuntu/faith-workspace/vfl-empire/data/unified_ml_matrix.parquet")

print(f"Odds Clusters successfully injected!")
print(f"Matrix size with complete odds data: {len(df)}")
