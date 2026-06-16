#!/usr/bin/env python3
import psycopg2
import pandas as pd
import numpy as np
import os

print("=== PHASE 1: BUILDING THE UNIFIED DATA MATRIX ===")
print("Extracting 135,000 matches from PostgreSQL Data Lake...")

conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")
query = """
    WITH RankedOdds AS (
        SELECT event_id, season_id, matchday_number, home_team, away_team,
               o15, o25, gg, u35,
               ROW_NUMBER() OVER(PARTITION BY event_id ORDER BY id DESC) as rn
        FROM vfl_odds_v2
        WHERE o15 IS NOT NULL AND o25 IS NOT NULL AND gg IS NOT NULL AND u35 IS NOT NULL
    )
    SELECT o.season_id as season, o.matchday_number as day, 
           r.home_team as home, r.away_team as away, 
           r.home_goals as h, r.away_goals as a,
           o.o15, o.o25, o.gg, o.u35,
           CASE WHEN r.home_goals > r.away_goals THEN 0 
                WHEN r.home_goals = r.away_goals THEN 1 
                ELSE 2 END as target_1x2
    FROM vfl_results_v2 r
    JOIN RankedOdds o ON r.event_id = o.event_id
    WHERE r.home_goals IS NOT NULL AND r.away_goals IS NOT NULL
      AND o.rn = 1
    ORDER BY o.season_id, o.matchday_number
"""
df = pd.read_sql_query(query, conn)
conn.close()

# Remove vf:season: prefix for cleaner matching
df['season'] = df['season'].astype(str).str.replace('vf:season:', '')

# ---------------------------------------------------------
# 1. MACRO-CONSTRAINTS (Engine Tension & Archetype)
# ---------------------------------------------------------
print("Calculating Macro-Constraints (Tension & Archetype)...")

# Archetype (Goals in MD 1-4)
early_goals = df[df['day'] <= 4].groupby('season').apply(lambda x: (x['h'] + x['a']).sum(), include_groups=False).reset_index(name='archetype_goals')
df = df.merge(early_goals, on='season', how='left')

# Cumulative Tension
df['match_goals'] = df['h'] + df['a']
md_totals = df.groupby(['season', 'day'])['match_goals'].sum().reset_index(name='md_goals')
md_totals['cumulative_goals'] = md_totals.groupby('season')['md_goals'].cumsum()
md_totals['expected_goals'] = md_totals['day'] * 19.9
md_totals['tension'] = md_totals['cumulative_goals'] - md_totals['expected_goals']

# We need the tension from the PREVIOUS matchday (so we don't leak the future)
md_totals['prev_tension'] = md_totals.groupby('season')['tension'].shift(1).fillna(0)
df = df.merge(md_totals[['season', 'day', 'prev_tension']], on=['season', 'day'], how='left')


# ---------------------------------------------------------
# 2. MICRO-CONSTRAINTS (Rolling League Table & Quotas)
# ---------------------------------------------------------
print("Calculating Micro-Constraints (Rolling League Table & Point Quotas)...")

home_results = df[['season', 'day', 'home', 'h', 'a']].copy()
home_results.rename(columns={'home': 'team', 'h': 'gf', 'a': 'ga'}, inplace=True)
home_results['pts'] = np.where(home_results['gf'] > home_results['ga'], 3, np.where(home_results['gf'] == home_results['ga'], 1, 0))

away_results = df[['season', 'day', 'away', 'a', 'h']].copy()
away_results.rename(columns={'away': 'team', 'a': 'gf', 'h': 'ga'}, inplace=True)
away_results['pts'] = np.where(away_results['gf'] > away_results['ga'], 3, np.where(away_results['gf'] == away_results['ga'], 1, 0))

df_teams = pd.concat([home_results, away_results], ignore_index=True)
df_teams.sort_values(['season', 'day'], inplace=True)

df_teams['gd'] = df_teams['gf'] - df_teams['ga']
df_teams['cum_pts'] = df_teams.groupby(['season', 'team'])['pts'].cumsum()
df_teams['cum_gd'] = df_teams.groupby(['season', 'team'])['gd'].cumsum()

# Shift 1 matchday (we only know the table state BEFORE the match starts)
df_teams['prev_pts'] = df_teams.groupby(['season', 'team'])['cum_pts'].shift(1).fillna(0)
df_teams['prev_gd'] = df_teams.groupby(['season', 'team'])['cum_gd'].shift(1).fillna(0)

# Calculate Rankings
df_teams.sort_values(['season', 'day', 'prev_pts', 'prev_gd'], ascending=[True, True, False, False], inplace=True)
df_teams['rank'] = df_teams.groupby(['season', 'day']).cumcount() + 1
df_teams['tier'] = pd.cut(df_teams['rank'], bins=[0, 5, 10, 15, 20], labels=[1, 2, 3, 4]) # 1=Top, 4=Bottom

# Point Quota Deficit (Expected Points based on Tier)
# A Tier 1 team expects to finish with ~75 pts (2.5 pts/game)
# A Tier 4 team expects to finish with ~25 pts (0.83 pts/game)
tier_expected_pts_per_game = {1: 2.3, 2: 1.6, 3: 1.1, 4: 0.8}
df_teams['expected_pts'] = df_teams['day'] * df_teams['tier'].map(tier_expected_pts_per_game).astype(float)
df_teams['quota_deficit'] = df_teams['prev_pts'] - df_teams['expected_pts']

# Merge back into main match dataframe
home_ranks = df_teams[['season', 'day', 'team', 'prev_pts', 'prev_gd', 'rank', 'tier', 'quota_deficit']].rename(
    columns={'team': 'home', 'prev_pts': 'h_pts', 'prev_gd': 'h_gd', 'rank': 'h_rank', 'tier': 'h_tier', 'quota_deficit': 'h_quota'}
)
away_ranks = df_teams[['season', 'day', 'team', 'prev_pts', 'prev_gd', 'rank', 'tier', 'quota_deficit']].rename(
    columns={'team': 'away', 'prev_pts': 'a_pts', 'prev_gd': 'a_gd', 'rank': 'a_rank', 'tier': 'a_tier', 'quota_deficit': 'a_quota'}
)

df = df.merge(home_ranks, on=['season', 'day', 'home'], how='left')
df = df.merge(away_ranks, on=['season', 'day', 'away'], how='left')

# Drop early matchdays where Table hasn't settled (MD 1 to 5)
df_final = df[df['day'] >= 6].copy()

# ---------------------------------------------------------
# 3. REPRESENTATION CONSTRAINT (Odds Clusters)
# ---------------------------------------------------------
print("Classifying Odds Fingerprints into DNA Clusters...")
import math
CLUSTER_CENTROIDS = [
    [0.8547, 0.6250, 0.5263, 0.6803],  [0.6993, 0.4255, 0.4505, 0.8475],
    [0.6711, 0.3968, 0.4673, 0.8696],  [0.8000, 0.5464, 0.5882, 0.7576],
    [0.7576, 0.4950, 0.4237, 0.8000],  [0.7353, 0.4630, 0.4902, 0.8197],
    [0.8333, 0.5882, 0.5747, 0.7143],  [0.8475, 0.6173, 0.6289, 0.6897],
]

def classify(row):
    vec = [1.0/row['o15'], 1.0/row['o25'], 1.0/row['gg'], 1.0/row['u35']]
    best_dist = float('inf')
    best_cluster = -1
    for i, centroid in enumerate(CLUSTER_CENTROIDS):
        d = math.sqrt(sum((x - y) ** 2 for x, y in zip(vec, centroid)))
        if d < best_dist:
            best_dist = d
            best_cluster = i
    return best_cluster

df_final['odds_cluster'] = df_final.apply(classify, axis=1)

# Save Matrix
OUT_DIR = "/home/ubuntu/faith-workspace/vfl-empire/data"
os.makedirs(OUT_DIR, exist_ok=True)
OUT_PATH = os.path.join(OUT_DIR, "unified_ml_matrix.parquet")
df_final.to_parquet(OUT_PATH)

print(f"\nUnified Data Matrix built successfully!")
print(f"Total Matches Indexed: {len(df_final)}")
print(f"Saved to: {OUT_PATH}")
print("\nReady for Phase 2: Supervised Learning Extraction.")
