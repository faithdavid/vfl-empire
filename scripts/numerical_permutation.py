import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import psycopg2
import os

print("Fetching fixtures for Numerical Permutation Mapping...")
conn = psycopg2.connect(dbname='vfl_empire', user='vfl_user', password='vfl_pass', host='localhost')

# We pick one complete season to visualize the permutation structure
query = """
    SELECT matchday_number as day, home_team as home, away_team as away
    FROM vfl_fixture_aligned
    WHERE season_id = 'vf:season:3092961'
    ORDER BY matchday_number
"""
df = pd.read_sql_query(query, conn)
conn.close()

# 1. Numerically Encode Teams
# We will encode them based roughly on their power Tier so numbers 1-4 are elite, 13-16 are bottom
team_encoding = {
    'Manchester Blue': 1, 'London Guns': 2, 'Chelsea': 3, 'Liverpool': 4,
    'Tottenham': 5, 'Newcastle': 6, 'Aston Villa': 7, 'Brighton': 8,
    'West Ham': 9, 'Manchester Red': 10, 'Crystal Palace': 11, 'Fulham': 12,
    'Everton': 13, 'Wolverhampton': 14, 'Bournemouth': 15, 'Leeds': 16
}

# Apply Encoding
df['home_id'] = df['home'].map(team_encoding)
df['away_id'] = df['away'].map(team_encoding)

# 2. Build the Permutation Matrices (30 days x 16 teams)
# Matrix 1: The Opponent ID
opponent_matrix = np.zeros((16, 30))
# Matrix 2: The Opponent Tier (for difficulty heatmapping)
difficulty_matrix = np.zeros((16, 30))

for _, row in df.iterrows():
    md = int(row['day']) - 1 # 0-indexed
    h_id = int(row['home_id'])
    a_id = int(row['away_id'])
    
    # Fill for Home team
    opponent_matrix[h_id - 1, md] = a_id # Positive = Home Game
    # Difficulty: if opponent is ID 1-4 (Tier 1), difficulty is high (4).
    # If opponent is ID 13-16 (Tier 4), difficulty is low (1).
    # Math: Tier = (a_id - 1) // 4 + 1. 
    # We invert it so Tier 1 (Elite) is difficulty 4.
    opp_tier = (a_id - 1) // 4 + 1
    difficulty_matrix[h_id - 1, md] = 5 - opp_tier 
    
    # Fill for Away team
    opponent_matrix[a_id - 1, md] = -h_id # Negative = Away Game
    opp_tier_away = (h_id - 1) // 4 + 1
    difficulty_matrix[a_id - 1, md] = 5 - opp_tier_away

# 3. Export Numerical Matrix to CSV for Data Exploration
teams_sorted = sorted(team_encoding.items(), key=lambda x: x[1])
team_names = [t[0] for t in teams_sorted]

perm_df = pd.DataFrame(opponent_matrix, index=team_names, columns=[f"MD{i}" for i in range(1, 31)])
out_dir = '/home/ubuntu/.gemini/antigravity-cli/brain/eebe6828-3ff7-43e5-bdf7-e6f836545559/scratch'
os.makedirs(out_dir, exist_ok=True)
perm_df.to_csv(f'{out_dir}/numerical_fixture_permutation.csv')

# 4. Plot the Fixture Difficulty Heatmap
plt.figure(figsize=(20, 10))
sns.heatmap(difficulty_matrix, cmap='YlOrRd', 
            xticklabels=[str(i) for i in range(1, 31)], 
            yticklabels=team_names,
            linewidths=0.5, linecolor='gray', cbar_kws={'label': 'Opponent Difficulty (4=Hardest, 1=Easiest)'})

plt.title("VFL Fixture Permutation Roadmap (Difficulty Matrix)", fontsize=18, fontweight='bold')
plt.xlabel("Matchday (1-30)", fontsize=14)
plt.ylabel("Team (Ranked 1 to 16)", fontsize=14)
plt.tight_layout()
plt.savefig(f'{out_dir}/fixture_permutation_heatmap.png', dpi=300)
plt.close()

print("Numerical Permutation Matrix and Heatmap generated successfully.")
