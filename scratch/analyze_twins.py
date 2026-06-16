import sqlite3
import pandas as pd

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, outcome FROM matches", conn_hist)

# We want only matchdays that have exactly 8 fixtures
matchday_counts = df_all.groupby(['season', 'day']).size()
valid_matchdays = matchday_counts[matchday_counts == 8].index
df_all = df_all.set_index(['season', 'day']).loc[valid_matchdays].reset_index()

# Find the 3 most recent seasons
seasons_ordered = df_all['season'].drop_duplicates().sort_values(ascending=False).tolist()
# Note: we might want to exclude the pending season if it's incomplete
conn_sov = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/sovereign.db')
df_pending = pd.read_sql_query("SELECT DISTINCT season_id FROM master_ledger WHERE status = 'PENDING'", conn_sov)
pending_seasons = set(df_pending['season_id'].tolist())

completed_seasons = [s for s in seasons_ordered if s not in pending_seasons]
last_3_seasons = completed_seasons[:3]

print(f"Using the last 3 completed seasons for testing: {last_3_seasons}")

# Create a signature for each matchday: sorted tuple of "Home_Away"
# Also store the outcomes in a dictionary mapping "Home_Away" to outcome
matchday_signatures = {}
matchday_outcomes = {}

for (season, day), group in df_all.groupby(['season', 'day']):
    fixtures = []
    outcomes = {}
    for _, row in group.iterrows():
        fixture_key = f"{row['home']}_vs_{row['away']}"
        fixtures.append(fixture_key)
        outcomes[fixture_key] = row['outcome']
    
    sig = tuple(sorted(fixtures))
    matchday_signatures[(season, day)] = sig
    matchday_outcomes[(season, day)] = outcomes

# Find twins
# Map signature -> list of (season, day)
sig_to_matchdays = {}
for md, sig in matchday_signatures.items():
    if sig not in sig_to_matchdays:
        sig_to_matchdays[sig] = []
    sig_to_matchdays[sig].append(md)

total_tests = 0
twins_found = 0
perfect_matches = 0
results_stats = []

for season in last_3_seasons:
    for day in range(1, 31):
        test_md = (season, day)
        if test_md not in matchday_signatures:
            continue # maybe incomplete data
            
        sig = matchday_signatures[test_md]
        outcomes_test = matchday_outcomes[test_md]
        
        # Find twins (other matchdays with the same signature)
        twins = [md for md in sig_to_matchdays[sig] if md != test_md]
        
        if len(twins) > 0:
            total_tests += 1
            # Check how outcomes match
            for twin in twins:
                twins_found += 1
                outcomes_twin = matchday_outcomes[twin]
                
                matches_count = 0
                for fixture_key in outcomes_test:
                    if outcomes_test[fixture_key] == outcomes_twin[fixture_key]:
                        matches_count += 1
                
                results_stats.append(matches_count)
                if matches_count == 8:
                    perfect_matches += 1
                    print(f"PERFECT MATCH (8/8) FOUND!")
                    print(f"Test MD: Season {season}, Day {day}  <==>  Twin MD: Season {twin[0]}, Day {twin[1]}")

print(f"\n--- Analysis Summary ---")
print(f"Total Matchdays Tested from last 3 seasons: {sum(1 for s in last_3_seasons for d in range(1, 31) if (s, d) in matchday_signatures)}")
print(f"Matchdays that had at least one twin: {total_tests}")
print(f"Total twin pairings analyzed: {twins_found}")
print(f"Perfect 8/8 outcome matches: {perfect_matches}")

if len(results_stats) > 0:
    from collections import Counter
    counts = Counter(results_stats)
    print("\nOutcome matches distribution (out of 8 fixtures):")
    for k in sorted(counts.keys(), reverse=True):
        print(f"{k}/8 fixtures matched: {counts[k]} times ({counts[k]/twins_found*100:.1f}%)")

