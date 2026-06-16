import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

print("Loading ML Matrix for Overlap Analysis...")
df = pd.read_parquet('/home/ubuntu/faith-workspace/vfl-empire/data/unified_ml_matrix.parquet')

# Drop invalid or completely null rows
df = df.dropna(subset=['prev_tension', 'h_quota', 'a_quota', 'target_1x2', 'odds_cluster'])

out_dir = '/home/ubuntu/.gemini/antigravity-cli/brain/eebe6828-3ff7-43e5-bdf7-e6f836545559/scratch'
os.makedirs(out_dir, exist_ok=True)
sns.set_theme(style="darkgrid")

# Map target back to readable strings
outcome_map = {0: 'Home Win', 1: 'Draw', 2: 'Away Win'}
df['Outcome'] = df['target_1x2'].map(outcome_map)

# 1. 2D KDE Density Plot (Phase Space): Quota Deficits vs Tension
# This shows where the "gravitational pull" of the engine forces outcomes
plt.figure(figsize=(12, 8))
# We just plot Home Wins vs Away Wins for clarity
subset = df[df['target_1x2'].isin([0, 2])]
sns.kdeplot(
    data=subset, x='h_quota', y='prev_tension', hue='Outcome',
    fill=True, alpha=0.5, palette={'Home Win': 'blue', 'Away Win': 'red'},
    levels=8, thresh=0.1
)
plt.title('Engine Phase Space: Home Quota Deficit vs Macro Tension', fontsize=16, fontweight='bold')
plt.xlabel('Home Team Point Quota Deficit (Lower = Desperate)', fontsize=12)
plt.ylabel('Macro Tension (Season Drift)', fontsize=12)
plt.tight_layout()
plt.savefig(f'{out_dir}/phase_space_kde.png', dpi=300)
plt.close()

# 2. Probability Heatmap: Odds Clusters vs Quota Deficit Bins
# Shows the exact overlap where the math guarantees outcomes
df['h_quota_bin'] = pd.qcut(df['h_quota'], q=5, labels=['Desperate', 'Behind', 'On Track', 'Ahead', 'Overperforming'])
df['odds_cluster_bin'] = 'Cluster ' + df['odds_cluster'].astype(int).astype(str)

heatmap_data = df.groupby(['h_quota_bin', 'odds_cluster_bin'])['target_1x2'].apply(lambda x: (x == 0).mean() * 100).unstack()

plt.figure(figsize=(14, 8))
sns.heatmap(heatmap_data, annot=True, fmt=".1f", cmap="YlGnBu", cbar_kws={'label': 'Home Win Probability (%)'})
plt.title('Overlap Matrix: Home Win Probability by DNA Cluster & Quota Deficit', fontsize=16, fontweight='bold')
plt.xlabel('Odds DNA Cluster', fontsize=12)
plt.ylabel('Home Team Quota Status', fontsize=12)
plt.tight_layout()
plt.savefig(f'{out_dir}/overlap_heatmap.png', dpi=300)
plt.close()

# 3. Decision Boundary Scatter (Poisson expected gap vs actual Goal Difference)
# Shows if Poisson math aligns with structural reality or diverges
df['xG_gap'] = df['poisson_hxG'] - df['poisson_axG']
df['gd_gap'] = df['h_gd'] - df['a_gd']

# Take a random sample to avoid massive overplotting
scatter_sample = df.sample(n=3000, random_state=42)

plt.figure(figsize=(12, 8))
sns.scatterplot(
    data=scatter_sample, x='gd_gap', y='xG_gap', hue='Outcome',
    palette={'Home Win': 'blue', 'Draw': 'orange', 'Away Win': 'red'},
    alpha=0.6, s=40
)
plt.axhline(0, color='black', linestyle='--', alpha=0.5)
plt.axvline(0, color='black', linestyle='--', alpha=0.5)
plt.title('Predictive Overlap: Form (Goal Difference Gap) vs Math (xG Gap)', fontsize=16, fontweight='bold')
plt.xlabel('Form Gap (Home GD - Away GD)', fontsize=12)
plt.ylabel('Mathematical Strength Gap (Home xG - Away xG)', fontsize=12)
plt.tight_layout()
plt.savefig(f'{out_dir}/scatter_decision_boundary.png', dpi=300)
plt.close()

print("Overlap plots generated.")
