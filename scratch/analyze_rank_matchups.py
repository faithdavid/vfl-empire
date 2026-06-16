import sqlite3
import pandas as pd
from collections import defaultdict, Counter

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

# We will collect rank matchups and their outcomes
rank_matchups = defaultdict(list)

# Process season by season
for season, season_group in df_all.groupby('season'):
    team_stats = {}
    
    # Process day by day
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty:
            continue
            
        # If day >= 3, we record the rank matchups based on CURRENT standings (before this day's matches)
        if day >= 3 and len(team_stats) > 0:
            # Calculate ranks
            ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
            ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
            
            for _, row in day_matches.iterrows():
                home = row['home']
                away = row['away']
                outcome = row['outcome']
                
                # Some teams might not have played yet if data is incomplete, default to something or skip
                if home in ranks and away in ranks:
                    h_rank = ranks[home]
                    a_rank = ranks[away]
                    rank_matchups[(h_rank, a_rank)].append(outcome)
                    
        # Now update team stats WITH this day's matches
        for _, row in day_matches.iterrows():
            home = row['home']
            away = row['away']
            h = row['h']
            a = row['a']
            
            # Skip if score is missing
            if pd.isna(h) or pd.isna(a):
                continue
                
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

print(f"Total distinct Rank vs Rank matchups analyzed: {len(rank_matchups)}")
print("Looking for highly consistent matchups (Sample Size >= 5)...")

results = []
for (hr, ar), outcomes in rank_matchups.items():
    if len(outcomes) >= 5:
        counts = Counter(outcomes)
        total = len(outcomes)
        most_common, mc_count = counts.most_common(1)[0]
        win_rate = mc_count / total
        
        results.append({
            'Home Rank': hr,
            'Away Rank': ar,
            'Total Matches': total,
            'Most Common Outcome': most_common,
            'Occurrences': mc_count,
            'Win Rate': win_rate
        })

# Sort by Win Rate (descending) and then Total Matches
df_results = pd.DataFrame(results).sort_values(by=['Win Rate', 'Total Matches'], ascending=[False, False])

print("\n=== TOP 15 MOST CONSISTENT RANK MATCHUPS (100% or close) ===")
print(df_results.head(15).to_string(index=False))

print("\n=== THE MYTH OF 100% ===")
perfect_matches = df_results[df_results['Win Rate'] == 1.0]
if not perfect_matches.empty:
    print(f"Found {len(perfect_matches)} rank combinations that result in the EXACT same outcome 100% of the time (with >= 5 samples)!")
    print(perfect_matches.to_string(index=False))
else:
    print("No rank combinations hit exactly 100% win rate across >= 5 samples, but some are very close.")

