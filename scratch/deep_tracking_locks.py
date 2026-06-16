import sqlite3
import pandas as pd
from collections import defaultdict

conn_hist = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
df_all = pd.read_sql_query("SELECT season, day, home, away, h, a, outcome FROM matches ORDER BY season, day", conn_hist)

print("Building deep contextual histories for all teams...")

match_records = []

for season, season_group in df_all.groupby('season'):
    team_stats = {} # pts, gd, gf
    team_history = defaultdict(list) # list of (opponent_rank, result)
    
    for day in range(1, 31):
        day_matches = season_group[season_group['day'] == day]
        if day_matches.empty: continue
            
        ranks = {}
        if len(team_stats) > 0:
            ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
            ranks = {team: i+1 for i, team in enumerate(ranked_teams)}
            
        for _, row in day_matches.iterrows():
            h_team, a_team = row['home'], row['away']
            outcome = row['outcome']
            
            if h_team in team_stats and a_team in team_stats:
                h_rank = ranks.get(h_team, -1)
                a_rank = ranks.get(a_team, -1)
                h_pts = team_stats[h_team]['pts']
                a_pts = team_stats[a_team]['pts']
                
                # Get last 3 form
                h_form = "".join([x[1] for x in team_history[h_team][-3:]])
                a_form = "".join([x[1] for x in team_history[a_team][-3:]])
                
                # Get last opponent rank (quality of last match)
                h_last_opp_rank = team_history[h_team][-1][0] if len(team_history[h_team]) > 0 else -1
                a_last_opp_rank = team_history[a_team][-1][0] if len(team_history[a_team]) > 0 else -1
                
                def is_prime(n):
                    if n < 2: return False
                    for i in range(2, int(n**0.5) + 1):
                        if n % i == 0: return False
                    return True
                
                md_type = "PRIME" if is_prime(day) else ("EVEN" if day % 2 == 0 else "ODD")
                
                # We record the features for both teams
                match_records.append({
                    'season': season,
                    'day': day,
                    'md_type': md_type,
                    'h_rank': h_rank, 'a_rank': a_rank,
                    'h_pts': h_pts, 'a_pts': a_pts,
                    'h_form': h_form, 'a_form': a_form,
                    'h_last_opp_rank': h_last_opp_rank,
                    'a_last_opp_rank': a_last_opp_rank,
                    'outcome': outcome
                })

        # Update stats & history for next day
        for _, row in day_matches.iterrows():
            h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
            if pd.isna(h) or pd.isna(a): continue
            
            if h_team not in team_stats: team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            if a_team not in team_stats: team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0}
            
            team_stats[h_team]['gf'] += h; team_stats[h_team]['gd'] += (h - a)
            team_stats[a_team]['gf'] += a; team_stats[a_team]['gd'] += (a - h)
            
            a_rank_current = ranks.get(a_team, -1)
            h_rank_current = ranks.get(h_team, -1)
            
            if h > a: 
                team_stats[h_team]['pts'] += 3
                team_history[h_team].append((a_rank_current, 'W'))
                team_history[a_team].append((h_rank_current, 'L'))
            elif h == a:
                team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
                team_history[h_team].append((a_rank_current, 'D'))
                team_history[a_team].append((h_rank_current, 'D'))
            else: 
                team_stats[a_team]['pts'] += 3
                team_history[h_team].append((a_rank_current, 'L'))
                team_history[a_team].append((h_rank_current, 'W'))

df_deep = pd.DataFrame(match_records)

print(f"\nConstructed deep tracking database with {len(df_deep)} fixtures.")
print("Features tracked: Matchday Parity/Prime, Rank, Points, Form (last 3), Last Opponent Rank.")

# Let's test the hypothesis: Do these ultra-deep signatures produce 100% prediction locks?
# We will combine: Home Form + Away Form + MD Type + Home Rank vs Away Rank
df_deep['mega_signature'] = df_deep.apply(
    lambda x: f"MD_{x['md_type']} | {x['h_form']} vs {x['a_form']} | R{x['h_rank']} vs R{x['a_rank']}", axis=1
)

sig_counts = df_deep['mega_signature'].value_counts()
df_deep['sig_count'] = df_deep['mega_signature'].map(sig_counts)

# Only look at signatures that have happened at least 5 times in history
df_valid = df_deep[df_deep['sig_count'] >= 5]

grouped = df_valid.groupby('mega_signature')['outcome'].agg(
    Total='count',
    Most_Common=lambda x: x.mode()[0] if not x.mode().empty else None,
    Count_Most_Common=lambda x: (x == x.mode()[0]).sum() if not x.mode().empty else 0
).reset_index()

grouped['Win_Rate'] = grouped['Count_Most_Common'] / grouped['Total']
perfect_locks = grouped[grouped['Win_Rate'] == 1.0].sort_values(by='Total', ascending=False)

print(f"\nOut of {len(grouped)} unique, recurring situations (>= 5 occurrences)...")
if perfect_locks.empty:
    print("There are ZERO situations that resulted in a 100% predictable outcome.")
    print("The highest predictability found for these deep signatures is:")
    print(grouped.sort_values(by='Win_Rate', ascending=False).head(10).to_string(index=False))
else:
    print(f"We found {len(perfect_locks)} situations that ALWAYS predict the exact same outcome:")
    print(perfect_locks.head(15).to_string(index=False))
    
