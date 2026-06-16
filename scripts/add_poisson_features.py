import pandas as pd
import numpy as np
import psycopg2

print("=== POISSON ENGINE INTEGRATION ===")
print("Calculating Base Poisson Expected Goals (xG) to measure Engine Deviation...")

df = pd.read_parquet("/home/ubuntu/faith-workspace/vfl-empire/data/unified_ml_matrix.parquet")

# We need the raw goals to compute attacking and defensive strengths.
conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")
query = """
    SELECT season_id as season, matchday_number as day, 
           home_team as home, away_team as away, 
           home_goals as h, away_goals as a 
    FROM vfl_fixture_aligned 
    WHERE home_goals IS NOT NULL
"""
raw_goals = pd.read_sql_query(query, conn)
conn.close()

# Remove prefix for merging
raw_goals['season'] = raw_goals['season'].astype(str).str.replace('vf:season:', '')

# Compute Rolling Attack/Defense Strengths
# We need expanding or rolling averages to avoid looking into the future.
# For simplicity in this script, we'll calculate season-to-date goals up to the previous matchday.

home_stats = raw_goals[['season', 'day', 'home', 'h', 'a']].rename(columns={'home': 'team', 'h': 'gf', 'a': 'ga'})
home_stats['is_home'] = 1
away_stats = raw_goals[['season', 'day', 'away', 'a', 'h']].rename(columns={'away': 'team', 'a': 'gf', 'h': 'ga'})
away_stats['is_home'] = 0

all_stats = pd.concat([home_stats, away_stats], ignore_index=True)
all_stats.sort_values(['season', 'day'], inplace=True)

# Cumulative goals scored and conceded
all_stats['cum_gf'] = all_stats.groupby(['season', 'team'])['gf'].cumsum()
all_stats['cum_ga'] = all_stats.groupby(['season', 'team'])['ga'].cumsum()
all_stats['matches_played'] = all_stats.groupby(['season', 'team']).cumcount() + 1

# Shift to get stats BEFORE the current match
all_stats['prev_gf'] = all_stats.groupby(['season', 'team'])['cum_gf'].shift(1).fillna(0)
all_stats['prev_ga'] = all_stats.groupby(['season', 'team'])['cum_ga'].shift(1).fillna(0)
all_stats['prev_played'] = all_stats.groupby(['season', 'team'])['matches_played'].shift(1).fillna(1) # avoid div by zero

all_stats['avg_gf'] = all_stats['prev_gf'] / all_stats['prev_played']
all_stats['avg_ga'] = all_stats['prev_ga'] / all_stats['prev_played']

# League averages (up to that matchday)
league_avgs = all_stats.groupby(['season', 'day']).agg({'gf': 'mean', 'ga': 'mean'}).reset_index()
league_avgs['cum_league_gf'] = league_avgs.groupby('season')['gf'].cumsum()
league_avgs['cum_league_ga'] = league_avgs.groupby('season')['ga'].cumsum()
league_avgs['league_matches'] = league_avgs.groupby('season').cumcount() + 1

league_avgs['prev_league_gf'] = league_avgs.groupby('season')['cum_league_gf'].shift(1).fillna(1)
league_avgs['prev_league_ga'] = league_avgs.groupby('season')['cum_league_ga'].shift(1).fillna(1)
league_avgs['prev_league_matches'] = league_avgs.groupby('season')['league_matches'].shift(1).fillna(1)

league_avgs['league_avg_gf'] = league_avgs['prev_league_gf'] / (league_avgs['prev_league_matches'] * 10) # 10 games per MD
league_avgs['league_avg_ga'] = league_avgs['prev_league_ga'] / (league_avgs['prev_league_matches'] * 10)

all_stats = all_stats.merge(league_avgs[['season', 'day', 'league_avg_gf', 'league_avg_ga']], on=['season', 'day'], how='left')

# Attack/Defense Strength
all_stats['attack_strength'] = all_stats['avg_gf'] / all_stats['league_avg_gf']
all_stats['defense_strength'] = all_stats['avg_ga'] / all_stats['league_avg_ga']

# Cap extreme values early in the season
all_stats['attack_strength'] = all_stats['attack_strength'].clip(0.1, 3.0)
all_stats['defense_strength'] = all_stats['defense_strength'].clip(0.1, 3.0)

# Merge into our Unified Matrix
home_merge = all_stats[all_stats['is_home'] == 1][['season', 'day', 'team', 'attack_strength', 'defense_strength']].rename(
    columns={'team': 'home', 'attack_strength': 'h_attack', 'defense_strength': 'h_defense'})

away_merge = all_stats[all_stats['is_home'] == 0][['season', 'day', 'team', 'attack_strength', 'defense_strength']].rename(
    columns={'team': 'away', 'attack_strength': 'a_attack', 'defense_strength': 'a_defense'})

# Drop existing columns if this is a rerun
df.drop(columns=['h_attack', 'h_defense', 'a_attack', 'a_defense', 'poisson_hxG', 'poisson_axG'], inplace=True, errors='ignore')

df = df.merge(home_merge, on=['season', 'day', 'home'], how='left')
df = df.merge(away_merge, on=['season', 'day', 'away'], how='left')

# Calculate Poisson Expected Goals (Lambda)
# Home xG = Home_Attack * Away_Defense * League_Avg_Home_Goals (approx 1.2)
# Away xG = Away_Attack * Home_Defense * League_Avg_Away_Goals (approx 0.9)
df['poisson_hxG'] = df['h_attack'] * df['a_defense'] * 1.2
df['poisson_axG'] = df['a_attack'] * df['h_defense'] * 0.9

# Save it back
df.to_parquet("/home/ubuntu/faith-workspace/vfl-empire/data/unified_ml_matrix.parquet")

print("Poisson Expected Goals (xG) injected into Unified Matrix.")
print(df[['season', 'day', 'home', 'away', 'poisson_hxG', 'poisson_axG', 'target_1x2']].head(10))
