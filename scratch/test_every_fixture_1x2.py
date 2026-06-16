import sqlite3
import pandas as pd
import numpy as np

# 1. Load Data
db_path = '/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db'
conn = sqlite3.connect(db_path)
query = """
SELECT season, day, home, away, h, a, oh, od, oa
FROM matches
WHERE season LIKE 'VFLM %'
"""
df = pd.read_sql_query(query, conn)
conn.close()

# 2. Preprocess Data
df['season_num'] = df['season'].str.replace('VFLM ', '').astype(int)
df = df.sort_values(['season_num', 'day'])

# Filter for the relevant block of seasons
df = df[df['season_num'] <= 5295]

def get_points(h_goals, a_goals):
    if h_goals > a_goals: return 3, 0
    elif h_goals == a_goals: return 1, 1
    return 0, 3

def get_outcome(h_goals, a_goals):
    if h_goals > a_goals: return 'HW'
    elif h_goals == a_goals: return 'DR'
    return 'AW'

df['outcome'] = df.apply(lambda row: get_outcome(row['h'], row['a']), axis=1)
df['season_phase'] = np.ceil(df['day'] / 2.0).astype(int)

# 3. Compute Tiers for all matches
def compute_standings_and_tiers(df_season):
    # This is a simplified rolling standing computation for the script
    # To save time, we will just iterate and build the tables
    records = []
    
    standings = {team: {'pts':0, 'gd':0, 'gf':0} for team in pd.concat([df_season['home'], df_season['away']]).unique()}
    
    for md in range(1, 31):
        # The tiers for matchday MD are based on standings AFTER MD-2
        if md <= 2:
            lag_tiers = {team: 'T1' for team in standings} # Default before MD3
        else:
            sorted_teams = sorted(standings.keys(), key=lambda t: (standings[t]['pts'], standings[t]['gd'], standings[t]['gf']), reverse=True)
            lag_tiers = {}
            for i, t in enumerate(sorted_teams):
                if i < 4: lag_tiers[t] = 'T1'
                elif i < 8: lag_tiers[t] = 'T2'
                elif i < 12: lag_tiers[t] = 'T3'
                else: lag_tiers[t] = 'T4'
                
        # Get matches for this MD
        md_matches = df_season[df_season['day'] == md]
        for _, row in md_matches.iterrows():
            rec = row.to_dict()
            rec['lag_home_tier'] = lag_tiers.get(row['home'], 'T4')
            rec['lag_away_tier'] = lag_tiers.get(row['away'], 'T4')
            records.append(rec)
            
        # Update standings AFTER this MD
        for _, row in md_matches.iterrows():
            hp, ap = get_points(row['h'], row['a'])
            h_gd = row['h'] - row['a']
            a_gd = row['a'] - row['h']
            
            standings[row['home']]['pts'] += hp
            standings[row['home']]['gd'] += h_gd
            standings[row['home']]['gf'] += row['h']
            
            standings[row['away']]['pts'] += ap
            standings[row['away']]['gd'] += a_gd
            standings[row['away']]['gf'] += row['a']
            
    return pd.DataFrame(records)

print("Calculating Lag Tiers across seasons...")
seasons_data = []
for s in df['season_num'].unique():
    seasons_data.append(compute_standings_and_tiers(df[df['season_num'] == s]))

df_processed = pd.concat(seasons_data, ignore_index=True)

# 4. Train/Test Split
df_train = df_processed[df_processed['season_num'] < 5295]
df_test = df_processed[df_processed['season_num'] == 5295]

# 5. Build Predictive Engine
# Group by Phase, HTier, ATier to find the most probable outcome
engine = df_train.groupby(['season_phase', 'lag_home_tier', 'lag_away_tier'])['outcome'].agg(lambda x: x.mode()[0] if not x.empty else 'HW').to_dict()

# 6. Test on VFLM 5295
total_bets = 0
wins = 0
losses = 0
units_staked = 0.0
units_returned = 0.0

for _, row in df_test.iterrows():
    key = (row['season_phase'], row['lag_home_tier'], row['lag_away_tier'])
    prediction = engine.get(key, 'HW') # Fallback to HW if unseen
    actual = row['outcome']
    
    total_bets += 1
    units_staked += 1.0
    
    if prediction == actual:
        wins += 1
        if prediction == 'HW': odds = row['oh']
        elif prediction == 'DR': odds = row['od']
        else: odds = row['oa']
        
        try:
            val = float(odds)
            if pd.isna(val):
                raise ValueError
        except:
            # Fallback to standard odds if missing in DB
            val = 1.70 if prediction == 'HW' else 2.10 if prediction == 'AW' else 3.00
            
        units_returned += val
    else:
        losses += 1

win_rate = (wins / total_bets) * 100
net_profit = units_returned - units_staked

print("\n=== 1X2 ENGINE TEST: VFLM 5295 ===")
print(f"Total Matches Predicted: {total_bets}")
print(f"Total Wins: {wins}")
print(f"Total Losses: {losses}")
print(f"Win Rate: {win_rate:.2f}%")
print(f"Units Staked: {units_staked:.2f}")
print(f"Units Returned: {units_returned:.2f}")
print(f"Net Profit: {net_profit:.2f} Units")
print("==================================")
