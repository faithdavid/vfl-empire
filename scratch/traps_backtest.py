import sqlite3
import pandas as pd
from collections import defaultdict

def main():
    conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db')
    cur = conn.cursor()
    
    # Get all results ordered by season and matchday
    cur.execute("""
        SELECT season_id, match_day, home_team, away_team, home_goals, away_goals 
        FROM results 
        WHERE season_id IS NOT NULL
        ORDER BY season_id, match_day
    """)
    rows = cur.fetchall()
    
    # Group by season
    seasons = defaultdict(list)
    for r in rows:
        seasons[r[0]].append(r)
        
    print(f"Total seasons found: {len(seasons)}")
    
    # We will simulate the table standings for each season
    total_bets = 0
    total_wins = 0
    total_profit = 0.0 # Assuming flat 1 unit bets, avg odds 1.8 for 1X, 2.0 for Win, etc
    
    for season_id, matches in seasons.items():
        # state
        points = defaultdict(int)
        goals_diff = defaultdict(int)
        form = defaultdict(list) # list of 'W', 'D', 'L'
        
        # group matches by matchday
        mds = defaultdict(list)
        for m in matches:
            mds[m[1]].append(m)
            
        for md in sorted(mds.keys()):
            if md > 5:
                # Calculate rankings before this matchday starts
                def get_sort_key(team):
                    return (points[team], goals_diff[team])
                
                ranked_teams = sorted(points.keys(), key=get_sort_key, reverse=True)
                
                for m in mds[md]:
                    home, away = m[2], m[3]
                    hg, ag = m[4], m[5]
                    
                    if home not in ranked_teams or away not in ranked_teams:
                        continue
                        
                    h_rank = ranked_teams.index(home) + 1
                    a_rank = ranked_teams.index(away) + 1
                    
                    h_form_list = form[home][-5:]
                    a_form_list = form[away][-5:]
                    
                    h_form_str = ""
                    if h_form_list:
                        # W3, L4, etc.
                        streak_char = h_form_list[-1]
                        count = 0
                        for c in reversed(h_form_list):
                            if c == streak_char:
                                count += 1
                            else:
                                break
                        h_form_str = f"{streak_char}{count}"
                    
                    a_form_str = ""
                    if a_form_list:
                        streak_char = a_form_list[-1]
                        count = 0
                        for c in reversed(a_form_list):
                            if c == streak_char:
                                count += 1
                            else:
                                break
                        a_form_str = f"{streak_char}{count}"
                        
                    # CRUSHER TRAP
                    # Top 4 (W3+) vs Bot 4 (L3+) -> Bet Opponent Win
                    is_crusher = False
                    bet_won = False
                    profit = 0
                    if h_rank <= 4 and h_form_str.startswith('W') and int(h_form_str[1:]) >= 3:
                        if a_rank >= 13 and a_form_str.startswith('L') and int(a_form_str[1:]) >= 3:
                            is_crusher = True
                            # Bet Away Win (Trap) -> meaning Away should win!
                            if ag > hg: bet_won = True
                    elif a_rank <= 4 and a_form_str.startswith('W') and int(a_form_str[1:]) >= 3:
                        if h_rank >= 13 and h_form_str.startswith('L') and int(h_form_str[1:]) >= 3:
                            is_crusher = True
                            # Bet Home Win
                            if hg > ag: bet_won = True
                            
                    # GRAVITY WELL TRAP
                    # Bot 4 (L4+) vs ANY -> Bet Opponent Win or Draw (1X/X2)
                    is_gravity = False
                    if h_rank >= 13 and h_form_str.startswith('L') and int(h_form_str[1:]) >= 4:
                        is_gravity = True
                        # Bet Away Win or Draw (X2)
                        if ag >= hg: bet_won = True
                    elif a_rank >= 13 and a_form_str.startswith('L') and int(a_form_str[1:]) >= 4:
                        is_gravity = True
                        # Bet Home Win or Draw (1X)
                        if hg >= ag: bet_won = True
                        
                    if is_crusher or is_gravity:
                        total_bets += 1
                        if bet_won:
                            total_wins += 1
                            if is_crusher: total_profit += 1.5 # Avg odds 2.5 - 1 = +1.5
                            if is_gravity: total_profit += 0.4 # Avg odds 1.4 - 1 = +0.4
                        else:
                            total_profit -= 1.0 # Lost 1 unit
            
            # Update state after matchday
            for m in mds[md]:
                home, away, hg, ag = m[2], m[3], m[4], m[5]
                goals_diff[home] += (hg - ag)
                goals_diff[away] += (ag - hg)
                if hg > ag:
                    points[home] += 3
                    form[home].append('W')
                    form[away].append('L')
                elif hg < ag:
                    points[away] += 3
                    form[away].append('W')
                    form[home].append('L')
                else:
                    points[home] += 1
                    points[away] += 1
                    form[home].append('D')
                    form[away].append('D')

    print(f"Total Bets: {total_bets}")
    print(f"Total Wins: {total_wins}")
    print(f"Win Rate: {(total_wins/total_bets)*100 if total_bets > 0 else 0:.2f}%")
    print(f"Estimated Profit (Units): {total_profit:.2f}")

if __name__ == '__main__':
    main()
