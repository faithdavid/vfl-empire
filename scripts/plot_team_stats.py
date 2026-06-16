import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import psycopg2
import os

print("Connecting to DB...")
conn = psycopg2.connect(dbname='vfl_empire', user='vfl_user', password='vfl_pass', host='localhost')
query = """
    SELECT 
        home_team,
        away_team,
        home_goals,
        away_goals
    FROM vfl_fixture_aligned
    WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
"""
df = pd.read_sql_query(query, conn)
conn.close()

print(f"Loaded {len(df)} matches.")

# Determine outcomes
df['home_win'] = (df['home_goals'] > df['away_goals']).astype(int)
df['draw'] = (df['home_goals'] == df['away_goals']).astype(int)
df['away_win'] = (df['home_goals'] < df['away_goals']).astype(int)

# Group by Home Team
home_stats = df.groupby('home_team').agg(
    home_matches=('home_team', 'count'),
    home_wins=('home_win', 'sum'),
    home_draws=('draw', 'sum'),
    home_losses=('away_win', 'sum'),
    home_goals_scored=('home_goals', 'sum'),
    home_goals_conceded=('away_goals', 'sum')
).reset_index().rename(columns={'home_team': 'team'})

# Group by Away Team
away_stats = df.groupby('away_team').agg(
    away_matches=('away_team', 'count'),
    away_wins=('away_win', 'sum'),
    away_draws=('draw', 'sum'),
    away_losses=('home_win', 'sum'),
    away_goals_scored=('away_goals', 'sum'),
    away_goals_conceded=('home_goals', 'sum')
).reset_index().rename(columns={'away_team': 'team'})

# Merge
stats = pd.merge(home_stats, away_stats, on='team')

# Calculate percentages for fairer comparison (some teams might have slightly different total matches if partial data)
stats['total_matches'] = stats['home_matches'] + stats['away_matches']
stats['home_win_pct'] = stats['home_wins'] / stats['home_matches'] * 100
stats['away_win_pct'] = stats['away_wins'] / stats['away_matches'] * 100
stats['draw_pct'] = (stats['home_draws'] + stats['away_draws']) / stats['total_matches'] * 100

stats['home_goals_per_game'] = stats['home_goals_scored'] / stats['home_matches']
stats['away_goals_per_game'] = stats['away_goals_scored'] / stats['away_matches']

# Sort alphabetically or by total wins to make chart readable
stats = stats.sort_values('team')

# Set aesthetic style
sns.set_theme(style="whitegrid")

# Create output dir
out_dir = '/home/ubuntu/.gemini/antigravity-cli/brain/eebe6828-3ff7-43e5-bdf7-e6f836545559/scratch'
os.makedirs(out_dir, exist_ok=True)

# 1. Plot Outcomes (Home Win %, Away Win %, Draw %)
plt.figure(figsize=(16, 8))
bar_width = 0.25
x = range(len(stats['team']))

plt.bar([i - bar_width for i in x], stats['home_win_pct'], width=bar_width, label='Home Win %', color='#2ca02c')
plt.bar(x, stats['away_win_pct'], width=bar_width, label='Away Win %', color='#1f77b4')
plt.bar([i + bar_width for i in x], stats['draw_pct'], width=bar_width, label='Draw %', color='#ff7f0e')

plt.xlabel('Teams', fontsize=12, fontweight='bold')
plt.ylabel('Percentage (%)', fontsize=12, fontweight='bold')
plt.title('Win/Draw Percentages by Team (Home vs Away)', fontsize=16, fontweight='bold')
plt.xticks(x, stats['team'], rotation=45, ha='right')
plt.legend()
plt.tight_layout()
plt.savefig(f'{out_dir}/team_outcomes.png', dpi=300)
plt.close()

# 2. Plot Goals Scored (Home vs Away)
plt.figure(figsize=(16, 8))
bar_width = 0.35
x = range(len(stats['team']))

plt.bar([i - bar_width/2 for i in x], stats['home_goals_per_game'], width=bar_width, label='Home Goals / Game', color='#d62728')
plt.bar([i + bar_width/2 for i in x], stats['away_goals_per_game'], width=bar_width, label='Away Goals / Game', color='#9467bd')

plt.xlabel('Teams', fontsize=12, fontweight='bold')
plt.ylabel('Goals per Game', fontsize=12, fontweight='bold')
plt.title('Average Goals Scored per Game by Team (Home vs Away)', fontsize=16, fontweight='bold')
plt.xticks(x, stats['team'], rotation=45, ha='right')
plt.legend()
plt.tight_layout()
plt.savefig(f'{out_dir}/team_goals.png', dpi=300)
plt.close()

print(f"Plots saved successfully to {out_dir}")
