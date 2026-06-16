import sqlite3
import pandas as pd

DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"
conn = sqlite3.connect(DB_PATH)
df = pd.read_sql_query("SELECT season, day, home, away, total FROM matches WHERE home='Bournemouth' AND away='Liverpool'", conn)

print("Total matches between Bournemouth and Liverpool:", len(df))
print("Over 3.5 matches:", len(df[df['total'] > 3.5]))
print("Under 3.5 matches:", len(df[df['total'] < 3.5]))

# Run vfl_standings_pattern_miner logic manually on the exact subset
import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_standings_pattern_miner import extract_panel_data_with_standings

df, max_s = extract_panel_data_with_standings()
target_group = df[(df['home'] == 'Bournemouth') & (df['away'] == 'Liverpool') & (df['home_tier'] == 'T4') & (df['away_tier'] == 'T1')]
print(f"Target Group Matches: {len(target_group)}")
if len(target_group) > 0:
    print(f"Target Group Under 3.5: {sum(target_group['total'] < 3.5)}")
    print(f"Target Group Over 3.5: {sum(target_group['total'] > 3.5)}")

