import sqlite3
import pandas as pd
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

# Re-calculate ranks for the entire history to enable rank-based locks
historical_data = [] # Will store dicts with match details including ranks

for season, season_group in df_all.groupby('season'):
    team_stats = {}
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        # Record signatures before matches are played
        ranks = {}
        if day >= 3 and len(team_stats) > 0:
            ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
            ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
            
        for idx, row in day_matches.iterrows():
            h_team, a_team = row['home'], row['away']
            h_rank = ranks.get(h_team, None)
            a_rank = ranks.get(a_team, None)
            historical_data.append({
                'season': season,
                'day': day,
                'home': h_team,
                'away': a_team,
                'home_rank': h_rank,
                'away_rank': a_rank,
                'outcome': row['outcome']
            })

        # Update stats
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            
            team_stats[h_team]['gf'] += h
            team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a
            team_stats[a_team]['gd'] += (a - h)
            
            if h > a: team_stats[h_team]['pts'] += 3
            elif h == a:
                team_stats[h_team]['pts'] += 1
                team_stats[a_team]['pts'] += 1
            else: team_stats[a_team]['pts'] += 3

df_hist = pd.DataFrame(historical_data)

# Find the last 3 completed seasons
conn_sov = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/sovereign.db')
df_pending = pd.read_sql_query("SELECT DISTINCT season_id FROM master_ledger WHERE status = 'PENDING'", conn_sov)
pending_seasons = set(df_pending['season_id'].tolist())

seasons_ordered = df_hist['season'].drop_duplicates().sort_values(ascending=False).tolist()
last_3_seasons = [s for s in seasons_ordered if s not in pending_seasons][:3]

# Now, let's analyze "Match Locks". We will define different types of locks.
# We will use the REST of the database (excluding last 3 seasons) to find locks,
# and see if they held true in the last 3 seasons.
df_train = df_hist[~df_hist['season'].isin(last_3_seasons)]
df_test = df_hist[df_hist['season'].isin(last_3_seasons)]

print(f"Training on {len(df_train)} historical matches to find 100% Match Locks...")
print(f"Testing locks on {len(df_test)} matches from the last 3 seasons...")

# Build lock dictionaries
# dict[lock_key] = [outcome1, outcome2, ...]
locks_home_rank = defaultdict(list)
locks_away_rank = defaultdict(list)
locks_fixture_day = defaultdict(list)
locks_team_vs_team = defaultdict(list)

for _, row in df_train.iterrows():
    h_team, a_team = row['home'], row['away']
    h_rank, a_rank = row['home_rank'], row['away_rank']
    day = row['day']
    outcome = row['outcome']
    
    if pd.notna(h_rank):
        locks_home_rank[(h_team, h_rank)].append(outcome)
    if pd.notna(a_rank):
        locks_away_rank[(a_team, a_rank)].append(outcome)
    locks_fixture_day[(h_team, a_team, day)].append(outcome)
    locks_team_vs_team[(h_team, a_team)].append(outcome)

# Filter for 100% locks with minimum sample size
MIN_SAMPLES = 4

def get_100_percent_locks(lock_dict):
    valid_locks = {}
    for k, v in lock_dict.items():
        if len(v) >= MIN_SAMPLES and len(set(v)) == 1:
            valid_locks[k] = v[0]
    return valid_locks

pure_locks_home_rank = get_100_percent_locks(locks_home_rank)
pure_locks_away_rank = get_100_percent_locks(locks_away_rank)
pure_locks_fixture_day = get_100_percent_locks(locks_fixture_day)
pure_locks_team_vs_team = get_100_percent_locks(locks_team_vs_team)

print(f"Found {len(pure_locks_home_rank)} locks for (Home Team, Home Rank) e.g., 'Chelsea at Rank 1 is always a HOME win'")
print(f"Found {len(pure_locks_away_rank)} locks for (Away Team, Away Rank)")
print(f"Found {len(pure_locks_fixture_day)} locks for (Home Team, Away Team, Matchday)")
print(f"Found {len(pure_locks_team_vs_team)} locks for (Home Team, Away Team)")

# Now test these locks on the last 3 seasons
results = {'home_rank': [0,0], 'away_rank': [0,0], 'fixture_day': [0,0], 'team_vs_team': [0,0]}

for _, row in df_test.iterrows():
    h_team, a_team = row['home'], row['away']
    h_rank, a_rank = row['home_rank'], row['away_rank']
    day = row['day']
    actual = row['outcome']
    
    # Test Home Rank lock
    if (h_team, h_rank) in pure_locks_home_rank:
        results['home_rank'][0] += 1
        if pure_locks_home_rank[(h_team, h_rank)] == actual:
            results['home_rank'][1] += 1
            
    # Test Away Rank lock
    if (a_team, a_rank) in pure_locks_away_rank:
        results['away_rank'][0] += 1
        if pure_locks_away_rank[(a_team, a_rank)] == actual:
            results['away_rank'][1] += 1
            
    # Test Fixture Day lock
    if (h_team, a_team, day) in pure_locks_fixture_day:
        results['fixture_day'][0] += 1
        if pure_locks_fixture_day[(h_team, a_team, day)] == actual:
            results['fixture_day'][1] += 1
            
    # Test Team vs Team lock
    if (h_team, a_team) in pure_locks_team_vs_team:
        results['team_vs_team'][0] += 1
        if pure_locks_team_vs_team[(h_team, a_team)] == actual:
            results['team_vs_team'][1] += 1

print("\n=== LOCK PERFORMANCE IN LAST 3 SEASONS ===")
for k, v in results.items():
    tested = v[0]
    correct = v[1]
    if tested > 0:
        print(f"Lock Type: {k.upper()} -> Tested {tested} times, Correct {correct} times ({correct/tested*100:.1f}%)")
    else:
        print(f"Lock Type: {k.upper()} -> Tested 0 times (No historical locks matched the test set)")

