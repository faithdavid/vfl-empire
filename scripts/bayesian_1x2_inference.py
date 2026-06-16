#!/usr/bin/env python3
import psycopg2
import pandas as pd

conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")

print("=== BAYESIAN INFERENCE: 1X2 Probabilities Given Engine Constraints ===")

query = """
    SELECT 
        CASE 
            WHEN h > a THEN 'HOME'
            WHEN h < a THEN 'AWAY'
            ELSE 'DRAW'
        END as result,
        CASE WHEN h + a > 2 THEN 'OVER' ELSE 'UNDER' END as goals_state,
        COUNT(*) as total
    FROM matches
    WHERE h IS NOT NULL AND a IS NOT NULL
    GROUP BY 
        CASE 
            WHEN h > a THEN 'HOME'
            WHEN h < a THEN 'AWAY'
            ELSE 'DRAW'
        END,
        CASE WHEN h + a > 2 THEN 'OVER' ELSE 'UNDER' END
"""

df = pd.read_sql_query(query, conn)

# Calculate Priors
total_matches = df['total'].sum()
over_matches = df[df['goals_state'] == 'OVER']['total'].sum()
under_matches = df[df['goals_state'] == 'UNDER']['total'].sum()

print(f"\n[1] The Priors (Baseline Probabilities):")
print(f"P(Over 2.5) = {over_matches / total_matches * 100:.1f}%")
print(f"P(Under 2.5) = {under_matches / total_matches * 100:.1f}%")

# Calculate Bayesian Conditionals for UNDER 2.5 (When the engine is suppressing goals)
print("\n[2] Bayesian Updating: If we know the Engine is forcing an UNDER (e.g. Archetype 0 suppression or Matchday Ceiling):")
u_home = df[(df['goals_state'] == 'UNDER') & (df['result'] == 'HOME')]['total'].sum()
u_away = df[(df['goals_state'] == 'UNDER') & (df['result'] == 'AWAY')]['total'].sum()
u_draw = df[(df['goals_state'] == 'UNDER') & (df['result'] == 'DRAW')]['total'].sum()

print(f"P(Home Win | Under 2.5) = {u_home / under_matches * 100:.1f}%")
print(f"P(Draw     | Under 2.5) = {u_draw / under_matches * 100:.1f}%")
print(f"P(Away Win | Under 2.5) = {u_away / under_matches * 100:.1f}%")

# Calculate Bayesian Conditionals for OVER 2.5 (When the engine is buffing goals)
print("\n[3] Bayesian Updating: If we know the Engine is forcing an OVER (e.g. Archetype 1 buffing):")
o_home = df[(df['goals_state'] == 'OVER') & (df['result'] == 'HOME')]['total'].sum()
o_away = df[(df['goals_state'] == 'OVER') & (df['result'] == 'AWAY')]['total'].sum()
o_draw = df[(df['goals_state'] == 'OVER') & (df['result'] == 'DRAW')]['total'].sum()

print(f"P(Home Win | Over 2.5) = {o_home / over_matches * 100:.1f}%")
print(f"P(Draw     | Over 2.5) = {o_draw / over_matches * 100:.1f}%  <-- (Math fact: Only 2-2, 3-3, 4-4 are possible)")
print(f"P(Away Win | Over 2.5) = {o_away / over_matches * 100:.1f}%")

conn.close()
