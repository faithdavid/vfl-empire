import sqlite3
import pandas as pd

conn_sov = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/sovereign.db')
conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')

# Get current matchday fixtures
df_pending = pd.read_sql_query("SELECT DISTINCT season_id, match_day, home_team, away_team FROM master_ledger WHERE status = 'PENDING' ORDER BY match_day DESC", conn_sov)
current_md = df_pending['match_day'].max()
current_season = df_pending[df_pending['match_day'] == current_md]['season_id'].iloc[0]

fixtures = df_pending[df_pending['match_day'] == current_md]

# Get the last 3 seasons (excluding the current one)
# We assume season strings can be sorted or we just get distinct seasons ordered by max(har_timestamp) or something
df_seasons = pd.read_sql_query("SELECT season, max(day) as max_day FROM matches GROUP BY season ORDER BY season DESC LIMIT 5", conn_hist)
# Let's drop current_season if it's there
recent_seasons = [s for s in df_seasons['season'] if s != current_season][:3]

print(f"Analyzing the last 3 seasons: {recent_seasons}")
print("For the 8 fixtures of the current Matchday 30:")

for idx, row in fixtures.iterrows():
    home = row['home_team']
    away = row['away_team']
    
    # Query these two teams in the last 3 seasons (Home vs Away)
    seasons_str = ",".join([f"'{s}'" for s in recent_seasons])
    query = f"SELECT season, day, outcome, h, a FROM matches WHERE home = '{home}' AND away = '{away}' AND season IN ({seasons_str}) ORDER BY season DESC"
    
    past_matches = pd.read_sql_query(query, conn_hist)
    
    print(f"\nFixture: {home} (Home) vs {away} (Away)")
    if past_matches.empty:
        print("  No matches found in the last 3 seasons.")
        continue
    
    outcomes = past_matches['outcome'].tolist()
    print(f"  Outcomes in last 3 seasons: {outcomes}")
    for _, r in past_matches.iterrows():
        print(f"    - Season: {r['season']} | Day: {r['day']} | Score: {r['h']}-{r['a']} ({r['outcome']})")
    
    # Analyze if they are all the same
    if len(outcomes) == 3 and len(set(outcomes)) == 1:
        print(f"  *** MATCHING TREND FOUND: 3/3 seasons resulted in {outcomes[0]} ***")
    elif len(outcomes) > 1 and len(set(outcomes)) == 1:
        print(f"  *** PARTIAL TREND FOUND: {len(outcomes)}/{len(outcomes)} seasons resulted in {outcomes[0]} ***")
    else:
        print("  No matching trend across all available recent seasons.")

