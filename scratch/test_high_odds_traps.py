import sqlite3
import json
import collections

# Load patterns
try:
    with open('/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json', 'r') as f:
        macro_data = json.load(f)
    with open('/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json', 'r') as f:
        micro_data = json.load(f)
except Exception as e:
    print(f"Error loading patterns: {e}")
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

# Fetch the last 10 complete seasons
cur.execute("SELECT season, MAX(day) as max_day FROM matches GROUP BY season HAVING max_day >= 30 ORDER BY season DESC LIMIT 10")
recent_seasons = [row['season'] for row in cur.fetchall()][::-1] 

print(f"--- RENOVATION BACKTEST: HIGH-ODDS TRAPS (10 SEASONS) ---")

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
            
    season_hits = 0
    season_bets = 0
            
    for day in range(1, 31):
        if day not in matches_by_day: continue
        
        # Calculate standings
        sorted_teams = sorted(standings.items(), key=lambda x: (x[1]['pts'], x[1]['gd'], x[1]['gf']), reverse=True)
        if day == 1:
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
                
                # Check Home Win Traps (>85%)
                if micro_row.get('w_1_rate', 0) >= 0.85 or macro_row.get('w_1_rate', 0) >= 0.85:
                    stats["Home Win (>85%)"]["bets"] += 1
                    season_bets += 1
                    if h_goals > a_goals:
                        stats["Home Win (>85%)"]["hits"] += 1
                        season_hits += 1

                # Check Under 2.5 Traps (>90%)
                if micro_row.get('w_u25_rate', 0) >= 0.90 or macro_row.get('w_u25_rate', 0) >= 0.90:
                    stats["Under 2.5 (>90%)"]["bets"] += 1
                    season_bets += 1
                    if (h_goals + a_goals) < 2.5:
                        stats["Under 2.5 (>90%)"]["hits"] += 1
                        season_hits += 1

                # Check Over 2.5 Traps (>90%)
                if micro_row.get('w_o25_rate', 0) >= 0.90 or macro_row.get('w_o25_rate', 0) >= 0.90:
                    stats["Over 2.5 (>90%)"]["bets"] += 1
                    season_bets += 1
                    if (h_goals + a_goals) > 2.5:
                        stats["Over 2.5 (>90%)"]["hits"] += 1
                        season_hits += 1

        # Update standings
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
            
    s_rate = (season_hits / season_bets * 100) if season_bets > 0 else 0
    print(f"Season {season}: {season_hits}/{season_bets} Hits -> {s_rate:.2f}%")

print("\n--- AGGREGATE PERFORMANCE (10 SEASONS) ---")
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
print(f"\n🏆 COMBINED EXTREME LOCKS: {total_hits} Wins / {total_bets} Bets -> {overall_rate:.2f}% Win Rate")
