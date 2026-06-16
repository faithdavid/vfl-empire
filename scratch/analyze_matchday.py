import sqlite3
import pandas as pd

# Connect to databases
conn_sov = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/sovereign.db')
conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')

# Get current match day pending fixtures from sovereign
df_pending = pd.read_sql_query("SELECT DISTINCT season_id, match_day, home_team, away_team FROM master_ledger WHERE status = 'PENDING' ORDER BY match_day DESC", conn_sov)
if df_pending.empty:
    print("No pending matches found.")
    exit(0)

current_md = df_pending['match_day'].max()
current_season = df_pending[df_pending['match_day'] == current_md]['season_id'].iloc[0]

print(f"Current Matchday: {current_md} (Season: {current_season})")
fixtures = df_pending[df_pending['match_day'] == current_md]

# Try to calculate team ranks based on history.db for the current season up to current_md - 1
df_season = pd.read_sql_query(f"SELECT home, away, h, a FROM matches WHERE season = '{current_season}' AND day < {current_md} AND h IS NOT NULL AND a IS NOT NULL", conn_hist)

team_stats = {}
for _, row in df_season.iterrows():
    home = row['home']
    away = row['away']
    h = row['h']
    a = row['a']
    
    if home not in team_stats: team_stats[home] = {'pts': 0, 'gd': 0, 'gf': 0}
    if away not in team_stats: team_stats[away] = {'pts': 0, 'gd': 0, 'gf': 0}
    
    team_stats[home]['gf'] += h
    team_stats[home]['gd'] += (h - a)
    team_stats[away]['gf'] += a
    team_stats[away]['gd'] += (a - h)
    
    if h > a:
        team_stats[home]['pts'] += 3
    elif h == a:
        team_stats[home]['pts'] += 1
        team_stats[away]['pts'] += 1
    else:
        team_stats[away]['pts'] += 3

# Rank teams
ranked_teams = sorted(team_stats.keys(), key=lambda x: (team_stats[x]['pts'], team_stats[x]['gd'], team_stats[x]['gf']), reverse=True)
ranks = {team: i+1 for i, team in enumerate(ranked_teams)}

print("\n--- Today's Fixtures ---")
for idx, row in fixtures.iterrows():
    home = row['home_team']
    away = row['away_team']
    home_rank = ranks.get(home, 'N/A')
    away_rank = ranks.get(away, 'N/A')
    print(f"{home} (Rank {home_rank}) vs {away} (Rank {away_rank})")

# Look 2 or 4 matchdays back... wait, the user asked:
# "could help looking 2 or 4 matchdays back, and see if this particular matchday has occured before then report to me the numbers"
# Let's find seasons that had EXACTLY these matchups on ANY matchday.
home_teams = set(fixtures['home_team'])
away_teams = set(fixtures['away_team'])

# Query all matches to find matchdays in past seasons that match these fixtures
print("\n--- Checking for exact matchday occurrences in history ---")
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches", conn_hist)

# Group by season and day
grouped = df_all.groupby(['season', 'day'])

match_found = False
for (s, d), group in grouped:
    if s == current_season: continue
    
    group_homes = set(group['home'])
    group_aways = set(group['away'])
    
    if home_teams.issubset(group_homes) and away_teams.issubset(group_aways):
        # We need to verify the EXACT pairings
        pairings_match = True
        for idx, row in fixtures.iterrows():
            if not ((group['home'] == row['home_team']) & (group['away'] == row['away_team'])).any():
                pairings_match = False
                break
        
        if pairings_match:
            match_found = True
            print(f"\nExact Matchday found! Season: {s}, Day: {d}")
            print(group[['home', 'away', 'h', 'a', 'outcome']].to_string(index=False))

if not match_found:
    print("\nNo exact matchday occurrences found in history.")

