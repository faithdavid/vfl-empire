import sqlite3
import pandas as pd
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome, oh, od, oa FROM matches ORDER BY season, day", conn_hist)

# Identify the last completed season
conn_sov = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/sovereign.db')
df_pending = pd.read_sql_query("SELECT DISTINCT season_id FROM master_ledger WHERE status = 'PENDING'", conn_sov)
pending_seasons = set(df_pending['season_id'].tolist())

seasons_ordered = df_all['season'].drop_duplicates().sort_values(ascending=False).tolist()
completed_seasons = [s for s in seasons_ordered if s not in pending_seasons]
last_season = completed_seasons[0]
train_seasons = completed_seasons[1:] # Exclude the very last season to prevent data leakage

print(f"Training locks on all history EXCEPT {last_season}...")
print(f"Testing picks strictly on {last_season}...")

# 1. Train State Locks
state_outcomes = defaultdict(list)
for season in train_seasons:
    season_group = df_all[df_all['season'] == season]
    team_stats = {}
    
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        ranks = {}
        if len(team_stats) > 0:
            ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
            ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
            
        # Record state before the match
        for _, row in day_matches.iterrows():
            h_team, a_team = row['home'], row['away']
            outcome = row['outcome']
            h_res = 'WIN' if outcome == 'HOME' else ('DRAW' if outcome == 'DRAW' else 'LOSE')
            a_res = 'WIN' if outcome == 'AWAY' else ('DRAW' if outcome == 'DRAW' else 'LOSE')
            
            if h_team in team_stats:
                h_pts = team_stats[h_team]['pts']
                h_rank = ranks.get(h_team, -1)
                state_outcomes[(h_team, 'HOME', h_rank, h_pts)].append(h_res)
                
            if a_team in team_stats:
                a_pts = team_stats[a_team]['pts']
                a_rank = ranks.get(a_team, -1)
                state_outcomes[(a_team, 'AWAY', a_rank, a_pts)].append(a_res)

        # Update stats
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            team_stats[h_team]['gf'] += h; team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a; team_stats[a_team]['gd'] += (a - h)
            if h > a: team_stats[h_team]['pts'] += 3
            elif h == a:
                team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
            else: team_stats[a_team]['pts'] += 3

# Filter 100% locks
MIN_SAMPLES = 4
locks = {}
for state, outcomes in state_outcomes.items():
    if len(outcomes) >= MIN_SAMPLES and len(set(outcomes)) == 1:
        locks[state] = outcomes[0]
        
print(f"Found {len(locks)} 100% pure locks from historical training data.")

# 2. Test on Last Season
last_season_matches = df_all[df_all['season'] == last_season]
team_stats = {}
picks = []
total_profit = 0

for day in range(1, 31):
    day_matches = last_season_matches[last_season_matches['day'] == day]
    if day_matches.empty: continue
        
    ranks = {}
    if len(team_stats) > 0:
        ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
        ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
        
    for _, row in day_matches.iterrows():
        h_team, a_team = row['home'], row['away']
        h_pts = team_stats.get(h_team, {}).get('pts', -1)
        a_pts = team_stats.get(a_team, {}).get('pts', -1)
        h_rank = ranks.get(h_team, -1)
        a_rank = ranks.get(a_team, -1)
        
        # Check Home Team Lock
        h_state = (h_team, 'HOME', h_rank, h_pts)
        if h_state in locks:
            guaranteed = locks[h_state]
            if guaranteed == 'WIN': bet, odds = 'HOME', row['oh']
            elif guaranteed == 'LOSE': bet, odds = 'AWAY', row['oa']
            else: bet, odds = 'DRAW', row['od']
            
            won = (row['outcome'] == bet)
            picks.append({'Match': f"{h_team} vs {a_team}", 'Day': day, 'Reason': f"{h_team} (Home, R{h_rank}, {h_pts}pts) locked to {guaranteed}", 'Bet': bet, 'Odds': odds, 'Won': won})

        # Check Away Team Lock
        a_state = (a_team, 'AWAY', a_rank, a_pts)
        if a_state in locks:
            guaranteed = locks[a_state]
            if guaranteed == 'WIN': bet, odds = 'AWAY', row['oa']
            elif guaranteed == 'LOSE': bet, odds = 'HOME', row['oh']
            else: bet, odds = 'DRAW', row['od']
            
            won = (row['outcome'] == bet)
            picks.append({'Match': f"{h_team} vs {a_team}", 'Day': day, 'Reason': f"{a_team} (Away, R{a_rank}, {a_pts}pts) locked to {guaranteed}", 'Bet': bet, 'Odds': odds, 'Won': won})

    # Update stats
    for _, row in day_matches.iterrows():
        h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
        if pd.isna(h) or pd.isna(a): continue
        if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
        if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
        team_stats[h_team]['gf'] += h; team_stats[h_team]['gd'] += (h - a)
        team_stats[a_team]['gf'] += a; team_stats[a_team]['gd'] += (a - h)
        if h > a: team_stats[h_team]['pts'] += 3
        elif h == a:
            team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
        else: team_stats[a_team]['pts'] += 3

df_picks = pd.DataFrame(picks)
if df_picks.empty:
    print("\nNo picks were triggered in the last season.")
else:
    wins = df_picks['Won'].sum()
    total = len(df_picks)
    print(f"\n=== BACKTEST RESULTS FOR SEASON {last_season} ===")
    print(f"Total Picks Made: {total}")
    print(f"Winning Picks: {wins} ({wins/total*100:.1f}%)")
    
    # Calculate profit assuming 1 unit stake
    profit = sum(row['Odds'] - 1 if row['Won'] else -1 for _, row in df_picks.iterrows())
    print(f"Net Profit (1 unit flat stake): {profit:.2f} units")
    print(f"Average Odds: {df_picks['Odds'].mean():.2f}")
    
    print("\nAll Picks:")
    print(df_picks.to_string(index=False))

