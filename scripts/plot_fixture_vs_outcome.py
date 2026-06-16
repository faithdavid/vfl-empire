import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import psycopg2
import os

print("Fetching data to compare Fixture Difficulty vs Outcomes...")
conn = psycopg2.connect(dbname='vfl_empire', user='vfl_user', password='vfl_pass', host='localhost')

# We pick one complete season
query = """
    SELECT matchday_number as day, home_team as home, away_team as away, home_goals, away_goals
    FROM vfl_fixture_aligned
    WHERE season_id = 'vf:season:3092961' AND home_goals IS NOT NULL
    ORDER BY matchday_number
"""
df = pd.read_sql_query(query, conn)
conn.close()

# 1. Encode Teams
team_encoding = {
    'Manchester Blue': 1, 'London Guns': 2, 'Chelsea': 3, 'Liverpool': 4,
    'Tottenham': 5, 'Newcastle': 6, 'Aston Villa': 7, 'Brighton': 8,
    'West Ham': 9, 'Manchester Red': 10, 'Crystal Palace': 11, 'Fulham': 12,
    'Everton': 13, 'Wolverhampton': 14, 'Bournemouth': 15, 'Leeds': 16
}

df['home_id'] = df['home'].map(team_encoding)
df['away_id'] = df['away'].map(team_encoding)

# 2. Build Matrices (16 teams, 30 days)
difficulty_matrix = np.zeros((16, 30))
outcome_matrix = np.zeros((16, 30)) # 3=Win, 1=Draw, 0=Loss (Points)

for _, row in df.iterrows():
    md = int(row['day']) - 1
    h_id = int(row['home_id'])
    a_id = int(row['away_id'])
    h_goals = row['home_goals']
    a_goals = row['away_goals']
    
    # Calculate Points for Home and Away
    if h_goals > a_goals:
        h_pts = 3; a_pts = 0
    elif h_goals == a_goals:
        h_pts = 1; a_pts = 1
    else:
        h_pts = 0; a_pts = 3
        
    # Home Team
    opp_tier_home = (a_id - 1) // 4 + 1
    difficulty_matrix[h_id - 1, md] = 5 - opp_tier_home # 4=Hard, 1=Easy
    outcome_matrix[h_id - 1, md] = h_pts
    
    # Away Team
    opp_tier_away = (h_id - 1) // 4 + 1
    difficulty_matrix[a_id - 1, md] = 5 - opp_tier_away
    outcome_matrix[a_id - 1, md] = a_pts

teams_sorted = sorted(team_encoding.items(), key=lambda x: x[1])
team_names = [t[0] for t in teams_sorted]

# 3. Calculate Correlation
# Flatten the arrays to calculate correlation across all 480 points (16 teams * 30 days)
flat_diff = difficulty_matrix.flatten()
flat_out = outcome_matrix.flatten()
corr = np.corrcoef(flat_diff, flat_out)[0, 1]
print(f"Mathematical Correlation between Fixture Difficulty and Outcome Points: {corr:.4f}")
# A negative correlation means Higher Difficulty -> Less Points. 

# 4. Plot Side-by-Side Heatmaps
out_dir = '/home/ubuntu/.gemini/antigravity-cli/brain/eebe6828-3ff7-43e5-bdf7-e6f836545559/scratch'
os.makedirs(out_dir, exist_ok=True)

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 16))

# Heatmap 1: Difficulty
sns.heatmap(difficulty_matrix, cmap='YlOrRd', ax=ax1,
            xticklabels=[str(i) for i in range(1, 31)], yticklabels=team_names,
            linewidths=0.5, linecolor='gray', cbar_kws={'label': 'Opponent Difficulty (4=Hardest, 1=Easiest)'})
ax1.set_title("1. Fixture Difficulty Permutation Map", fontsize=18, fontweight='bold')
ax1.set_xlabel("Matchday (1-30)", fontsize=12)

# Heatmap 2: Outcomes (Points)
from matplotlib.colors import ListedColormap
# Custom cmap: Red=Loss(0), Yellow=Draw(1), Green=Win(3)
# We map 0->Red, 1->Yellow, 3->Green
cmap_outcomes = ListedColormap(['#d62728', '#ff7f0e', '#2ca02c'])
# Normalization bounds for discrete points 0, 1, 3
sns.heatmap(outcome_matrix, cmap=cmap_outcomes, ax=ax2,
            xticklabels=[str(i) for i in range(1, 31)], yticklabels=team_names,
            linewidths=0.5, linecolor='gray', cbar_kws={'label': 'Points Earned (0=Loss, 1=Draw, 3=Win)', 'ticks':[0, 1, 3]})
ax2.set_title("2. Actual Match Outcomes (Points Earned)", fontsize=18, fontweight='bold')
ax2.set_xlabel("Matchday (1-30)", fontsize=12)

plt.tight_layout()
plt.savefig(f'{out_dir}/fixture_vs_outcome_overlay.png', dpi=300)
plt.close()

print("Overlay plots generated successfully.")
