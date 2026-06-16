import pandas as pd
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

df, _ = extract_panel_data_with_standings()

matches = df[(df['home'] == 'West Ham') & (df['away'] == 'London Guns') & (df['home_micro'] == 'E') & (df['away_micro'] == 'B')]
print(f"Total historical matches for this Micro-Tier combo: {len(matches)}")
for _, m in matches.iterrows():
    print(f"Season: {m['season']} | MD: {m['day']} | Score: {m['h']}-{m['a']} | Total: {m['total']} | GG: {m['gg']}")
