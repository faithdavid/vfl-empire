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

bet_sequence = []

# Assuming average odds for these extreme traps
ODDS_HOME_WIN = 2.05
ODDS_U25 = 1.85
ODDS_O25 = 1.85

for season in recent_seasons:
    cur.execute("SELECT * FROM matches WHERE season = ? ORDER BY day ASC", (season,))
    all_matches = cur.fetchall()
    standings = collections.defaultdict(lambda: {'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0})
    matches_by_day = collections.defaultdict(list)
    for m in all_matches:
        if m['h'] is not None and m['a'] is not None:
            matches_by_day[m['day']].append(m)
            
    for day in range(1, 31):
        if day not in matches_by_day: continue
        
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
                
                placed_bet = False
                
                # Check Home Win
                if micro_row.get('w_1_rate', 0) >= 0.85 or macro_row.get('w_1_rate', 0) >= 0.85:
                    is_win = (h_goals > a_goals)
                    bet_sequence.append(("Home Win", is_win, ODDS_HOME_WIN))
                    placed_bet = True

                # Check Under 2.5
                if not placed_bet and (micro_row.get('w_u25_rate', 0) >= 0.90 or macro_row.get('w_u25_rate', 0) >= 0.90):
                    is_win = ((h_goals + a_goals) < 2.5)
                    bet_sequence.append(("Under 2.5", is_win, ODDS_U25))
                    placed_bet = True

                # Check Over 2.5
                if not placed_bet and (micro_row.get('w_o25_rate', 0) >= 0.90 or macro_row.get('w_o25_rate', 0) >= 0.90):
                    is_win = ((h_goals + a_goals) > 2.5)
                    bet_sequence.append(("Over 2.5", is_win, ODDS_O25))

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

# COMPOUNDING SIMULATION
print("--- 5-STEP COMPOUNDING SIMULATION ---")
print("Rules:")
print("- Step 1 Base Stake: 10 N")
print("- Cycle Length: 5 consecutive bets (100% rollover)")
print("- If cycle completes: Bank 60% of returns. New base stake becomes 40% of returns.")
print("- If cycle crashes: Restart. If Bank >= 1000, new base is 200 N. Else, new base is 10 N.\n")

banked_profit = 0.0
base_stake = 10.0
current_stake = 10.0
current_step = 1

print("Chronological Run:")
for idx, (market, is_win, odds) in enumerate(bet_sequence):
    print(f"Bet {idx+1} [Step {current_step}]: {market} @ {odds:.2f} | Stake: {current_stake:.2f} N", end=" -> ")
    
    if is_win:
        current_stake = current_stake * odds
        print(f"✅ WIN | Current Pot: {current_stake:.2f} N")
        
        if current_step == 5:
            # Cycle completed
            payout = current_stake
            bank = payout * 0.60
            new_base = payout * 0.40
            
            banked_profit += bank
            print(f"  🎉 CYCLE COMPLETE! Banking {bank:.2f} N | New Base Stake for next cycle: {new_base:.2f} N")
            
            base_stake = new_base
            current_stake = base_stake
            current_step = 1
        else:
            current_step += 1
            
    else:
        print(f"❌ LOSS | Cycle crashed!")
        # Restart logic based on banked profit
        if banked_profit >= 1000:
            print(f"  🔄 Bank > 1000 N. Restarting cycle with 200 N base stake (drawn from bank).")
            banked_profit -= 200.0
            base_stake = 200.0
        else:
            print(f"  🔄 Bank < 1000 N. Restarting cycle with 10 N base stake.")
            banked_profit -= 10.0
            base_stake = 10.0
            
        current_stake = base_stake
        current_step = 1

# Note: banked_profit was tracked as purely "withdrawn" money. 
# Since we drew from the bank upon crashes, we must account for initial out-of-pocket funding.
# We started with 10 N initially.
out_of_pocket = 10.0

print("\n--- SIMULATION RESULTS ---")
print(f"Total Bets: {len(bet_sequence)}")
print(f"Total Cycles Completed (5 Wins): {banked_profit > 0}")
print(f"Final Naira Banked (Withdrawn & Safe): {banked_profit:.2f} N")
print(f"Current Rollover Pot (Unfinished Cycle): {current_stake if current_step > 1 else 0:.2f} N")
print(f"NET PROFIT: {(banked_profit + (current_stake if current_step > 1 else 0)) - out_of_pocket:.2f} N")
