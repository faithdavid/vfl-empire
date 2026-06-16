import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import psycopg2
import os

print("Generating Odds DNA Heatmaps...")
conn = psycopg2.connect(dbname='vfl_empire', user='vfl_user', password='vfl_pass', host='localhost')

# Fetch Fixtures
query_fixtures = """
    SELECT season_id, matchday_number, home_team, away_team, home_goals, away_goals
    FROM vfl_fixture_aligned
    WHERE home_goals IS NOT NULL
"""
df_fixtures = pd.read_sql_query(query_fixtures, conn)

# Fetch Odds
query_odds = """
    SELECT season_id, matchday_number, home_team, away_team, gg, o25
    FROM vfl_odds_v2
"""
df_odds = pd.read_sql_query(query_odds, conn)
conn.close()

df_odds = df_odds.drop_duplicates(subset=['season_id', 'matchday_number', 'home_team', 'away_team'])

# Merge
df = pd.merge(df_fixtures, df_odds, on=['season_id', 'matchday_number', 'home_team', 'away_team'], how='inner')

elite_teams = ['Manchester Blue', 'London Guns', 'Chelsea', 'Liverpool']
weak_teams = ['West Ham', 'Manchester Red', 'Crystal Palace', 'Fulham', 'Everton', 'Wolverhampton', 'Bournemouth', 'Leeds']

# 1. Macro Filter: All Elite vs Weak matches
df_macro = df[(df['home_team'].isin(elite_teams)) & (df['away_team'].isin(weak_teams))].copy()
df_macro['target'] = (df_macro['home_goals'] > df_macro['away_goals']).astype(int)

# Bin the odds to create a clean heatmap
# GG usually ranges from 1.3 to 2.5. O25 ranges from 1.3 to 2.5
df_macro['gg_bin'] = pd.cut(df_macro['gg'], bins=np.arange(1.3, 2.6, 0.1), labels=np.arange(1.35, 2.55, 0.1))
df_macro['o25_bin'] = pd.cut(df_macro['o25'], bins=np.arange(1.3, 2.6, 0.1), labels=np.arange(1.35, 2.55, 0.1))

# Heatmap Data: Win Rate
heatmap_data = df_macro.groupby(['gg_bin', 'o25_bin'])['target'].mean().unstack() * 100
# Heatmap Data: Sample Size
count_data = df_macro.groupby(['gg_bin', 'o25_bin'])['target'].count().unstack()

# Mask cells with fewer than 10 matches to avoid noise
mask = count_data < 10

out_dir = '/home/ubuntu/.gemini/antigravity-cli/brain/eebe6828-3ff7-43e5-bdf7-e6f836545559/scratch'
os.makedirs(out_dir, exist_ok=True)

plt.figure(figsize=(14, 8))
sns.heatmap(heatmap_data, mask=mask, cmap='RdYlGn', annot=True, fmt=".1f", 
            cbar_kws={'label': 'Home Win Rate (%)'}, linewidths=0.5)

plt.title('Macro Odds DNA: Elite vs Weak Home Win Rate (Sample Size >= 10)', fontsize=16, fontweight='bold')
plt.xlabel('Over 2.5 Odds', fontsize=12)
plt.ylabel('Goal-Goal (GG) Odds', fontsize=12)
plt.gca().invert_yaxis()
plt.tight_layout()
plt.savefig(f'{out_dir}/odds_dna_macro_heatmap.png', dpi=300)
plt.close()

# Plot 2: Scatter plot of Volume vs Win Rate for specific clusters
cluster_stats = df_macro.groupby(['gg', 'o25'])['target'].agg(['count', 'mean']).reset_index()
cluster_stats['mean'] = cluster_stats['mean'] * 100
cluster_stats = cluster_stats[cluster_stats['count'] >= 5]

plt.figure(figsize=(12, 6))
scatter = plt.scatter(cluster_stats['count'], cluster_stats['mean'], 
                      c=cluster_stats['mean'], cmap='RdYlGn', s=cluster_stats['count']*5, alpha=0.7, edgecolors='black')

plt.title('Odds Cluster Reliability: Sample Size vs Win Rate', fontsize=16, fontweight='bold')
plt.xlabel('Number of Matches in Cluster', fontsize=12)
plt.ylabel('Home Win Rate (%)', fontsize=12)
plt.axhline(y=62, color='blue', linestyle='--', label='Structural Baseline (62%)')
plt.axhline(y=80, color='green', linestyle='--', label='High Confidence (80%)')
plt.colorbar(scatter, label='Win Rate (%)')
plt.legend()
plt.tight_layout()
plt.savefig(f'{out_dir}/odds_cluster_scatter.png', dpi=300)
plt.close()

print("Odds DNA Pandas Graphs generated.")
