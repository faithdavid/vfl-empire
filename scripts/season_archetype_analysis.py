#!/usr/bin/env python3
import psycopg2
import pandas as pd
from sklearn.cluster import KMeans
import numpy as np
from scipy.stats import pearsonr

conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")

# Extract Season-level features based on MD 1-4 vs MD 5-30
query = """
    WITH md_stats AS (
        SELECT 
            season, 
            day,
            SUM(h+a) as total_goals,
            SUM(CASE WHEN h = a THEN 1 ELSE 0 END) as draws,
            SUM(CASE WHEN h+a > 2 THEN 1 ELSE 0 END) as o25
        FROM matches
        WHERE h IS NOT NULL AND a IS NOT NULL
        GROUP BY season, day
        HAVING COUNT(*) = 8
    )
    SELECT 
        season,
        SUM(CASE WHEN day <= 4 THEN total_goals ELSE 0 END) as early_goals,
        SUM(CASE WHEN day <= 4 THEN draws ELSE 0 END) as early_draws,
        SUM(CASE WHEN day <= 4 THEN o25 ELSE 0 END) as early_o25,
        
        SUM(CASE WHEN day > 4 THEN total_goals ELSE 0 END) as rest_goals,
        SUM(CASE WHEN day > 4 THEN draws ELSE 0 END) as rest_draws,
        SUM(CASE WHEN day > 4 THEN o25 ELSE 0 END) as rest_o25
    FROM md_stats
    GROUP BY season
    HAVING COUNT(day) = 30
"""

df = pd.read_sql_query(query, conn)
print(f"Loaded {len(df)} complete seasons for Archetype Analysis.\n")

if len(df) == 0:
    print("Not enough complete seasons to analyze.")
    exit()

# 1. Pearson Correlation (Does early season predict the rest of the season?)
print("--- MACRO-SEASON CORRELATION (MD 1-4 vs MD 5-30) ---")
corr_goals, _ = pearsonr(df['early_goals'], df['rest_goals'])
corr_draws, _ = pearsonr(df['early_draws'], df['rest_draws'])
corr_o25, _ = pearsonr(df['early_o25'], df['rest_o25'])

print(f"Goals Correlation: {corr_goals:.3f}")
print(f"Draws Correlation: {corr_draws:.3f}")
print(f"Over 2.5 Correlation: {corr_o25:.3f}\n")

if corr_goals < -0.3:
    print("-> CONCLUSION: Strong RUBBER-BAND effect. If MD 1-4 are high scoring, the rest of the season is suppressed.")
elif corr_goals > 0.3:
    print("-> CONCLUSION: Strong MOMENTUM effect. An 'Over' season stays 'Over' the whole way through.")
else:
    print("-> CONCLUSION: NO CORRELATION. The engine forces a hard mean-reversion regardless of how the season starts.\n")

# 2. Season Archetype Clustering (Using only the first 4 matchdays)
print("--- SEASON ARCHETYPES (Clustering based on MD 1-4) ---")
X = df[['early_goals', 'early_draws', 'early_o25']]
kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
df['archetype'] = kmeans.fit_predict(X)

arch_summary = df.groupby('archetype').agg(
    count=('season', 'count'),
    avg_early_goals=('early_goals', 'mean'),
    avg_rest_goals=('rest_goals', 'mean')
).reset_index()

arch_summary['expected_rest_goals_baseline'] = arch_summary['avg_early_goals'] * (26/4) # If it scaled linearly
arch_summary['deviation_from_baseline'] = arch_summary['avg_rest_goals'] - arch_summary['expected_rest_goals_baseline']

for _, row in arch_summary.iterrows():
    print(f"Archetype {int(row['archetype'])} ({row['count']} seasons):")
    print(f"  MD 1-4 Avg Goals: {row['avg_early_goals']:.1f}")
    print(f"  MD 5-30 Avg Goals: {row['avg_rest_goals']:.1f}")
    print(f"  Linear Expectation vs Reality: {row['expected_rest_goals_baseline']:.1f} expected -> {row['avg_rest_goals']:.1f} actual (Diff: {row['deviation_from_baseline']:+.1f} goals)")
    print()

conn.close()
