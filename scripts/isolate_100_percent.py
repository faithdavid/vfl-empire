import pandas as pd
import psycopg2
from collections import defaultdict

print("Refining Backtest to Isolate the 100% Logic (Opponent Tension)...")
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

seasons = df.groupby('season_id')

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
        
        # --- THE REFINED LOGIC ---
        if home in elite_teams and away in weak_teams and md > 8: # Let PPG stabilize more
            home_ppg = points[home] / matches_played[home] if matches_played[home] > 0 else 0
            away_ppg = points[away] / matches_played[away] if matches_played[away] > 0 else 0
            
            recent = recent_form[home][-2:]
            winless_streak = len(recent) == 2 and 'W' not in recent
            
            # The Elite Team is Desperate
            home_desperate = home_ppg < 1.8 
            
            # THE NEW ISOLATION LOGIC:
            # What if the Elite team is EXTREMELY desperate? (PPG < 1.2)
            # What if the Opponent is just average? 
            home_extreme_desperation = home_ppg < 1.3
            
            if winless_streak and home_extreme_desperation:
                total_triggers += 1
                outcome = 'W' if hg > ag else ('D' if hg == ag else 'L')
                if outcome == 'W':
                    total_hits += 1
                
        # --- UPDATE STATE AFTER THE MATCH ---
        if hg > ag:
            points[home] += 3
        elif hg == ag:
            points[home] += 1; points[away] += 1
        else:
            points[away] += 3
            
        recent_form[home].append('W' if hg > ag else ('D' if hg == ag else 'L'))
        recent_form[away].append('L' if hg > ag else ('D' if hg == ag else 'W'))
        matches_played[home] += 1; matches_played[away] += 1

print(f"\n--- REFINED BACKTEST RESULTS (OPPONENT EXCESS QUOTA LOGIC) ---")
print(f"Total Execution Triggers Found: {total_triggers}")
print(f"Total Successful Hits (Home Wins): {total_hits}")

if total_triggers > 0:
    win_rate = (total_hits / total_triggers) * 100
    print(f"\nISOLATED HIT RATE: {win_rate:.2f}%")
else:
    print("\nNo triggers found with these strict conditions.")
