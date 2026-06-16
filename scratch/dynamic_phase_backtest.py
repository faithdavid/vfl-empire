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

def eval_hit(market, home_goals, away_goals):
    tg = home_goals + away_goals
    if market == "Under 3.5": return tg < 3.5
    if market == "Over 1.5": return tg > 1.5
    return False

# We will test on the last complete season
target_season = 'vf:season:3086405'
cur.execute("SELECT * FROM matches WHERE season = ? ORDER BY day ASC", (target_season,))
all_matches = cur.fetchall()

standings = collections.defaultdict(lambda: {'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0})
matches_by_day = collections.defaultdict(list)
for m in all_matches:
    if m['h'] is not None and m['a'] is not None:
        matches_by_day[m['day']].append(m)

# Tracker for rolling Micro logic accuracy
micro_history = collections.deque(maxlen=10) # Track last 10 micro bets

total_bets = 0
total_wins = 0

print(f"--- DYNAMIC PHASE-SWITCHING BACKTEST (Season {target_season}) ---\n")

for day in range(1, 31):
    if day not in matches_by_day: continue
    
    # Calculate standings before the matches
    sorted_teams = sorted(standings.items(), key=lambda x: (x[1]['pts'], x[1]['gd'], x[1]['gf']), reverse=True)
    if day == 1:
        st = [(m['home'], 0) for m in matches_by_day[day]] + [(m['away'], 0) for m in matches_by_day[day]]
        sorted_teams = [(t, 0) for t in sorted(list(set([t[0] for t in st])))]
        
    tiers = {team if isinstance(team, str) else team[0]: get_tier(i + 1) for i, team in enumerate(sorted_teams)}
    micro_tiers = {team if isinstance(team, str) else team[0]: get_micro_tier(i + 1) for i, team in enumerate(sorted_teams)}
    
    # Determine Phase
    if len(micro_history) == 10:
        micro_win_rate = sum(micro_history) / 10.0
    else:
        micro_win_rate = 1.0 # Assume STABLE to start
        
    if micro_win_rate < 0.70:
        phase = "🔴 CHAOS MODE"
    else:
        phase = "🟢 STABLE MODE"
        
    day_predictions = []
        
    for m in matches_by_day[day]:
        h_team = m['home']
        a_team = m['away']
        h_goals = m['h']
        a_goals = m['a']
        
        # Always evaluate Micro logic silently in the background to track the RNG algorithm
        if day >= 5:
            h_micro = micro_tiers.get(h_team, "E")
            a_micro = micro_tiers.get(a_team, "E")
            micro_key = (h_team, a_team, h_micro, a_micro)
            micro_row = micro_patterns.get(micro_key, {})
            
            # Simulated Micro bet (the phantom bet to test the waters)
            if micro_row.get('w_o15_rate', 0) >= 0.80:
                is_hit = eval_hit("Over 1.5", h_goals, a_goals)
                micro_history.append(1 if is_hit else 0)
            elif micro_row.get('w_u35_rate', 0) >= 0.85:
                is_hit = eval_hit("Under 3.5", h_goals, a_goals)
                micro_history.append(1 if is_hit else 0)
                
            # Now make the ACTUAL bets based on the Phase
            h_tier = tiers.get(h_team, "T3")
            a_tier = tiers.get(a_team, "T3")
            macro_key = (h_team, a_team, h_tier, a_tier)
            macro_row = macro_patterns.get(macro_key, {})
            
            if phase == "🔴 CHAOS MODE":
                # In Chaos, ONLY bet pure Macro Under 3.5 Locks
                if macro_row.get('w_u35_rate', 0) >= 0.85:
                    is_hit = eval_hit("Under 3.5", h_goals, a_goals)
                    result_str = "✅ WIN" if is_hit else "❌ LOSS"
                    if is_hit: total_wins += 1
                    total_bets += 1
                    day_predictions.append(f"   [{h_team} v {a_team}] Macro U3.5 Lock -> {result_str} ({h_goals}-{a_goals})")
                    
            elif phase == "🟢 STABLE MODE":
                # In Stable, bet CONFLUENCE (Both must agree)
                macro_locks = []
                if macro_row.get('w_u35_rate', 0) >= 0.85: macro_locks.append("Under 3.5")
                if macro_row.get('w_o15_rate', 0) >= 0.80: macro_locks.append("Over 1.5")
                
                micro_locks = []
                if micro_row.get('w_o15_rate', 0) >= 0.80: micro_locks.append("Over 1.5")
                if micro_row.get('w_u35_rate', 0) >= 0.85: micro_locks.append("Under 3.5")
                
                confluence = list(set(macro_locks) & set(micro_locks))
                for lock in confluence:
                    is_hit = eval_hit(lock, h_goals, a_goals)
                    result_str = "✅ WIN" if is_hit else "❌ LOSS"
                    if is_hit: total_wins += 1
                    total_bets += 1
                    day_predictions.append(f"   [{h_team} v {a_team}] Confluence {lock} -> {result_str} ({h_goals}-{a_goals})")

    if day_predictions:
        print(f"[Matchday {day:02d}] {phase} (RNG Stable: {micro_win_rate*100:.0f}%)")
        for pred in day_predictions:
            print(pred)
        print("-" * 60)
        
    # Update standings
    for m in matches_by_day[day]:
        h_team, a_team, h_goals, a_goals = m['home'], m['away'], m['h'], m['a']
        if h_goals > a_goals: standings[h_team]['pts'] += 3
        elif h_goals < a_goals: standings[a_team]['pts'] += 3
        else:
            standings[h_team]['pts'] += 1
            standings[a_team]['pts'] += 1
        standings[h_team]['gd'] += (h_goals - a_goals)
        standings[a_team]['gd'] += (a_goals - h_goals)
        standings[h_team]['gf'] += h_goals
        standings[a_team]['gf'] += a_goals

final_rate = (total_wins / total_bets * 100) if total_bets > 0 else 0
print(f"\n🏆 DYNAMIC ENGINE FINAL RESULT: {total_wins} Wins / {total_bets} Bets -> {final_rate:.2f}% Win Rate")
