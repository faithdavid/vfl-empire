import pandas as pd

# Load the Unified ML Matrix (which has clusters, tension, poisson, quotas)
df = pd.read_parquet('/home/ubuntu/faith-workspace/vfl-empire/data/unified_ml_matrix.parquet')

# We need the actual odds for financials. 
# They are in df as: 'o15', 'o25', 'gg', 'u35', but we need 1X2 odds.
# Let's merge the 1x2 odds from the raw database.
import psycopg2

print("Connecting to DB to fetch 1X2 odds...")
conn = psycopg2.connect(dbname='vfl_empire', user='vfl_user', password='vfl_pass', host='localhost')
query = """
    SELECT 
        REPLACE(season_id, 'vf:season:', '') AS season,
        matchday_number AS day,
        home_team AS home,
        MAX(CASE WHEN outcome_name = 'Home' THEN odds::FLOAT END) as odds_home,
        MAX(CASE WHEN outcome_name = 'Draw' THEN odds::FLOAT END) as odds_draw,
        MAX(CASE WHEN outcome_name = 'Away' THEN odds::FLOAT END) as odds_away
    FROM vfl_odds_v2
    WHERE market_name = '1x2'
    GROUP BY season_id, matchday_number, home_team
"""
odds_df = pd.read_sql_query(query, conn)
conn.close()

# Deduplicate odds (just in case)
odds_df = odds_df.drop_duplicates(subset=['season', 'day', 'home'], keep='last')

# Merge 1X2 odds into our ML Matrix
df['season'] = df['season'].astype(str)
df['day'] = df['day'].astype(int)
df['home'] = df['home'].astype(str)

odds_df['season'] = odds_df['season'].astype(str)
odds_df['day'] = odds_df['day'].astype(int)
odds_df['home'] = odds_df['home'].astype(str)

df = df.merge(odds_df, on=['season', 'day', 'home'], how='inner')

print(f"Matrix merged with 1X2 odds. Total valid matches: {len(df)}")

# Define Tiers and Phases
def get_tier(rank):
    if rank <= 4: return 'T1'
    elif rank <= 8: return 'T2'
    elif rank <= 12: return 'T3'
    else: return 'T4'

def get_phase(matchday):
    if matchday <= 5: return 'P1'
    elif matchday <= 10: return 'P2'
    elif matchday <= 15: return 'P3'
    elif matchday <= 20: return 'P4'
    elif matchday <= 25: return 'P5'
    else: return 'P6'

df['home_tier'] = df['h_rank'].apply(get_tier)
df['away_tier'] = df['a_rank'].apply(get_tier)
df['phase'] = df['day'].apply(get_phase)

# Map target_1x2 back to '1', 'X', '2'
outcome_map = {0: '1', 1: 'X', 2: '2'}
df['outcome'] = df['target_1x2'].map(outcome_map)

# Build the Truth Table grouped by Phase, Tier Matchup, AND Odds Cluster!
grouped = df.groupby(['phase', 'home_tier', 'away_tier', 'odds_cluster'])

truth_table = []
for name, group in grouped:
    phase, home_tier, away_tier, cluster = name
    total_matches = len(group)
    if total_matches < 10: # Only care about statistically significant sample sizes
        continue
        
    home_wins_df = group[group['outcome'] == '1']
    draws_df = group[group['outcome'] == 'X']
    away_wins_df = group[group['outcome'] == '2']
    
    w_count = len(home_wins_df)
    d_count = len(draws_df)
    l_count = len(away_wins_df)
    
    # Financials (Flat Staking 1 unit)
    home_return = home_wins_df['odds_home'].sum()
    draw_return = draws_df['odds_draw'].sum()
    away_return = away_wins_df['odds_away'].sum()
    
    home_profit = home_return - total_matches
    draw_profit = draw_return - total_matches
    away_profit = away_return - total_matches
    
    home_yield = (home_profit / total_matches) * 100
    draw_yield = (draw_profit / total_matches) * 100
    away_yield = (away_profit / total_matches) * 100
    
    truth_table.append({
        'Phase': phase,
        'Matchup': f"{home_tier} v {away_tier}",
        'DNA_Cluster': f"Cluster {int(cluster)}",
        'Matches': total_matches,
        'Home_Win%': round(w_count/total_matches * 100, 1),
        'Draw%': round(d_count/total_matches * 100, 1),
        'Away_Win%': round(l_count/total_matches * 100, 1),
        'Home_ROI%': round(home_yield, 2),
        'Draw_ROI%': round(draw_yield, 2),
        'Away_ROI%': round(away_yield, 2)
    })

truth_df = pd.DataFrame(truth_table)
truth_df.to_csv('/home/ubuntu/faith-workspace/vfl-empire/data/dna_financial_truth_table.csv', index=False)

print("\n--- TOP 10 HYPER-PROFITABLE BLIND SPOTS (HOME WINS) ---")
top_home = truth_df.sort_values('Home_ROI%', ascending=False).head(10)
print(top_home[['Phase', 'Matchup', 'DNA_Cluster', 'Matches', 'Home_Win%', 'Home_ROI%']].to_string(index=False))

print("\n--- TOP 10 HYPER-PROFITABLE BLIND SPOTS (DRAWS) ---")
top_draw = truth_df.sort_values('Draw_ROI%', ascending=False).head(10)
print(top_draw[['Phase', 'Matchup', 'DNA_Cluster', 'Matches', 'Draw%', 'Draw_ROI%']].to_string(index=False))

print("\n--- TOP 10 HYPER-PROFITABLE BLIND SPOTS (AWAY WINS) ---")
top_away = truth_df.sort_values('Away_ROI%', ascending=False).head(10)
print(top_away[['Phase', 'Matchup', 'DNA_Cluster', 'Matches', 'Away_Win%', 'Away_ROI%']].to_string(index=False))
