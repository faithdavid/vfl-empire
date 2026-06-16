import sqlite3
import pandas as pd
from collections import defaultdict

# 1. Load Data
conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

conn_sov = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/sovereign.db')
df_pending = pd.read_sql_query("SELECT DISTINCT season_id FROM master_ledger WHERE status = 'PENDING'", conn_sov)
pending_seasons = set(df_pending['season_id'].tolist())

seasons_ordered = df_all['season'].drop_duplicates().sort_values(ascending=False).tolist()
completed_seasons = [s for s in seasons_ordered if s not in pending_seasons]
last_season = completed_seasons[0]
train_seasons = completed_seasons[1:]

print("Building Trajectory Database...")

def get_rank_bracket(r):
    if r <= 4: return 'Top4'
    if r <= 8: return 'UpMid'
    if r <= 12: return 'LowMid'
    return 'Bot4'

# Precompute histories
match_records = []
for season, season_group in df_all.groupby('season'):
    team_stats = {}
    team_history = defaultdict(list)
    rank_history = defaultdict(list)
    
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        ranks = {}
        if len(team_stats) > 0:
            ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
            ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
            
        # Record trajectory state before matches
        for _, row in day_matches.iterrows():
            h_team, a_team = row['home'], row['away']
            outcome = row['outcome']
            
            if h_team in team_stats and a_team in team_stats and day > 5:
                # 1. Form last 5
                h_form = "".join(team_history[h_team][-5:])
                a_form = "".join(team_history[a_team][-5:])
                
                # 2. Rank Trend (Compare current rank to rank 3 matches ago)
                h_curr_rank = ranks.get(h_team, 16)
                a_curr_rank = ranks.get(a_team, 16)
                
                h_past_rank = rank_history[h_team][-3] if len(rank_history[h_team]) >= 3 else 16
                a_past_rank = rank_history[a_team][-3] if len(rank_history[a_team]) >= 3 else 16
                
                def get_trend(curr, past):
                    if curr < past: return "UP"
                    if curr > past: return "DOWN"
                    return "STABLE"
                
                h_trend = get_trend(h_curr_rank, h_past_rank)
                a_trend = get_trend(a_curr_rank, a_past_rank)
                
                # 3. Build Signatures
                h_sig = f"{get_rank_bracket(h_curr_rank)}_{h_trend}_{h_form}"
                a_sig = f"{get_rank_bracket(a_curr_rank)}_{a_trend}_{a_form}"
                
                match_records.append({
                    'season': season,
                    'day': day,
                    'h_team': h_team,
                    'a_team': a_team,
                    'h_sig': h_sig,
                    'a_sig': a_sig,
                    'outcome': outcome
                })

        # Update stats
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            team_stats[h_team]['gf'] += h; team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a; team_stats[a_team]['gd'] += (a - h)
            
            if h > a: 
                team_stats[h_team]['pts'] += 3
                team_history[h_team].append('W'); team_history[a_team].append('L')
            elif h == a:
                team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
                team_history[h_team].append('D'); team_history[a_team].append('D')
            else: 
                team_stats[a_team]['pts'] += 3
                team_history[h_team].append('L'); team_history[a_team].append('W')
                
            rank_history[h_team].append(ranks.get(h_team, 16))
            rank_history[a_team].append(ranks.get(a_team, 16))

df_traj = pd.DataFrame(match_records)
df_train = df_traj[df_traj['season'] != last_season]
df_test = df_traj[df_traj['season'] == last_season]

print("\n--- TRAJECTORY MATCHING EXPERIMENT ---")
print(f"Testing on Season: {last_season}, Matchday 15")

# Group training data by Trajectory Clash
clash_history = defaultdict(list)
for _, row in df_train.iterrows():
    # Only map historical matches that happened around mid-season (MD 10 to 20) to maintain context
    if 10 <= row['day'] <= 20:
        clash_history[(row['h_sig'], row['a_sig'])].append(row['outcome'])

# Test on Matchday 15 of the last season
test_md = 15
test_fixtures = df_test[df_test['day'] == test_md]

for _, row in test_fixtures.iterrows():
    h_team, a_team = row['h_team'], row['a_team']
    h_sig, a_sig = row['h_sig'], row['a_sig']
    actual_outcome = row['outcome']
    
    past_outcomes = clash_history.get((h_sig, a_sig), [])
    
    print(f"\nFixture: {h_team} vs {a_team}")
    print(f"Home Trajectory: {h_sig}")
    print(f"Away Trajectory: {a_sig}")
    
    if len(past_outcomes) == 0:
        print(" -> No historical twin found for this exact trajectory clash.")
    else:
        # Calculate distribution
        counts = {k: past_outcomes.count(k) for k in set(past_outcomes)}
        most_common = max(counts, key=counts.get)
        win_rate = counts[most_common] / len(past_outcomes)
        
        print(f" -> Found {len(past_outcomes)} historical twins for this clash.")
        print(f" -> Historical Outcome Distribution: {counts}")
        if win_rate == 1.0:
            status = "PERFECT PREDICTION" if actual_outcome == most_common else "FAILED PREDICTION"
            print(f" -> *** 100% LOCK FOUND! Predicted: {most_common} *** | Actual Result: {actual_outcome} [{status}]")
        elif win_rate >= 0.70:
            status = "CORRECT" if actual_outcome == most_common else "WRONG"
            print(f" -> Strong Trend ({win_rate*100:.1f}%) for {most_common} | Actual Result: {actual_outcome} [{status}]")
        else:
            print(" -> History was mixed (No clear lock).")

