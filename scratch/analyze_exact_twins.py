import sqlite3
import pandas as pd
from collections import defaultdict

conn_sov = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/sovereign.db')
conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')

print("1. Loading historical data and calculating ranks for every matchday...")
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

# Build a dictionary to hold the signature of every historical match: 
# dict[(home, away, home_rank, away_rank)] = list of outcomes
historical_signatures = defaultdict(list)
match_signatures = {} # To hold the calculated signature for each match row

for season, season_group in df_all.groupby('season'):
    team_stats = {}
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        # Record signatures before matches are played
        if day >= 3 and len(team_stats) > 0:
            ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
            ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
            
            for idx, row in day_matches.iterrows():
                h_team, a_team = row['home'], row['away']
                if h_team in ranks and a_team in ranks:
                    sig = (h_team, a_team, ranks[h_team], ranks[a_team])
                    historical_signatures[sig].append(row['outcome'])
                    match_signatures[idx] = sig

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

print("2. Checking the 8 pending fixtures for current Matchday 30 against exact historical signatures...")
df_pending = pd.read_sql_query("SELECT DISTINCT season_id, match_day, home_team, away_team FROM master_ledger WHERE status = 'PENDING' ORDER BY match_day DESC", conn_sov)
current_md = df_pending['match_day'].max()
current_season = df_pending[df_pending['match_day'] == current_md]['season_id'].iloc[0]
fixtures = df_pending[df_pending['match_day'] == current_md]

# Re-calculate ranks for current season to get the exact ranks for these 8 fixtures
df_season = pd.read_sql_query(f"SELECT home, away, h, a FROM matches WHERE season = '{current_season}' AND day < {current_md} AND h IS NOT NULL AND a IS NOT NULL", conn_hist)
team_stats_cur = {}
for _, row in df_season.iterrows():
    h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
    if h_team not in team_stats_cur: team_stats_cur[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
    if a_team not in team_stats_cur: team_stats_cur[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
    team_stats_cur[h_team]['gf'] += h
    team_stats_cur[h_team]['gd'] += (h - a)
    team_stats_cur[a_team]['gf'] += a
    team_stats_cur[a_team]['gd'] += (a - h)
    if h > a: team_stats_cur[h_team]['pts'] += 3
    elif h == a:
        team_stats_cur[h_team]['pts'] += 1
        team_stats_cur[a_team]['pts'] += 1
    else: team_stats_cur[a_team]['pts'] += 3

ranked_teams_cur = sorted(team_stats_cur.keys(), key=lambda t: (team_stats_cur[t]['pts'], team_stats_cur[t]['gd'], team_stats_cur[t]['gf']), reverse=True)
ranks_cur = {team: i+1 for i, team in enumerate(ranked_teams_cur)}

print("\n=== CURRENT MATCHDAY EXACT TWIN CHECK ===")
for _, row in fixtures.iterrows():
    h_team = row['home_team']
    a_team = row['away_team']
    h_rank = ranks_cur.get(h_team, -1)
    a_rank = ranks_cur.get(a_team, -1)
    
    sig = (h_team, a_team, h_rank, a_rank)
    past_outcomes = historical_signatures.get(sig, [])
    
    print(f"\n{h_team} (Rank {h_rank}) vs {a_team} (Rank {a_rank})")
    if len(past_outcomes) == 0:
        print("  -> No exact historical matches with both names and these exact ranks.")
    else:
        print(f"  -> Found {len(past_outcomes)} historical matches with this EXACT signature!")
        print(f"  -> Outcomes: {past_outcomes}")
        if len(set(past_outcomes)) == 1:
            print("  -> *** 100% CONSISTENT OUTCOME FOUND! ***")
            
print("\n3. Running the Controlled Test over the last 3 completed seasons...")
seasons_ordered = df_all['season'].drop_duplicates().sort_values(ascending=False).tolist()
# Filter out current
completed_seasons = [s for s in seasons_ordered if s != current_season][:3]

total_tested = 0
found_twins = 0
hundred_percent = 0
hundred_percent_samples = []

for season in completed_seasons:
    season_matches = df_all[df_all['season'] == season]
    for idx, row in season_matches.iterrows():
        if idx in match_signatures:
            sig = match_signatures[idx]
            # Outcomes from all time EXCEPT this specific match
            all_outcomes = list(historical_signatures[sig])
            # Removing the outcome of the match we are currently testing to see if history PREDICTS it
            if row['outcome'] in all_outcomes:
                all_outcomes.remove(row['outcome'])
            
            total_tested += 1
            if len(all_outcomes) > 0:
                found_twins += 1
                if len(set(all_outcomes)) == 1:
                    # History was 100% consistent
                    hundred_percent += 1
                    # Did history predict THIS match correctly?
                    if all_outcomes[0] == row['outcome']:
                        hundred_percent_samples.append((sig, all_outcomes[0], True, len(all_outcomes)))
                    else:
                        hundred_percent_samples.append((sig, all_outcomes[0], False, len(all_outcomes)))

print(f"\n=== CONTROLLED TEST RESULTS (Last 3 Seasons) ===")
print(f"Total fixtures tested (MD 3-30): {total_tested}")
print(f"Fixtures that had at least 1 exact historical twin (Name+Rank matching): {found_twins}")
print(f"Fixtures where the historical twins were 100% consistent: {hundred_percent}")

if hundred_percent > 0:
    correct = sum(1 for x in hundred_percent_samples if x[2])
    print(f"Out of those {hundred_percent} 100% consistent historical trends, it correctly predicted the test match {correct} times ({correct/hundred_percent*100:.1f}%)")

