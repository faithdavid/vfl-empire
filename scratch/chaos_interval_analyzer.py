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

def get_micro_tier(rank):
    if rank <= 2: return "A"
    elif rank <= 4: return "B"
    elif rank <= 6: return "C"
    elif rank <= 8: return "D"
    elif rank <= 10: return "E"
    elif rank <= 12: return "F"
    elif rank <= 14: return "G"
    else: return "H"

def eval_hit(market, home_goals, away_goals):
    tg = home_goals + away_goals
    if market == "Under 3.5": return tg < 3.5
    if market == "Over 1.5": return tg > 1.5
    return False

# Find seasons with 30 days
cur.execute("SELECT season, MAX(day) as max_day FROM matches GROUP BY season HAVING max_day >= 30 ORDER BY season ASC")
seasons = [row['season'] for row in cur.fetchall()]

season_stats = []

for season in seasons:
    cur.execute("SELECT * FROM matches WHERE season = ? ORDER BY day ASC", (season,))
    all_matches = cur.fetchall()
    
    standings = collections.defaultdict(lambda: {'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0})
    matches_by_day = collections.defaultdict(list)
    for m in all_matches:
        if m['h'] is not None and m['a'] is not None:
            matches_by_day[m['day']].append(m)
        
    hits = 0
    total = 0
    
    for day in range(1, 31):
        if day not in matches_by_day: continue
        sorted_teams = sorted(standings.items(), key=lambda x: (x[1]['pts'], x[1]['gd'], x[1]['gf']), reverse=True)
        if day == 1:
            st = [(m['home'], 0) for m in matches_by_day[day]] + [(m['away'], 0) for m in matches_by_day[day]]
            sorted_teams = [(t, 0) for t in sorted(list(set([t[0] for t in st])))]
            
        micro_tiers = {team if isinstance(team, str) else team[0]: get_micro_tier(i + 1) for i, team in enumerate(sorted_teams)}
        
        for m in matches_by_day[day]:
            h_team = m['home']
            a_team = m['away']
            h_goals = m['h']
            a_goals = m['a']
            
            if day >= 5:
                h_micro = micro_tiers.get(h_team, "E")
                a_micro = micro_tiers.get(a_team, "E")
                micro_key = (h_team, a_team, h_micro, a_micro)
                micro_row = micro_patterns.get(micro_key, {})
                
                locks = []
                if micro_row.get('w_o15_rate', 0) >= 0.80: locks.append("Over 1.5")
                if micro_row.get('w_u35_rate', 0) >= 0.85: locks.append("Under 3.5")
                
                locks = list(set(locks))
                for market in locks:
                    total += 1
                    if eval_hit(market, h_goals, a_goals): hits += 1
                        
            # Update standings
            if h_goals > a_goals:
                standings[h_team]['pts'] += 3
            elif h_goals < a_goals:
                standings[a_team]['pts'] += 3
            else:
                standings[h_team]['pts'] += 1
                standings[a_team]['pts'] += 1
            standings[h_team]['gd'] += (h_goals - a_goals)
            standings[a_team]['gd'] += (a_goals - h_goals)
            standings[h_team]['gf'] += h_goals
            standings[a_team]['gf'] += a_goals
            
    if total > 0:
        rate = (hits / total * 100)
        # Threshold: if Micro logic hits less than 85%, it's slipping. Less than 80% is chaos.
        if rate < 80.0:
            phase = "CHAOS"
        elif rate > 88.0:
            phase = "STABLE"
        else:
            phase = "MIXED"
        season_stats.append({'season': season, 'rate': rate, 'phase': phase})

print("--- RNG PHASE INTERVAL ANALYSIS ---")
chaos_intervals = []
last_chaos_idx = None

for i, stat in enumerate(season_stats):
    print(f"Season {i+1} ({stat['season']}): Micro Hit Rate = {stat['rate']:.1f}% [{stat['phase']}]")
    if stat['phase'] == 'CHAOS':
        if last_chaos_idx is not None:
            interval = i - last_chaos_idx
            chaos_intervals.append(interval)
        last_chaos_idx = i

if chaos_intervals:
    avg_interval = sum(chaos_intervals) / len(chaos_intervals)
    print(f"\nAverage interval between CHAOS seasons: {avg_interval:.2f} seasons")
    print(f"Raw intervals: {chaos_intervals}")
else:
    print("\nNot enough CHAOS seasons to calculate an interval.")
