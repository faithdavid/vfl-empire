#!/usr/bin/env python3
import psycopg2
import pandas as pd

conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")

# Pick a single highly volatile season to demonstrate the MD by MD tracking
query = """
    SELECT season, day, SUM(h+a) as goals
    FROM matches
    WHERE season = 'vf:season:3088744' AND h IS NOT NULL AND a IS NOT NULL
    GROUP BY season, day
    ORDER BY day
"""

df = pd.read_sql_query(query, conn)

print("=== THE SLIDING WINDOW: Tracking the Engine MD by MD ===")
print("Tracking Season vf:season:3088744. Target Average: 19.9 Goals per MD.\n")

cumulative_goals = 0
target_average = 19.9

print(f"{'MD':<4} | {'Goals Scored':<15} | {'Cumulative Target':<20} | {'Deficit/Surplus (Tension)':<25} | {'Engine Response Next MD'}")
print("-" * 100)

for index, row in df.iterrows():
    md = row['day']
    goals = row['goals']
    cumulative_goals += goals
    expected_goals = md * target_average
    
    tension = cumulative_goals - expected_goals
    
    # Predict engine response for the NEXT matchday based on the tension
    if tension > 5:
        response = "CRITICAL SURPLUS: Forcing Under 2.5"
    elif tension < -5:
        response = "CRITICAL DEFICIT: Forcing Over 2.5"
    else:
        response = "BALANCED: Engine at peace"
        
    print(f"{md:<4} | {goals:<15} | {expected_goals:<20.1f} | {tension:<25.1f} | {response}")

conn.close()
