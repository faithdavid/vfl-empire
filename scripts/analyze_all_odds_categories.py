import pandas as pd
import numpy as np
import psycopg2

print("Running Global Odds Category Analysis...")
conn = psycopg2.connect(dbname='vfl_empire', user='vfl_user', password='vfl_pass', host='localhost')

# Fetch everything
q = """
    SELECT f.home_team, f.away_team, f.home_goals, f.away_goals, 
           o.gg, o.ng, o.o15, o.o25, o.u25, o.u35
    FROM vfl_fixture_aligned f
    JOIN vfl_odds_v2 o ON f.season_id = o.season_id 
        AND f.matchday_number = o.matchday_number 
        AND f.home_team = o.home_team 
        AND f.away_team = o.away_team
    WHERE f.home_goals IS NOT NULL AND o.gg IS NOT NULL
"""
df = pd.read_sql_query(q, conn)
conn.close()

# Ensure structured data
df = df.drop_duplicates()
print(f"Total well-structured matches with complete odds data: {len(df)}")

# Define Outcomes
df['Home_Win'] = (df['home_goals'] > df['away_goals']).astype(int)
df['Draw'] = (df['home_goals'] == df['away_goals']).astype(int)
df['Away_Win'] = (df['home_goals'] < df['away_goals']).astype(int)
df['O25_Hit'] = ((df['home_goals'] + df['away_goals']) > 2).astype(int)
df['GG_Hit'] = ((df['home_goals'] > 0) & (df['away_goals'] > 0)).astype(int)

# Bin the GG Odds (like 1.30-1.34, 1.35-1.39)
# We will use 0.05 step bins
bins = np.arange(1.30, 2.50, 0.05)
labels = [f"{b:.2f}-{b+0.04:.2f}" for b in bins[:-1]]
df['gg_category'] = pd.cut(df['gg'], bins=bins, labels=labels, right=False)

# Group by GG Category
gg_stats = df.groupby('gg_category', observed=False).agg(
    Matches=('home_team', 'count'),
    Home_Win_Pct=('Home_Win', lambda x: x.mean() * 100),
    Draw_Pct=('Draw', lambda x: x.mean() * 100),
    Away_Win_Pct=('Away_Win', lambda x: x.mean() * 100),
    GG_Hit_Pct=('GG_Hit', lambda x: x.mean() * 100),
    O25_Hit_Pct=('O25_Hit', lambda x: x.mean() * 100)
).dropna().reset_index()

# Filter out very small sample sizes
gg_stats = gg_stats[gg_stats['Matches'] > 50]

print("\n--- GLOBAL ODDS CATEGORY ANALYSIS (Based purely on GG Odds) ---")
print(gg_stats.to_string(index=False, float_format="%.1f"))

# Bin the O25 Odds
o25_bins = np.arange(1.20, 2.50, 0.05)
o25_labels = [f"{b:.2f}-{b+0.04:.2f}" for b in o25_bins[:-1]]
df['o25_category'] = pd.cut(df['o25'], bins=o25_bins, labels=o25_labels, right=False)

o25_stats = df.groupby('o25_category', observed=False).agg(
    Matches=('home_team', 'count'),
    Home_Win_Pct=('Home_Win', lambda x: x.mean() * 100),
    Draw_Pct=('Draw', lambda x: x.mean() * 100),
    Away_Win_Pct=('Away_Win', lambda x: x.mean() * 100),
    GG_Hit_Pct=('GG_Hit', lambda x: x.mean() * 100),
    O25_Hit_Pct=('O25_Hit', lambda x: x.mean() * 100)
).dropna().reset_index()

o25_stats = o25_stats[o25_stats['Matches'] > 50]

print("\n--- GLOBAL ODDS CATEGORY ANALYSIS (Based purely on Over 2.5 Odds) ---")
print(o25_stats.to_string(index=False, float_format="%.1f"))
