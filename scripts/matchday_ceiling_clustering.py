#!/usr/bin/env python3
import psycopg2
import pandas as pd
from sklearn.cluster import KMeans
import numpy as np

conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")

print("=== MACRO-DISTRIBUTION ENGINE: Matchday Ceilings & K-Means Clusters ===")

# Query to get Matchday Totals (Home Wins, Away Wins, Draws, Total Goals, O2.5 hits)
query = """
    SELECT 
        season, 
        day, 
        COUNT(*) as total_matches,
        SUM(CASE WHEN h > a THEN 1 ELSE 0 END) as home_wins,
        SUM(CASE WHEN h < a THEN 1 ELSE 0 END) as away_wins,
        SUM(CASE WHEN h = a THEN 1 ELSE 0 END) as draws,
        SUM(h + a) as total_goals,
        SUM(CASE WHEN h + a > 2 THEN 1 ELSE 0 END) as over_2_5
    FROM matches
    WHERE h IS NOT NULL AND a IS NOT NULL
    GROUP BY season, day
    HAVING COUNT(*) = 8
"""

df = pd.read_sql_query(query, conn)
print(f"Loaded {len(df)} complete Matchdays (8 matches each).\n")

# 1. Evaluate Ceilings (Min/Max distributions)
print("--- THE VFL CEILINGS ---")
print(f"Max Goals in a single Matchday: {df['total_goals'].max()}")
print(f"Min Goals in a single Matchday: {df['total_goals'].min()}")
print(f"Average Goals per Matchday: {df['total_goals'].mean():.1f}")
print(f"Max Home Wins in a Matchday: {df['home_wins'].max()} (out of 8)")
print(f"Max Away Wins in a Matchday: {df['away_wins'].max()} (out of 8)")
print(f"Max Draws in a Matchday: {df['draws'].max()} (out of 8)")
print(f"Max Over 2.5s in a Matchday: {df['over_2_5'].max()} (out of 8)\n")

# 2. K-Means Clustering to find MSport's "Templates"
print("--- K-MEANS CLUSTERING (FINDING THE ENGINE TEMPLATES) ---")
# We will cluster the Matchdays into 5 distinct macro-templates based on goals and outcomes
X = df[['home_wins', 'away_wins', 'draws', 'total_goals', 'over_2_5']]

kmeans = KMeans(n_clusters=5, random_state=42, n_init=10)
df['cluster'] = kmeans.fit_predict(X)

# Analyze the clusters
cluster_summary = df.groupby('cluster').agg(
    count=('season', 'count'),
    avg_hw=('home_wins', 'mean'),
    avg_aw=('away_wins', 'mean'),
    avg_dr=('draws', 'mean'),
    avg_goals=('total_goals', 'mean'),
    avg_o25=('over_2_5', 'mean')
).reset_index()

cluster_summary['frequency_%'] = (cluster_summary['count'] / len(df)) * 100
cluster_summary = cluster_summary.sort_values('avg_goals')

for _, row in cluster_summary.iterrows():
    c = row['cluster']
    print(f"Template {c} (Happens {row['frequency_%']:.1f}% of the time):")
    print(f"  Goals: {row['avg_goals']:.1f} | O2.5 Hits: {row['avg_o25']:.1f}/8")
    print(f"  Distribution -> Home: {row['avg_hw']:.1f} | Away: {row['avg_aw']:.1f} | Draws: {row['avg_dr']:.1f}")
    print(f"  Interpretation: ", end="")
    if row['avg_goals'] < 16:
        print("Under/Boring Template. High Draws, Low Scoring.")
    elif row['avg_goals'] > 22:
        print("Over/Explosive Template. High Away Wins, High Scoring.")
    elif row['avg_hw'] > 4:
        print("Home Bias Template. The engine heavily favors Home teams.")
    else:
        print("Balanced/Standard Template. MSport's default state.")
    print()

conn.close()
