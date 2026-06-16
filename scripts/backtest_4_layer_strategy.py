import pandas as pd
import psycopg2
from collections import defaultdict

print("Starting 4-Layer Execution Strategy Backtest...")
conn = psycopg2.connect(dbname='vfl_empire', user='vfl_user', password='vfl_pass', host='localhost')

query = """
    SELECT season_id, matchday_number, home_team, away_team, home_goals, away_goals
    FROM vfl_fixture_aligned
    WHERE home_goals IS NOT NULL
    ORDER BY season_id, matchday_number
"""
df = pd.read_sql_query(query, conn)
conn.close()

# Tiers
elite_teams = ['Manchester Blue', 'London Guns', 'Chelsea', 'Liverpool']
weak_teams = ['West Ham', 'Manchester Red', 'Crystal Palace', 'Fulham', 'Everton', 'Wolverhampton', 'Bournemouth', 'Leeds']

total_triggers = 0
total_hits = 0

# To store results for analysis
results_log = []

# Group by season to simulate chronologically
seasons = df.groupby('season_id')

for season_id, season_df in seasons:
    # State trackers for this season
    points = defaultdict(int)
    matches_played = defaultdict(int)
    recent_form = defaultdict(list) # list of 'W', 'D', 'L'
    
    for _, row in season_df.iterrows():
        md = int(row['matchday_number'])
        home = row['home_team']
        away = row['away_team']
        hg = row['home_goals']
        ag = row['away_goals']
        
        # --- 4-LAYER CHECK BEFORE THE MATCH IS PLAYED ---
        if home in elite_teams and away in weak_teams and md > 5:
            ppg = points[home] / matches_played[home] if matches_played[home] > 0 else 0
            
            # Check Reality Layer: Did they win 0 times in their last 2 games?
            recent = recent_form[home][-2:]
            winless_streak = len(recent) == 2 and 'W' not in recent
            
            # Check Desperation Layer: Are they dropping below Elite quota?
            desperate = ppg < 1.8  # Elite teams need ~2.2, so <1.8 is desperate
            
            if winless_streak and desperate:
                total_triggers += 1
                outcome = 'W' if hg > ag else ('D' if hg == ag else 'L')
                if outcome == 'W':
                    total_hits += 1
                
                results_log.append({
                    'season': season_id, 'md': md, 'team': home, 'opp': away, 
                    'ppg': round(ppg, 2), 'recent': recent, 'outcome': outcome
                })
                
        # --- UPDATE STATE AFTER THE MATCH ---
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

print(f"\n--- BACKTEST RESULTS OVER {len(seasons)} SEASONS ---")
print(f"Total Matches Analyzed: {len(df)}")
print(f"Total Execution Triggers Found: {total_triggers}")
print(f"Total Successful Hits (Home Wins): {total_hits}")

if total_triggers > 0:
    win_rate = (total_hits / total_triggers) * 100
    print(f"\nFINAL HIT RATE: {win_rate:.2f}%")
else:
    print("\nNo triggers found with these strict conditions.")

# Print a few examples
print("\nSample Triggers:")
for log in results_log[:10]:
    print(f"Season {log['season']} MD {log['md']} | {log['team']} vs {log['opp']} | PPG: {log['ppg']} Form: {log['recent']} -> Outcome: {log['outcome']}")
