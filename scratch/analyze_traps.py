import sqlite3
import pandas as pd
from collections import defaultdict
import json

def main():
    conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db')
    cur = conn.cursor()
    cur.execute("""
        SELECT season_id, match_day, home_team, away_team, home_goals, away_goals 
        FROM results 
        WHERE season_id IS NOT NULL
        ORDER BY season_id, match_day
    """)
    rows = cur.fetchall()
    
    seasons = defaultdict(list)
    for r in rows:
        seasons[r[0]].append(r)
        
    records = []
    
    for season_id, matches in seasons.items():
        points = defaultdict(int)
        goals_diff = defaultdict(int)
        goals_scored = defaultdict(int)
        goals_conceded = defaultdict(int)
        form = defaultdict(list)
        
        mds = defaultdict(list)
        for m in matches:
            mds[m[1]].append(m)
            
        for md in sorted(mds.keys()):
            if md > 5:
                def get_sort_key(team):
                    return (points[team], goals_diff[team])
                
                ranked_teams = sorted(points.keys(), key=get_sort_key, reverse=True)
                
                for m in mds[md]:
                    home, away = m[2], m[3]
                    hg, ag = m[4], m[5]
                    
                    if home not in ranked_teams or away not in ranked_teams: continue
                        
                    h_rank = ranked_teams.index(home) + 1
                    a_rank = ranked_teams.index(away) + 1
                    
                    h_form_list = form[home][-5:]
                    a_form_list = form[away][-5:]
                    
                    def get_streak(flist):
                        if not flist: return ""
                        char = flist[-1]
                        c = 0
                        for x in reversed(flist):
                            if x == char: c += 1
                            else: break
                        return f"{char}{c}"
                        
                    h_form_str = get_streak(h_form_list)
                    a_form_str = get_streak(a_form_list)
                    
                    is_crusher = False
                    is_gravity = False
                    bet_won = False
                    trap_type = ""
                    
                    if h_rank <= 4 and h_form_str.startswith('W') and int(h_form_str[1:]) >= 3:
                        if a_rank >= 13 and a_form_str.startswith('L') and int(a_form_str[1:]) >= 3:
                            is_crusher = True
                            trap_type = "CRUSHER_HOME_FAV"
                            if hg > ag: bet_won = True
                    elif a_rank <= 4 and a_form_str.startswith('W') and int(a_form_str[1:]) >= 3:
                        if h_rank >= 13 and h_form_str.startswith('L') and int(h_form_str[1:]) >= 3:
                            is_crusher = True
                            trap_type = "CRUSHER_AWAY_FAV"
                            if ag > hg: bet_won = True
                            
                    if h_rank >= 13 and h_form_str.startswith('L') and int(h_form_str[1:]) >= 4:
                        is_gravity = True
                        trap_type = "GRAVITY_HOME_DOG"
                        if ag >= hg: bet_won = True # Bet X2
                    elif a_rank >= 13 and a_form_str.startswith('L') and int(a_form_str[1:]) >= 4:
                        is_gravity = True
                        trap_type = "GRAVITY_AWAY_DOG"
                        if hg >= ag: bet_won = True # Bet 1X
                        
                    if is_crusher or is_gravity:
                        records.append({
                            "matchday": md,
                            "trap_type": trap_type,
                            "h_rank": h_rank,
                            "a_rank": a_rank,
                            "h_points": points[home],
                            "a_points": points[away],
                            "h_gd": goals_diff[home],
                            "a_gd": goals_diff[away],
                            "h_gs": goals_scored[home],
                            "a_gs": goals_scored[away],
                            "h_gc": goals_conceded[home],
                            "a_gc": goals_conceded[away],
                            "won": bet_won
                        })
            
            for m in mds[md]:
                home, away, hg, ag = m[2], m[3], m[4], m[5]
                goals_diff[home] += (hg - ag)
                goals_diff[away] += (ag - hg)
                goals_scored[home] += hg
                goals_scored[away] += ag
                goals_conceded[home] += ag
                goals_conceded[away] += hg
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

    df = pd.DataFrame(records)
    df.to_csv("/home/ubuntu/faith-workspace/vfl-empire/scratch/trap_records.csv", index=False)
    
    # Analysis
    print("--- TRAP WIN RATES BY TYPE ---")
    print(df.groupby('trap_type')['won'].mean() * 100)
    print(df.groupby('trap_type').size())
    
    print("\n--- GOAL DIFFERENTIAL IMPACT ON CRUSHERS ---")
    crushers = df[df['trap_type'].str.contains('CRUSHER')].copy()
    crushers['gd_diff'] = abs(crushers['h_gd'] - crushers['a_gd'])
    crushers['gd_bucket'] = pd.qcut(crushers['gd_diff'], 3, labels=['Low', 'Med', 'High'])
    print(crushers.groupby('gd_bucket')['won'].mean() * 100)
    
    print("\n--- GOALS CONCEDED IMPACT ON GRAVITY WELLS ---")
    gravity = df[df['trap_type'].str.contains('GRAVITY')].copy()
    # For Gravity Home Dog, the dog is Home. For Gravity Away Dog, the dog is Away.
    def get_dog_gc(row):
        return row['h_gc'] if row['trap_type'] == 'GRAVITY_HOME_DOG' else row['a_gc']
    
    gravity['dog_gc'] = gravity.apply(get_dog_gc, axis=1)
    gravity['gc_bucket'] = pd.qcut(gravity['dog_gc'], 3, labels=['Low GC', 'Med GC', 'High GC'])
    print(gravity.groupby('gc_bucket')['won'].mean() * 100)

if __name__ == '__main__':
    main()
