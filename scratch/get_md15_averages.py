import sqlite3
import pandas as pd

DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"
conn = sqlite3.connect(DB_PATH)

# Get last 12 seasons
query = "SELECT DISTINCT season FROM matches WHERE season IS NOT NULL ORDER BY season DESC LIMIT 12"
seasons = pd.read_sql_query(query, conn)['season'].tolist()

all_ranks = []

for s in seasons:
    query = f"SELECT home as team, h as gf, a as ga FROM matches WHERE season = '{s}' AND day <= 15"
    h_df = pd.read_sql_query(query, conn)
    query = f"SELECT away as team, a as gf, h as ga FROM matches WHERE season = '{s}' AND day <= 15"
    a_df = pd.read_sql_query(query, conn)
    
    h_df['pts'] = h_df.apply(lambda x: 3 if x['gf'] > x['ga'] else (1 if x['gf'] == x['ga'] else 0), axis=1)
    a_df['pts'] = a_df.apply(lambda x: 3 if x['gf'] > x['ga'] else (1 if x['gf'] == x['ga'] else 0), axis=1)
    
    df = pd.concat([h_df, a_df])
    pts = df.groupby('team')['pts'].sum().sort_values(ascending=False).reset_index()
    pts['rank'] = pts.index + 1
    all_ranks.append(pts)

combined = pd.concat(all_ranks)
avg = combined.groupby('rank')['pts'].mean().round(1)

print("=== MD 15 POINT QUOTAS (12-Season Average) ===")
for r, p in avg.items():
    print(f"Rank {r}: ~{p} pts")
    if r == 6:
        print("--------------------- (Top 6 Cutoff)")
    elif r == 12:
        print("--------------------- (Mid 6 Cutoff)")
    elif r == 16:
        break
