#!/usr/bin/env python3
import psycopg2
import pandas as pd
import numpy as np

conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")

# Find a complete season with all 30 matchdays extracted
test_season = 'VFLM 5010'
print(f"=== BACKTEST SIMULATION: Season {test_season} ===\n")

# Load all matches for this season
query_matches = f"""
    SELECT day, home, away, h, a, 
           CASE WHEN h>a THEN 'HOME' WHEN h<a THEN 'AWAY' ELSE 'DRAW' END as result,
           CASE WHEN h+a>2 THEN 'OVER' ELSE 'UNDER' END as ou
    FROM matches 
    WHERE season = '{test_season}' AND h IS NOT NULL AND a IS NOT NULL
    ORDER BY day
"""
df = pd.read_sql_query(query_matches, conn)

target_avg_goals = 19.9
cumulative_goals = 0
bankroll = 1000 # Starting Bankroll
unit_size = 50

# Track simple ELO (Points)
points = {team: 0 for team in pd.concat([df['home'], df['away']]).unique()}

wins = 0
losses = 0

for md in range(1, 31):
    md_matches = df[df['day'] == md]
    
    # 1. Update Cumulative Tension from PREVIOUS Matchday
    if md > 1:
        prev_matches = df[df['day'] == md - 1]
        cumulative_goals += sum(prev_matches['h'] + prev_matches['a'])
        
        # Update Points
        for _, match in prev_matches.iterrows():
            if match['result'] == 'HOME': points[match['home']] += 3
            elif match['result'] == 'AWAY': points[match['away']] += 3
            else: 
                points[match['home']] += 1
                points[match['away']] += 1

    # 2. Skip betting on MD 1-5 to allow Tension & ELO to build
    if md < 6:
        continue
        
    expected_cumulative = (md - 1) * target_avg_goals
    tension = cumulative_goals - expected_cumulative
    
    # 3. Macro-State Prediction
    if tension > 4:
        engine_state = "UNDER_FORCE" # Engine wants to suppress goals
    elif tension < -4:
        engine_state = "OVER_FORCE"  # Engine wants to generate goals
    else:
        engine_state = "BALANCED"    # Engine is resting, skip betting
        continue
        
    # 4. Micro-State Alignment (Betting)
    print(f"--- MD {md} | Tension: {tension:+.1f} | State: {engine_state} ---")
    
    for _, match in md_matches.iterrows():
        h_pts = points[match['home']]
        a_pts = points[match['away']]
        pts_diff = h_pts - a_pts
        
        bet_placed = None
        bet_won = False
        
        # Rule 1: OVER FORCE + Strong Home Team -> Bet Home Win
        if engine_state == "OVER_FORCE" and pts_diff >= 4:
            bet_placed = "HOME WIN"
            bet_won = (match['result'] == 'HOME')
            
        # Rule 2: OVER FORCE + Strong Attacking Teams -> Bet Over 2.5
        elif engine_state == "OVER_FORCE" and h_pts > 10 and a_pts > 10:
            bet_placed = "OVER 2.5"
            bet_won = (match['ou'] == 'OVER')
            
        # Rule 3: UNDER FORCE + Weak Teams -> Bet Under 2.5
        elif engine_state == "UNDER_FORCE" and h_pts < 8 and a_pts < 8:
            bet_placed = "UNDER 2.5"
            bet_won = (match['ou'] == 'UNDER')
            
        # Rule 4: UNDER FORCE + Equal Teams -> Bet Draw
        elif engine_state == "UNDER_FORCE" and abs(pts_diff) <= 2:
            bet_placed = "DRAW"
            bet_won = (match['result'] == 'DRAW')
            
        if bet_placed:
            status = "✅ WON" if bet_won else "❌ LOST"
            if bet_won:
                wins += 1
                bankroll += (unit_size * 0.8) # Assuming avg decimal odds of ~1.80
            else:
                losses += 1
                bankroll -= unit_size
                
            print(f"  [{match['home']} vs {match['away']}]")
            print(f"  Engine Bias: {engine_state} | Micro Form: Home {h_pts}pts vs Away {a_pts}pts")
            print(f"  BET PLACED: {bet_placed} -> RESULT: {match['h']}-{match['a']} ({status})")

print("\n=== FINAL SIMULATION RESULTS ===")
total_bets = wins + losses
if total_bets > 0:
    win_rate = (wins / total_bets) * 100
    roi = ((bankroll - 1000) / 1000) * 100
    print(f"Total Bets Placed: {total_bets}")
    print(f"Wins: {wins} | Losses: {losses}")
    print(f"Win Rate: {win_rate:.1f}%")
    print(f"Starting Bankroll: $1000 | Final Bankroll: ${bankroll:.2f}")
    print(f"Total ROI: {roi:+.1f}%")
else:
    print("No bets met the strict >90% lock criteria this season.")

conn.close()
