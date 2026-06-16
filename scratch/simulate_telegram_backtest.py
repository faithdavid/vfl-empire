import json
import sqlite3
import pandas as pd
import numpy as np
import requests
import time

TELEGRAM_TOKEN = "8939731870:AAGIPK4PYrR2Nfmxeir1t7iS7sn68uxVBHA"
TELEGRAM_CHAT_ID = "5705670725"

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

print("Loading data...")
conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db')
query = """
SELECT season, day, home, away, h, a, total, gg, o25
FROM matches
WHERE season IS NOT NULL AND total IS NOT NULL
"""
df = pd.read_sql_query(query, conn)
conn.close()

df['season_num'] = df['season'].astype(str).str.extract(r'(\d+)').astype(float)
max_season = df['season_num'].max()
df['season_num'].fillna(max_season, inplace=True)

home_results = df[['season', 'season_num', 'day', 'home', 'h', 'a']].copy()
home_results.rename(columns={'home': 'team', 'h': 'gf', 'a': 'ga'}, inplace=True)
home_results['pts'] = np.where(home_results['gf'] > home_results['ga'], 3, np.where(home_results['gf'] == home_results['ga'], 1, 0))

away_results = df[['season', 'season_num', 'day', 'away', 'a', 'h']].copy()
away_results.rename(columns={'away': 'team', 'a': 'gf', 'h': 'ga'}, inplace=True)
away_results['pts'] = np.where(away_results['gf'] > away_results['ga'], 3, np.where(away_results['gf'] == away_results['ga'], 1, 0))

df_teams = pd.concat([home_results, away_results], ignore_index=True)
df_teams.sort_values(['season', 'day'], inplace=True)
df_teams['gd'] = df_teams['gf'] - df_teams['ga']

df_teams['cum_pts'] = df_teams.groupby(['season', 'team'])['pts'].cumsum()
df_teams['cum_gd'] = df_teams.groupby(['season', 'team'])['gd'].cumsum()
df_teams['cum_gf'] = df_teams.groupby(['season', 'team'])['gf'].cumsum()

# The 2-Matchday Lag (shift(2))
df_teams['prev_pts'] = df_teams.groupby(['season', 'team'])['cum_pts'].shift(2).fillna(0)
df_teams['prev_gd'] = df_teams.groupby(['season', 'team'])['cum_gd'].shift(2).fillna(0)
df_teams['prev_gf'] = df_teams.groupby(['season', 'team'])['cum_gf'].shift(2).fillna(0)

df_teams.sort_values(['season', 'day', 'prev_pts', 'prev_gd', 'prev_gf'], ascending=[True, True, False, False, False], inplace=True)
df_teams['rank'] = df_teams.groupby(['season', 'day']).cumcount() + 1
df_teams['lag_tier'] = pd.cut(df_teams['rank'], bins=[0, 4, 8, 12, 16], labels=['T1', 'T2', 'T3', 'T4'])

home_ranks = df_teams[['season', 'day', 'team', 'lag_tier']].rename(columns={'team': 'home', 'lag_tier': 'lag_home_tier'})
away_ranks = df_teams[['season', 'day', 'team', 'lag_tier']].rename(columns={'team': 'away', 'lag_tier': 'lag_away_tier'})

df = df.merge(home_ranks, on=['season', 'day', 'home'], how='left')
df = df.merge(away_ranks, on=['season', 'day', 'away'], how='left')
df['season_phase'] = np.ceil(df['day'] / 2.0).astype(int)

df_valid = df[df['season_phase'] >= 2].copy()

with open('/home/ubuntu/faith-workspace/vfl-empire/data/phase_fixture_locks_bulletproof.json', 'r') as f:
    locks_list = json.load(f)
locks_db = { (str(l['home']), str(l['away']), str(l['home_tier']), str(l['away_tier']), int(l['phase'])): l['lock'] for l in locks_list }

# Explicitly filter for VFLM 5276 through VFLM 5295
test_seasons = list(range(5276, 5296))
df_test = df_valid[df_valid['season_num'].isin(test_seasons)].sort_values(by=['season_num', 'day'])

unique_mds = df_test[['season_num', 'day']].drop_duplicates().values.tolist()
unique_mds = [(int(s), int(d)) for s, d in unique_mds]

STARTING_STAKE = 140.0
CYCLE_RESET_STAKE = 1000.0
TARGET_CYCLE_BETS = 12

current_stake = STARTING_STAKE
bets_in_cycle = 0
cycle_num = 1
total_banked = 0.0

last_absolute_md = None
total_simulated_minutes = 0

send_telegram("🧪 *INITIALIZING VFL SIMULATION*\nRunning chronological backtest exactly from VFLM 5276 to VFLM 5295 (20 Seasons).")

for _, row in df_test.iterrows():
    key = (str(row['home']), str(row['away']), str(row['lag_home_tier']), str(row['lag_away_tier']), int(row['season_phase']))
    
    if key in locks_db:
        prediction = locks_db[key]
        
        current_md_tuple = (int(row['season_num']), int(row['day']))
        current_md_idx = unique_mds.index(current_md_tuple)
        
        if last_absolute_md is None:
            wait_mds = 0
        else:
            wait_mds = current_md_idx - last_absolute_md
            
        last_absolute_md = current_md_idx
        
        wait_mins = wait_mds * 4
        total_simulated_minutes += wait_mins
        wait_h = int(wait_mins // 60)
        wait_m = int(wait_mins % 60)
        
        # Simulate odds
        odds = 1.70 if prediction == 'hw' else 2.10 if prediction == 'aw' else 3.00
        
        stake = current_stake
        returns = stake * odds
        
        bets_in_cycle += 1
        current_stake = returns
        
        msg = f"  - Bet {bets_in_cycle}/12: VFLM {int(row['season_num'])} | MD {int(row['day']):<2} | {row['home']} vs {row['away']} ({prediction.upper()})"
        send_telegram(msg)
        time.sleep(1.0)
        
        if bets_in_cycle >= TARGET_CYCLE_BETS:
            send_telegram(f"🎉 *--- Cycle {cycle_num} Complete ---*")
            current_stake = CYCLE_RESET_STAKE
            bets_in_cycle = 0
            cycle_num += 1

send_telegram("✅ *Done sending summary.*")
