import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

print("Loading ML Matrix for Oscillation Analysis...")
df = pd.read_parquet('/home/ubuntu/faith-workspace/vfl-empire/data/unified_ml_matrix.parquet')

out_dir = '/home/ubuntu/.gemini/antigravity-cli/brain/eebe6828-3ff7-43e5-bdf7-e6f836545559/scratch'
os.makedirs(out_dir, exist_ok=True)
sns.set_theme(style="whitegrid")

# 1. Matchday Oscillations (Outcome Probabilities)
md_stats = df.groupby('day')['target_1x2'].value_counts(normalize=True).unstack().fillna(0) * 100
# target_1x2 -> 0: Home, 1: Draw, 2: Away

plt.figure(figsize=(14, 6))
plt.plot(md_stats.index, md_stats[0], marker='o', label='Home Win %', color='blue', linewidth=2)
plt.plot(md_stats.index, md_stats[1], marker='s', label='Draw %', color='orange', linewidth=2)
plt.plot(md_stats.index, md_stats[2], marker='^', label='Away Win %', color='red', linewidth=2)

# Trendlines
import numpy as np
z = np.polyfit(md_stats.index, md_stats[0], 2)
p = np.poly1d(z)
plt.plot(md_stats.index, p(md_stats.index), "b--", alpha=0.5)

plt.title('Matchday Oscillation: Outcome Probabilities from MD1 to MD30', fontsize=16, fontweight='bold')
plt.xlabel('Matchday (1-30)', fontsize=12)
plt.ylabel('Probability (%)', fontsize=12)
plt.xticks(range(1, 31))
plt.legend()
plt.tight_layout()
plt.savefig(f'{out_dir}/matchday_oscillation_outcomes.png', dpi=300)
plt.close()

# 2. Matchday Oscillation (Total Goals)
# Re-load goals from vfl_fixture_aligned
import psycopg2
conn = psycopg2.connect(dbname='vfl_empire', user='vfl_user', password='vfl_pass', host='localhost')
query = """
    SELECT matchday_number as day, (home_goals + away_goals) as total_goals,
           home_goals, away_goals
    FROM vfl_fixture_aligned
    WHERE home_goals IS NOT NULL
"""
goals_df = pd.read_sql_query(query, conn)
conn.close()

goals_md = goals_df.groupby('day')[['total_goals', 'home_goals', 'away_goals']].mean()

plt.figure(figsize=(14, 6))
plt.plot(goals_md.index, goals_md['total_goals'], marker='o', label='Total Goals / Match', color='purple', linewidth=2)
plt.plot(goals_md.index, goals_md['home_goals'], marker='o', label='Home Goals / Match', color='blue', linestyle='--', alpha=0.7)
plt.plot(goals_md.index, goals_md['away_goals'], marker='o', label='Away Goals / Match', color='red', linestyle='--', alpha=0.7)

plt.title('Fixture Goal Oscillation: Scoring Averages from MD1 to MD30', fontsize=16, fontweight='bold')
plt.xlabel('Matchday (1-30)', fontsize=12)
plt.ylabel('Average Goals per Game', fontsize=12)
plt.xticks(range(1, 31))
plt.legend()
plt.tight_layout()
plt.savefig(f'{out_dir}/matchday_oscillation_goals.png', dpi=300)
plt.close()

# Calculate raw correlations with matchday
print("\n--- Matchday Correlation (Oscillation Bias) ---")
print("Correlation of Home Win with Matchday:", df['target_1x2'].apply(lambda x: 1 if x == 0 else 0).corr(df['day']))
print("Correlation of Draw with Matchday:", df['target_1x2'].apply(lambda x: 1 if x == 1 else 0).corr(df['day']))
print("Correlation of Away Win with Matchday:", df['target_1x2'].apply(lambda x: 1 if x == 2 else 0).corr(df['day']))
print("Correlation of Total Goals with Matchday:", goals_df['total_goals'].corr(goals_df['day']))

print("Oscillation plots generated.")
