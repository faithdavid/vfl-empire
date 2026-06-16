import sqlite3
import pandas as pd

conn = sqlite3.connect("/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db")
df = pd.read_sql_query("SELECT season, day FROM matches", conn)
df['season_num'] = pd.to_numeric(df['season'], errors='coerce')
max_s = df['season_num'].max()
print("Max season:", max_s)
print("Total fixtures in max season:", len(df[df['season_num'] == max_s]))
print("Total fixtures in max-1 season:", len(df[df['season_num'] == max_s - 1]))
