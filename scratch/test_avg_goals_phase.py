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

# Fetch the last 7 complete seasons
cur.execute("SELECT season, MAX(day) as max_day FROM matches GROUP BY season HAVING max_day >= 30 ORDER BY season DESC LIMIT 7")
recent_seasons = [row['season'] for row in cur.fetchall()][::-1] # Reverse to be chronological

print(f"--- DYNAMIC PHASE DETECTOR BACKTEST (Avg Goals Method) ---")
print(f"Testing on 7 latest seasons: {recent_seasons}\n")

total_overall_bets = 0
total_overall_wins = 0

for season in recent_seasons:
    cur.execute("SELECT * FROM matches WHERE season = ? ORDER BY day ASC", (season,))
    all_matches = cur.fetchall()
    
    standings = collections.defaultdict(lambda: {'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0})
    matches_by_day = collections.defaultdict(list)
    for m in all_matches:
        if m['h'] is not None and m['a'] is not None:
            matches_by_day[m['day']].append(m)
            
    season_bets = 0
    season_wins = 0
    chaos_triggers = 0
    stable_triggers = 0
            
    for day in range(1, 31):
        if day not in matches_by_day: continue
        
        # Calculate Phase based on previous 3 matchdays
        if day >= 4:
            goals_list = []
            for d in range(day - 3, day):
                for pm in matches_by_day.get(d, []):
                    goals_list.append(pm['total'])
            
            if goals_list:
                avg_goals = sum(goals_list) / len(goals_list)
            else:
                avg_goals = 2.5
                
            if avg_goals < 2.3 or avg_goals > 3.1:
                phase = "CHAOS"
                chaos_triggers += 1
            else:
                phase = "STABLE"
                stable_triggers += 1
        else:
            phase = "STABLE"
        
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
                
                macro_key = (h_team, a_team, h_tier, a_tier)
                micro_key = (h_team, a_team, h_micro, a_micro)
                
                macro_row = macro_patterns.get(macro_key, {})
                micro_row = micro_patterns.get(micro_key, {})
                
                if phase == "CHAOS":
                    # Only bet Pure Macro Under 3.5
                    if macro_row.get('w_u35_rate', 0) >= 0.85:
                        season_bets += 1
                        total_overall_bets += 1
                        if eval_hit("Under 3.5", h_goals, a_goals):
                            season_wins += 1
                            total_overall_wins += 1
                else:
                    # Stable: Bet Confluence
                    macro_locks = []
                    if macro_row.get('w_u35_rate', 0) >= 0.85: macro_locks.append("Under 3.5")
                    if macro_row.get('w_o15_rate', 0) >= 0.80: macro_locks.append("Over 1.5")
                    
                    micro_locks = []
                    if micro_row.get('w_o15_rate', 0) >= 0.80: micro_locks.append("Over 1.5")
                    if micro_row.get('w_u35_rate', 0) >= 0.85: micro_locks.append("Under 3.5")
                    
                    confluence = list(set(macro_locks) & set(micro_locks))
                    for lock in confluence:
                        season_bets += 1
                        total_overall_bets += 1
                        if eval_hit(lock, h_goals, a_goals):
                            season_wins += 1
                            total_overall_wins += 1

        # Update standings
        if h_goals > a_goals: standings[h_team]['pts'] += 3
        elif h_goals < a_goals: standings[a_team]['pts'] += 3
        else:
            standings[h_team]['pts'] += 1
            standings[a_team]['pts'] += 1
        standings[h_team]['gd'] += (h_goals - a_goals)
        standings[a_team]['gd'] += (a_goals - h_goals)
        standings[h_team]['gf'] += h_goals
        standings[a_team]['gf'] += a_goals
        
    s_rate = (season_wins / season_bets * 100) if season_bets > 0 else 0
    print(f"Season {season}: {season_wins}/{season_bets} Hits -> {s_rate:.2f}% (Stable Days: {stable_triggers}, Chaos Days: {chaos_triggers})")

overall_rate = (total_overall_wins / total_overall_bets * 100) if total_overall_bets > 0 else 0
print(f"\n🏆 COMBINED 7-SEASON PERFORMANCE: {total_overall_wins} Wins / {total_overall_bets} Bets -> {overall_rate:.2f}% Win Rate")
