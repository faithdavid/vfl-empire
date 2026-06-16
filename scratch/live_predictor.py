import sqlite3
import pandas as pd

conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-empire/data/databases/history.db')

# Get latest season
latest_season = pd.read_sql_query("SELECT season FROM matches ORDER BY season DESC LIMIT 1", conn).iloc[0]['season']
latest_day = pd.read_sql_query(f"SELECT MAX(day) as d FROM matches WHERE season = '{latest_season}'", conn).iloc[0]['d']

df = pd.read_sql_query(f"SELECT home, away, h, a, outcome FROM matches WHERE season = '{latest_season}'", conn)

team_stats = {}
team_streaks = {}

for _, row in df.iterrows():
    h_team, a_team, h, a = row['home'], row['away'], row['h'], row['a']
    if pd.isna(h) or pd.isna(a): continue
    
    if h_team not in team_stats:
        team_stats[h_team] = {'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0}
        team_streaks[h_team] = []
    if a_team not in team_stats:
        team_stats[a_team] = {'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0}
        team_streaks[a_team] = []
        
    team_stats[h_team]['gf'] += h; team_stats[h_team]['ga'] += a
    team_stats[h_team]['gd'] += (h - a)
    team_stats[a_team]['gf'] += a; team_stats[a_team]['ga'] += h
    team_stats[a_team]['gd'] += (a - h)
    
    if h > a:
        team_stats[h_team]['pts'] += 3
        team_streaks[h_team].append('W'); team_streaks[a_team].append('L')
    elif h == a:
        team_stats[h_team]['pts'] += 1; team_stats[a_team]['pts'] += 1
        team_streaks[h_team].append('D'); team_streaks[a_team].append('D')
    else:
        team_stats[a_team]['pts'] += 3
        team_streaks[h_team].append('L'); team_streaks[a_team].append('W')

def get_current_streak(history):
    if not history: return '-', 0
    last_res = history[-1]
    count = 0
    for res in reversed(history):
        if res == last_res: count += 1
        else: break
    return last_res, count

print(f"=========================================================")
print(f" LIVE PREDICTOR ALGORITHM: {latest_season} | PREPARING FOR MATCHDAY {latest_day + 1}")
print(f"=========================================================\n")

# Rank the teams
ranked_teams = sorted(team_stats.keys(), key=lambda t: (team_stats[t]['pts'], team_stats[t]['gd'], team_stats[t]['gf']), reverse=True)
ranks = {team: i+1 for i, team in enumerate(ranked_teams)}

def get_rank_bracket(r):
    if r <= 4: return 'Top4'
    if r <= 8: return 'UpMid'
    if r <= 12: return 'LowMid'
    return 'Bot4'

# Create Cheat Sheet
cheat_sheet = []
for team in ranked_teams:
    r = ranks[team]
    pts = team_stats[team]['pts']
    bracket = get_rank_bracket(r)
    s_type, s_len = get_current_streak(team_streaks[team])
    streak_str = f"{s_type}{s_len}"
    
    # Identify Active Traps
    trap = ""
    if bracket == 'Top4' and streak_str == 'W4': trap = "🔥 ACTIVE CRUSHER (Bet Home if playing Bot4 L3)"
    elif bracket == 'Top4' and streak_str == 'L1': trap = "⚠️ STREAK SNAPPER (Target Draws/X2 vs W6 or Target O1.5 vs W5)"
    elif bracket == 'Top4' and s_type == 'D': trap = "🛑 STANDOFF PROTOCOL (Target Draws against other Top4 W2)"
    elif bracket == 'Bot4' and streak_str == 'L5': trap = "⚓ STAGNATION TRAP (Target 1X vs Bot4 L1)"
    elif bracket == 'Bot4' and streak_str == 'L3': trap = "💀 GUARANTEED LOSER (Bet Against if playing Top4 W4)"
    elif bracket == 'LowMid' and streak_str == 'W3': trap = "📉 GRAVITY CORRECTION (Bet Against if playing Top4 W2)"
    elif bracket == 'Bot4' and streak_str == 'W2': trap = "🤡 FALSE HOPE (Bet Against if playing Top4 W2)"
    
    cheat_sheet.append((r, team, bracket, pts, streak_str, trap))

print(f"{'Rank':<5} | {'Team':<15} | {'Bracket':<8} | {'Pts':<4} | {'Streak':<6} | {'Active Algorithm Trap'}")
print("-" * 110)
for r, t, b, p, s, trap in cheat_sheet:
    print(f"{r:<5} | {t:<15} | {b:<8} | {p:<4} | {s:<6} | {trap}")

print("\n=========================================================")
print(" HOW TO USE THIS CHEAT SHEET FOR MATCHDAY", latest_day + 1)
print("=========================================================")
print("1. Look at the MSport fixtures for the upcoming Matchday.")
print("2. Check the combinations above.")
print("3. If you see a '🔥 ACTIVE CRUSHER' playing a '💀 GUARANTEED LOSER', Bet HOME WIN + UNDER 3.5.")
print("4. If you see a '📉 GRAVITY CORRECTION' playing a Top4 W2, Bet the Top 4 Team.")
print("5. If no exact Traps align, play the 'General Mismatch' (Top4 Home vs Bot4 Away).")
