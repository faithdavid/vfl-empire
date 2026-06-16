import sqlite3
import json
import collections
import copy

try:
    with open('/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json', 'r') as f:
        macro_data = json.load(f)
    with open('/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json', 'r') as f:
        micro_data = json.load(f)
except Exception as e:
    exit(1)

macro_patterns = {(r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in macro_data}
micro_patterns = {(r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in micro_data}

conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def get_tier(rank):
    if rank <= 4: return "T1"
    elif rank <= 8: return "T2"
    elif rank <= 12: return "T3"
    else: return "T4"

def get_micro_tier(rank):
    if rank <= 2: return "A"
    elif rank <= 4: return "B"
    elif rank <= 6: return "C"
    elif rank <= 8: return "D"
    elif rank <= 10: return "E"
    elif rank <= 12: return "F"
    elif rank <= 14: return "G"
    else: return "H"

cur.execute("SELECT season, MAX(day) as max_day FROM matches GROUP BY season HAVING max_day >= 30 ORDER BY season DESC LIMIT 10")
recent_seasons = [row['season'] for row in cur.fetchall()][::-1] 

stats = {
    "Home Win (>85%)": {"bets": 0, "hits": 0},
    "Under 2.5 (>90%)": {"bets": 0, "hits": 0},
    "Over 2.5 (>90%)": {"bets": 0, "hits": 0}
}

for season in recent_seasons:
    cur.execute("SELECT * FROM matches WHERE season = ? ORDER BY day ASC", (season,))
    all_matches = cur.fetchall()
    
    standings = collections.defaultdict(lambda: {'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0})
    matches_by_day = collections.defaultdict(list)
    for m in all_matches:
        if m['h'] is not None and m['a'] is not None:
            matches_by_day[m['day']].append(m)
            
    # Keep track of history
    standings_history = {}
            
    for day in range(1, 31):
        if day not in matches_by_day: continue
        
        # Save exact standings BEFORE this day is played
        standings_history[day] = copy.deepcopy(standings)
        
        # In real life, user says if playing MD11, the table might be from MD9.
        # This means the table is delayed by 1 full matchday.
        # So for `day`, we use `standings_history[day - 1]`
        target_table_day = day - 1
        if target_table_day < 1: target_table_day = 1
        
        delayed_standings = standings_history.get(target_table_day, standings_history[day])
        
        sorted_teams = sorted(delayed_standings.items(), key=lambda x: (x[1]['pts'], x[1]['gd'], x[1]['gf']), reverse=True)
        if target_table_day == 1:
            st = [(m['home'], 0) for m in matches_by_day[day]] + [(m['away'], 0) for m in matches_by_day[day]]
            sorted_teams = [(t, 0) for t in sorted(list(set([t[0] for t in st])))]
            
        tiers = {team if isinstance(team, str) else team[0]: get_tier(i + 1) for i, team in enumerate(sorted_teams)}
        micro_tiers = {team if isinstance(team, str) else team[0]: get_micro_tier(i + 1) for i, team in enumerate(sorted_teams)}
        
        for m in matches_by_day[day]:
            h_team, a_team, h_goals, a_goals = m['home'], m['away'], m['h'], m['a']
            
            if day >= 5:
                h_tier = tiers.get(h_team, "T3")
                a_tier = tiers.get(a_team, "T3")
                h_micro = micro_tiers.get(h_team, "E")
                a_micro = micro_tiers.get(a_team, "E")
                
                macro_row = macro_patterns.get((h_team, a_team, h_tier, a_tier), {})
                micro_row = micro_patterns.get((h_team, a_team, h_micro, a_micro), {})
                
                if micro_row.get('w_1_rate', 0) >= 0.85 or macro_row.get('w_1_rate', 0) >= 0.85:
                    stats["Home Win (>85%)"]["bets"] += 1
                    if h_goals > a_goals: stats["Home Win (>85%)"]["hits"] += 1

                if micro_row.get('w_u25_rate', 0) >= 0.90 or macro_row.get('w_u25_rate', 0) >= 0.90:
                    stats["Under 2.5 (>90%)"]["bets"] += 1
                    if (h_goals + a_goals) < 2.5: stats["Under 2.5 (>90%)"]["hits"] += 1

                if micro_row.get('w_o25_rate', 0) >= 0.90 or macro_row.get('w_o25_rate', 0) >= 0.90:
                    stats["Over 2.5 (>90%)"]["bets"] += 1
                    if (h_goals + a_goals) > 2.5: stats["Over 2.5 (>90%)"]["hits"] += 1

        # Update actual live standings with today's matches
        for m in matches_by_day[day]:
            h, a, hg, ag = m['home'], m['away'], m['h'], m['a']
            if hg > ag: standings[h]['pts'] += 3
            elif hg < ag: standings[a]['pts'] += 3
            else:
                standings[h]['pts'] += 1
                standings[a]['pts'] += 1
            standings[h]['gd'] += (hg - ag)
            standings[a]['gd'] += (ag - hg)
            standings[h]['gf'] += hg
            standings[a]['gf'] += ag

print("\n--- DELAYED STANDINGS PERFORMANCE (10 SEASONS) ---")
total_bets = 0
total_hits = 0
for market, data in stats.items():
    bets = data["bets"]
    hits = data["hits"]
    rate = (hits / bets * 100) if bets > 0 else 0
    total_bets += bets
    total_hits += hits
    print(f"🎯 {market}: {hits}/{bets} -> {rate:.2f}% Win Rate")

overall_rate = (total_hits / total_bets * 100) if total_bets > 0 else 0
print(f"\n🏆 COMBINED EXTREME LOCKS (WITH 1-MD DELAY): {total_hits} Wins / {total_bets} Bets -> {overall_rate:.2f}% Win Rate")
