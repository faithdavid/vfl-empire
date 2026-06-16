import pandas as pd
import sqlite3

DB = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"

# 1. We just reuse the existing miner logic to get the dataframe with tiers
import sys
sys.path.append("/home/ubuntu/faith-workspace/vfl-empire/scripts")
from vfl_standings_pattern_miner import extract_panel_data_with_standings

df, _ = extract_panel_data_with_standings()
df.drop_duplicates(subset=['season', 'day', 'home', 'away'], inplace=True)

# Define outcome metrics
df['u25'] = (df['total'] < 2.5).astype(int)
df['o25'] = (df['total'] > 2.5).astype(int)
df['hw'] = (df['h'] > df['a']).astype(int)

print("--- PURE TIER vs TIER ANALYSIS (Agnostic of Teams) ---")
# Group purely by Home Tier vs Away Tier
grouped = df.groupby(['home_tier', 'away_tier'])
results = []
for name, group in grouped:
    count = len(group)
    if count == 0: continue
    
    u25_rate = group['u25'].mean()
    o25_rate = group['o25'].mean()
    hw_rate = group['hw'].mean()
    
    results.append({
        'Matchup': f"Home {name[0]} vs Away {name[1]}",
        'Samples': count,
        'HomeWin%': hw_rate * 100,
        'Under2.5%': u25_rate * 100,
        'Over2.5%': o25_rate * 100
    })

res_df = pd.DataFrame(results).sort_values('Matchup')
print(res_df.to_string(index=False, float_format="%.1f"))

print("\n--- SPECIFIC TEAM vs ANY TIER (Example: Chelsea vs T1) ---")
team_group = df[df['home'] == 'Chelsea'].groupby('away_tier')
res2 = []
for tier, group in team_group:
    res2.append({
        'Scenario': f"Chelsea (Home) vs ANY {tier}",
        'Samples': len(group),
        'ChelseaWin%': group['hw'].mean() * 100,
        'Under2.5%': group['u25'].mean() * 100
    })
print(pd.DataFrame(res2).to_string(index=False, float_format="%.1f"))
