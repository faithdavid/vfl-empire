#!/usr/bin/env python3
import psycopg2
import pandas as pd

conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")

# Find a few matchdays where the total goals were 9 or less
query_find_mds = """
    SELECT season, day, SUM(h+a) as total_goals
    FROM matches
    WHERE h IS NOT NULL AND a IS NOT NULL
    GROUP BY season, day
    HAVING COUNT(*) = 8 AND SUM(h+a) <= 9
    ORDER BY season DESC, day DESC
    LIMIT 3;
"""

df_mds = pd.read_sql_query(query_find_mds, conn)

print("=== PROOF: The 'Ultra Under' Matchdays ===")
print("Here are actual historical Matchdays from your database where the ENTIRE round (all 8 games) produced 9 goals or less:\n")

for _, row in df_mds.iterrows():
    season = row['season']
    day = row['day']
    total_goals = row['total_goals']
    
    print(f">> Season {season} - Matchday {day} (Total Goals in Matchday: {total_goals})")
    
    query_scores = f"""
        SELECT home, away, h, a
        FROM matches
        WHERE season = '{season}' AND day = {day}
    """
    df_scores = pd.read_sql_query(query_scores, conn)
    
    for _, match in df_scores.iterrows():
        print(f"   {match['home']:<20} {match['h']} - {match['a']}  {match['away']}")
    print("-" * 40)

conn.close()
