import pandas as pd
import psycopg2
from collections import defaultdict

print("Applying Layer 4: MSport Odds DNA Matrix...")
conn = psycopg2.connect(dbname='vfl_empire', user='vfl_user', password='vfl_pass', host='localhost')

# 1. Fetch Fixtures
query_fixtures = """
    SELECT season_id, matchday_number, home_team, away_team, home_goals, away_goals
    FROM vfl_fixture_aligned
    WHERE home_goals IS NOT NULL
    ORDER BY season_id, matchday_number
"""
df_fixtures = pd.read_sql_query(query_fixtures, conn)

# 2. Fetch Odds
query_odds = """
    SELECT season_id, matchday_number, home_team, away_team, gg, ng, o25, u25
    FROM vfl_odds_v2
"""
df_odds = pd.read_sql_query(query_odds, conn)
conn.close()

# Drop duplicates if any in odds
df_odds = df_odds.drop_duplicates(subset=['season_id', 'matchday_number', 'home_team', 'away_team'])

# Tiers
elite_teams = ['Manchester Blue', 'London Guns', 'Chelsea', 'Liverpool']
weak_teams = ['West Ham', 'Manchester Red', 'Crystal Palace', 'Fulham', 'Everton', 'Wolverhampton', 'Bournemouth', 'Leeds']

triggers = []

seasons = df_fixtures.groupby('season_id')

for season_id, season_df in seasons:
    points = defaultdict(int)
    matches_played = defaultdict(int)
    recent_form = defaultdict(list)
    
    for _, row in season_df.iterrows():
        md = int(row['matchday_number'])
        home = row['home_team']
        away = row['away_team']
        hg = row['home_goals']
        ag = row['away_goals']
        
        if home in elite_teams and away in weak_teams and md > 5:
            ppg = points[home] / matches_played[home] if matches_played[home] > 0 else 0
            recent = recent_form[home][-2:]
            winless_streak = len(recent) == 2 and 'W' not in recent
            desperate = ppg < 1.8 
            
            if winless_streak and desperate:
                outcome = 'W' if hg > ag else ('D' if hg == ag else 'L')
                triggers.append({
                    'season_id': season_id, 'matchday_number': md, 
                    'home_team': home, 'away_team': away, 'outcome': outcome
                })
                
        # Update state
        if hg > ag:
            points[home] += 3
            recent_form[home].append('W')
            recent_form[away].append('L')
        elif hg == ag:
            points[home] += 1
            points[away] += 1
            recent_form[home].append('D')
            recent_form[away].append('D')
        else:
            points[away] += 3
            recent_form[home].append('L')
            recent_form[away].append('W')
            
        matches_played[home] += 1
        matches_played[away] += 1

df_triggers = pd.DataFrame(triggers)

# Merge Triggers with Odds
merged = pd.merge(df_triggers, df_odds, on=['season_id', 'matchday_number', 'home_team', 'away_team'], how='inner')

print(f"Total Triggers with active Odds Data: {len(merged)}")

# Isolate 100% Logic
# Let's round the odds slightly in case there's noise, or group by exact odds.
# Usually odds are like 1.85, 1.90.
merged['odds_cluster'] = merged.apply(lambda x: f"GG:{x['gg']}_O25:{x['o25']}", axis=1)

stats = merged.groupby('odds_cluster')['outcome'].apply(lambda x: pd.Series({
    'Total_Matches': len(x),
    'Home_Wins': (x == 'W').sum(),
    'Win_Rate': (x == 'W').sum() / len(x) * 100
})).unstack().reset_index()

# Filter for clusters that have at least 3 occurrences and 100% win rate
perfect_clusters = stats[(stats['Total_Matches'] >= 3) & (stats['Win_Rate'] == 100)].sort_values('Total_Matches', ascending=False)
strong_clusters = stats[(stats['Total_Matches'] >= 5) & (stats['Win_Rate'] >= 80)].sort_values('Win_Rate', ascending=False)

print("\n--- 100% MATHEMATICAL LOCKS (Layer 4 Odds Clusters) ---")
if not perfect_clusters.empty:
    print(perfect_clusters.to_string(index=False))
else:
    print("No perfect 100% clusters found with n>=3.")

print("\n--- 80%+ HIGH CONFIDENCE CLUSTERS (Layer 4 Odds Clusters) ---")
if not strong_clusters.empty:
    print(strong_clusters.to_string(index=False))
else:
    print("No strong clusters found.")
