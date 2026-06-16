#!/usr/bin/env python3
import psycopg2
import pandas as pd
import numpy as np

conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost")

print("=== BIRDS EYE VIEW: Deep Odds Mappings ===")
query = """
    SELECT 
        home, away, h, a,
        oh as h_odd, od as d_odd, oa as a_odd,
        o_o25 as o25_odd, o_u25 as u25_odd,
        o_gg as gg_odd, o_ng as ng_odd,
        h + a as total_goals,
        CASE 
            WHEN h > a THEN 'H'
            WHEN h < a THEN 'A'
            ELSE 'D'
        END as result,
        gg, o25
    FROM matches
    WHERE h IS NOT NULL AND a IS NOT NULL
"""
df = pd.read_sql_query(query, conn)
print(f"Loaded {len(df)} historical matches with full odds and results.")

# 1. 1X2 Exact Odds Mapping
print("\n[1] Scanning for 1X2 Holy Grails (Exact Odds Triplets)...")
odds_group = df.groupby(['h_odd', 'd_odd', 'a_odd']).agg(
    total_matches=('result', 'count'),
    home_wins=('result', lambda x: (x == 'H').sum()),
    draws=('result', lambda x: (x == 'D').sum()),
    away_wins=('result', lambda x: (x == 'A').sum())
).reset_index()

sig_odds = odds_group[odds_group['total_matches'] >= 15].copy()
sig_odds['h_pct'] = (sig_odds['home_wins'] / sig_odds['total_matches']) * 100
sig_odds['d_pct'] = (sig_odds['draws'] / sig_odds['total_matches']) * 100
sig_odds['a_pct'] = (sig_odds['away_wins'] / sig_odds['total_matches']) * 100

holy_grails = sig_odds[
    (sig_odds['h_pct'] >= 85) | 
    (sig_odds['a_pct'] >= 85) |
    (sig_odds['d_pct'] >= 85)
].sort_values('total_matches', ascending=False)

if not holy_grails.empty:
    print(f"FOUND {len(holy_grails)} 1X2 ODDS COMBINATIONS WITH >=85% PREDICTABILITY!")
    print(holy_grails[['h_odd', 'd_odd', 'a_odd', 'total_matches', 'h_pct', 'd_pct', 'a_pct']].to_string(index=False))
else:
    print("No pure >=85% exact 1X2 locks found with >15 match sample size.")

# 2. O2.5 Exact Odds Mapping
print("\n[2] Scanning for O2.5 / U2.5 Trap Odds...")
ou_group = df.groupby(['o25_odd', 'u25_odd']).agg(
    matches=('result', 'count'),
    o25_hits=('o25', 'sum')
).reset_index()

ou_sig = ou_group[ou_group['matches'] >= 30].copy()
ou_sig['o25_pct'] = (ou_sig['o25_hits'] / ou_sig['matches']) * 100

print("Top 3 Trap Odds for OVER 2.5:")
print(ou_sig.sort_values('o25_pct', ascending=False).head(3).to_string(index=False))

print("\nTop 3 Trap Odds for UNDER 2.5:")
print(ou_sig.sort_values('o25_pct', ascending=True).head(3).to_string(index=False))

# 3. GG (Both Teams to Score) Mappings
print("\n[3] Scanning for GG/NG Trap Odds...")
gg_group = df.groupby(['gg_odd', 'ng_odd']).agg(
    matches=('result', 'count'),
    gg_hits=('gg', 'sum')
).reset_index()

gg_sig = gg_group[gg_group['matches'] >= 30].copy()
gg_sig['gg_pct'] = (gg_sig['gg_hits'] / gg_sig['matches']) * 100

print("Top 3 Trap Odds for GG (Both Teams Score):")
print(gg_sig.sort_values('gg_pct', ascending=False).head(3).to_string(index=False))

print("\nTop 3 Trap Odds for NG (One/No Team Scores):")
print(gg_sig.sort_values('gg_pct', ascending=True).head(3).to_string(index=False))

conn.close()
