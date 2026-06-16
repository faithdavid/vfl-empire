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

# Build lookup dictionaries
macro_patterns = {}
for row in macro_data:
    macro_patterns[(row['home'], row['away'], row['home_tier'], row['away_tier'])] = row

micro_patterns = {}
for row in micro_data:
    micro_patterns[(row['home'], row['away'], row['home_tier'], row['away_tier'])] = row

# Connect to database
conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Find the most recent complete season
cur.execute("SELECT season FROM matches WHERE day = 30 ORDER BY season DESC LIMIT 1")
row = cur.fetchone()
if not row:
    print("No complete season found.")
    exit(1)
target_season = row['season']
print(f"Targeting last complete season: {target_season}")

# Fetch all matches for the season
cur.execute("SELECT * FROM matches WHERE season = ? ORDER BY day ASC", (target_season,))
all_matches = cur.fetchall()

# State for tracking points, goals, form
standings = collections.defaultdict(lambda: {'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0, 'form': []})

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

results = {
    'MACRO': {'hits': 0, 'total': 0},
    'MICRO': {'hits': 0, 'total': 0},
    'CONFLUENCE': {'hits': 0, 'total': 0}
}

def eval_hit(market, home_goals, away_goals):
    tg = home_goals + away_goals
    if market == "Under 3.5": return tg < 3.5
    if market == "Over 1.5": return tg > 1.5
    return False

matches_by_day = collections.defaultdict(list)
for m in all_matches:
    matches_by_day[m['day']].append(m)

print("Simulating Season...")
for day in range(1, 31):
    if day not in matches_by_day: continue
    
    # Calculate current standings BEFORE matchday
    sorted_teams = sorted(standings.items(), key=lambda x: (x[1]['pts'], x[1]['gd'], x[1]['gf']), reverse=True)
    
    # Fill in default teams if day 1
    if day == 1:
        # Sort arbitrarily for Day 1
        sorted_teams = [(m['home'], 0) for m in matches_by_day[day]] + [(m['away'], 0) for m in matches_by_day[day]]
        sorted_teams = sorted(list(set([t[0] for t in sorted_teams])))
        sorted_teams = [(t, 0) for t in sorted_teams]
        
    tiers = {}
    micro_tiers = {}
    for i, data in enumerate(sorted_teams):
        rank = i + 1
        team = data[0] if isinstance(data, tuple) else data
        tiers[team] = get_tier(rank)
        micro_tiers[team] = get_micro_tier(rank)
        
    for m in matches_by_day[day]:
        h_team = m['home']
        a_team = m['away']
        h_goals = m['h']
        a_goals = m['a']
        
        # We predict if day >= 5
        if day >= 5:
            h_tier = tiers.get(h_team, "T3")
            a_tier = tiers.get(a_team, "T3")
            h_micro = micro_tiers.get(h_team, "E")
            a_micro = micro_tiers.get(a_team, "E")
            
            macro_key = (h_team, a_team, h_tier, a_tier)
            micro_key = (h_team, a_team, h_micro, a_micro)
            
            macro_row = macro_patterns.get(macro_key, {})
            micro_row = micro_patterns.get(micro_key, {})
            
            macro_locks = []
            if macro_row.get('w_u35_rate', 0) >= 0.85:
                macro_locks.append("Under 3.5")
            if macro_row.get('w_o15_rate', 0) >= 0.85:
                macro_locks.append("Over 1.5")
                
            micro_locks = []
            if micro_row.get('w_o15_rate', 0) >= 0.80:
                micro_locks.append("Over 1.5")
            if micro_row.get('w_u35_rate', 0) >= 0.85:
                micro_locks.append("Under 3.5")
            
            # Predict only Over 1.5 and Under 3.5 for this test
            
            for market in macro_locks:
                results['MACRO']['total'] += 1
                if eval_hit(market, h_goals, a_goals): results['MACRO']['hits'] += 1
                    
            for market in micro_locks:
                results['MICRO']['total'] += 1
                if eval_hit(market, h_goals, a_goals): results['MICRO']['hits'] += 1
                    
            confluence_locks = list(set(macro_locks) & set(micro_locks))
            for market in confluence_locks:
                results['CONFLUENCE']['total'] += 1
                if eval_hit(market, h_goals, a_goals): results['CONFLUENCE']['hits'] += 1

        # Update standings AFTER match
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

print("\n--- FULL SEASON 5296 INDEPENDENT BACKTEST RESULTS ---")
for t, d in results.items():
    hits = d['hits']
    total = d['total']
    rate = (hits / total * 100) if total > 0 else 0
    print(f"{t} LOGIC: {hits} Hits / {total} Total Predictions -> {rate:.2f}% Hit Rate")
