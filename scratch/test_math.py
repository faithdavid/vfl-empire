import pandas as pd
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

df, max_s = extract_panel_data_with_standings()
group = df[(df['home'] == 'West Ham') & (df['away'] == 'London Guns') & (df['home_micro'] == 'E') & (df['away_micro'] == 'B')].copy()

group = group.sort_values(by='season_num')
n = len(group)
weights = [(1.15 ** i) for i in range(n)]
sum_weight = sum(weights)

w_total = group['total'].astype(float).values * weights
print("Weights:", weights)
print("Totals:", group['total'].values)
print("Weighted Avg Total:", w_total.sum() / sum_weight)

