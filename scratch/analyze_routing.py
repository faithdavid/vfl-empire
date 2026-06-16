import sqlite3
import pandas as pd
import numpy as np
from tqdm import tqdm

DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db"
conn = sqlite3.connect(DB_PATH)

# Get all completed seasons
query = "SELECT DISTINCT season FROM matches WHERE season IS NOT NULL"
seasons_df = pd.read_sql_query(query, conn)
seasons = seasons_df['season'].tolist()

print(f"Analyzing {len(seasons)} seasons for point-level routing...")

# We will build a massive dataset of every match, the points of home/away going into it, and the result.
# To optimize, we'll write a complex SQL query or use pandas. Let's use pandas for easier manipulation.

matches = pd.read_sql_query("SELECT season, day, home, away, h, a FROM matches WHERE season IS NOT NULL", conn)
matches = matches.sort_values(by=['season', 'day'])

# Initialize points tracking
# We need to compute the points of every team before every matchday
# This can be slow if done iteratively. Let's vectorize it.

# Create a long format for all team results
home_res = matches[['season', 'day', 'home', 'h', 'a']].copy()
home_res.rename(columns={'home': 'team', 'h': 'gf', 'a': 'ga'}, inplace=True)
home_res['pts'] = np.where(home_res['gf'] > home_res['ga'], 3, np.where(home_res['gf'] == home_res['ga'], 1, 0))

away_res = matches[['season', 'day', 'away', 'a', 'h']].copy()
away_res.rename(columns={'away': 'team', 'a': 'gf', 'h': 'ga'}, inplace=True)
away_res['pts'] = np.where(away_res['gf'] > away_res['ga'], 3, np.where(away_res['gf'] == away_res['ga'], 1, 0))

all_res = pd.concat([home_res, away_res]).sort_values(by=['season', 'team', 'day'])

# Calculate cumulative points BEFORE the match
all_res['cum_pts'] = all_res.groupby(['season', 'team'])['pts'].cumsum() - all_res['pts']

# Calculate cumulative goal difference BEFORE the match
all_res['gd'] = all_res['gf'] - all_res['ga']
all_res['cum_gd'] = all_res.groupby(['season', 'team'])['gd'].cumsum() - all_res['gd']

# We need to get the rank of each team before the matchday
# To do this efficiently, we pivot cum_pts and cum_gd
pivot_pts = all_res.pivot(index=['season', 'day'], columns='team', values='cum_pts')
pivot_gd = all_res.pivot(index=['season', 'day'], columns='team', values='cum_gd')

# Rank teams per season/day. Higher points -> lower rank. Tie breaker: higher GD -> lower rank
# Using pandas rank:
# We can create a combined score: pts + (gd / 1000)
combined_score = pivot_pts + (pivot_gd / 1000.0)

# Rank descending (highest score gets rank 1)
ranks = combined_score.rank(axis=1, method='min', ascending=False)

# Melt the ranks back
ranks_melt = ranks.reset_index().melt(id_vars=['season', 'day'], var_name='team', value_name='rank_before')
all_res = pd.merge(all_res, ranks_melt, on=['season', 'day', 'team'])

# Now merge this data back to the original matches
matches = pd.merge(matches, all_res[['season', 'day', 'team', 'cum_pts', 'rank_before']].rename(columns={'team': 'home', 'cum_pts': 'h_pts', 'rank_before': 'h_rank'}), on=['season', 'day', 'home'])
matches = pd.merge(matches, all_res[['season', 'day', 'team', 'cum_pts', 'rank_before']].rename(columns={'team': 'away', 'cum_pts': 'a_pts', 'rank_before': 'a_rank'}), on=['season', 'day', 'away'])

# Now we have every match, with home/away points and ranks BEFORE the match.
# Let's group by Matchday, Home Rank, and Away Rank to see outcomes
print("Dataset compiled. Aggregating routing patterns...")

matches['outcome'] = np.where(matches['h'] > matches['a'], 'H', np.where(matches['h'] == matches['a'], 'D', 'A'))
matches['btts'] = np.where((matches['h'] > 0) & (matches['a'] > 0), 1, 0)
matches['o25'] = np.where((matches['h'] + matches['a']) > 2, 1, 0)

# We want to find "Routing": given day, h_rank, a_rank, what is the probability of H, D, A?
# To avoid tiny sample sizes, we might group ranks into Tiers (1-6, 7-12, 13-16) or look at specific days
def get_tier(r):
    if r <= 6: return "Top6"
    if r <= 12: return "Mid6"
    return "Bot4"

matches['h_tier'] = matches['h_rank'].apply(get_tier)
matches['a_tier'] = matches['a_rank'].apply(get_tier)

# Let's find patterns where a specific outcome has a massive hit rate (e.g., >80% with a decent sample size)
grouped = matches.groupby(['day', 'h_tier', 'a_tier'])
stats = grouped.agg(
    total=('outcome', 'count'),
    H_win=('outcome', lambda x: (x == 'H').sum()),
    D=('outcome', lambda x: (x == 'D').sum()),
    A_win=('outcome', lambda x: (x == 'A').sum()),
    BTTS=('btts', 'sum'),
    O25=('o25', 'sum')
).reset_index()

stats['H_pct'] = stats['H_win'] / stats['total']
stats['D_pct'] = stats['D'] / stats['total']
stats['A_pct'] = stats['A_win'] / stats['total']
stats['1X_pct'] = (stats['H_win'] + stats['D']) / stats['total']
stats['X2_pct'] = (stats['A_win'] + stats['D']) / stats['total']

# Filter for statistically significant routing patterns
print("\n=== TOP EARLY SEASON (MD 1-15) ROUTING PATTERNS (Min 50 Matches, >80% Hit Rate) ===")
early = stats[(stats['day'] <= 15) & (stats['total'] >= 50)]
high_prob_early = early[(early['H_pct'] > 0.8) | (early['A_pct'] > 0.8) | (early['1X_pct'] > 0.8) | (early['X2_pct'] > 0.8)].sort_values('total', ascending=False)
for _, row in high_prob_early.head(10).iterrows():
    print(f"MD {row['day']:02d} | {row['h_tier']} vs {row['a_tier']} | Vol: {row['total']}")
    if row['1X_pct'] > 0.8: print(f"  -> 1X (Home or Draw): {row['1X_pct']*100:.1f}%")
    if row['X2_pct'] > 0.8: print(f"  -> X2 (Away or Draw): {row['X2_pct']*100:.1f}%")

print("\n=== TOP LATE SEASON (MD 16-30) ROUTING PATTERNS (Min 50 Matches, >80% Hit Rate) ===")
late = stats[(stats['day'] > 15) & (stats['total'] >= 50)]
high_prob_late = late[(late['H_pct'] > 0.8) | (late['A_pct'] > 0.8) | (late['1X_pct'] > 0.8) | (late['X2_pct'] > 0.8)].sort_values('total', ascending=False)
for _, row in high_prob_late.head(10).iterrows():
    print(f"MD {row['day']:02d} | {row['h_tier']} vs {row['a_tier']} | Vol: {row['total']}")
    if row['1X_pct'] > 0.8: print(f"  -> 1X (Home or Draw): {row['1X_pct']*100:.1f}%")
    if row['X2_pct'] > 0.8: print(f"  -> X2 (Away or Draw): {row['X2_pct']*100:.1f}%")

