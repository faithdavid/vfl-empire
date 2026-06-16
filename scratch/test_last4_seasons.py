import json
from collections import defaultdict

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])
# Chunk matches into full seasons (240 matches each)
seasons = [matches[i:i+240] for i in range(0, len(matches), 240) if len(matches[i:i+240]) == 240]

if len(seasons) >= 4:
    seasons_to_test = seasons[-4:]
else:
    seasons_to_test = seasons

print(f"Testing on the last {len(seasons_to_test)} completed seasons...\n")

def get_rank_group(rank):
    if rank <= 6: return "Top6"
    if rank <= 12: return "Mid6"
    return "Bot4"

avg_rank_pts = {1: 32, 2: 29, 3: 28, 4: 26, 5: 25, 6: 24, 7: 22, 8: 20, 9: 20, 10: 18, 11: 17, 12: 16, 13: 15, 14: 14, 15: 11, 16: 9}

total_bets = 0
total_won = 0
total_pnl = 0

for season_idx, season_matches in enumerate(seasons_to_test):
    print(f"--- SEASON {season_idx + 1} ---")
    
    # MD 15 Standings
    team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
    for m in season_matches:
        if m['match_day'] > 15: continue
        hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
        h, a = m['home_team'], m['away_team']
        if hg > ag: team_pts[h] += 3
        elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
        else: team_pts[a] += 3
        
    ranks = {t: i+1 for i, (t, _) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))}
    
    quota_status = {}
    for t, pts in team_pts.items():
        r = ranks[t]
        avg = avg_rank_pts[r]
        if pts > avg + 1: quota_status[t] = "OverQuota"
        elif pts < avg - 1: quota_status[t] = "UnderQuota"
        else: quota_status[t] = "OnQuota"

    leg1_dict = {}
    for m in season_matches:
        if m['match_day'] <= 15:
            pair = tuple(sorted([m['home_team'], m['away_team']]))
            leg1_dict[pair] = m

    s_bets = 0
    s_won = 0
    s_pnl = 0

    for m2 in season_matches:
        if m2['match_day'] <= 15: continue
        md2 = m2['match_day']
        
        pair = tuple(sorted([m2['home_team'], m2['away_team']]))
        m1 = leg1_dict.get(pair)
        if not m1: continue
        
        h1, a1 = m1['home_team'], m1['away_team']
        hg1, ag1 = m1['home_goals'], m1['away_goals']
        
        if hg1 > ag1: w1, l1 = h1, a1
        elif ag1 > hg1: w1, l1 = a1, h1
        else: w1, l1 = "DRAW", "DRAW"
        
        h2, a2 = m2['home_team'], m2['away_team']
        hg2, ag2 = m2['home_goals'], m2['away_goals']
        
        h2_rank = get_rank_group(ranks[h2])
        a2_rank = get_rank_group(ranks[a2])
        
        bet = None
        odds = 0
        hit = False
        
        # Rule 1: Delayed Elite Win
        if w1 == "DRAW" and hg1 == 0 and h2_rank == "Top6" and a2_rank == "Mid6":
            bet = "Home Win (Delayed Elite Win)"
            odds = 1.60
            if hg2 > ag2: hit = True
            
        # Rule 2: Elite Vengeance Blowout
        elif w1 != "DRAW" and abs(hg1-ag1) >= 3 and get_rank_group(ranks[w1]) == "Mid6" and get_rank_group(ranks[l1]) == "Top6" and h2 == l1:
            bet = "Home Win (Elite Vengeance)"
            odds = 1.50
            if hg2 > ag2: hit = True

        # Rule 3: Point-Aware Sabotage (OverQuota Fade)
        elif w1 != "DRAW" and quota_status[w1] == "OverQuota" and a2 == w1:
            bet = "1X Double Chance (OverQuota Fade)"
            odds = 2.20
            if hg2 >= ag2: hit = True
            
        # Rule 4: Double Elite Shootout
        elif w1 != "DRAW" and abs(hg1-ag1) == 2 and get_rank_group(ranks[w1]) == "Top6" and get_rank_group(ranks[l1]) == "Top6" and h2 == l1:
            bet = "O2.5 & BTTS Yes (Elite Shootout)"
            odds = 2.00
            if hg2+ag2 > 2.5 and hg2>0 and ag2>0: hit = True
            
        # Rule 5: Away Revenge Trap
        elif w1 != "DRAW" and abs(hg1-ag1) == 1 and get_rank_group(ranks[w1]) == "Bot4" and get_rank_group(ranks[l1]) == "Top6" and h2 == w1:
            bet = "Away Win (Away Revenge Trap)"
            odds = 1.80
            if ag2 > hg2: hit = True

        if bet:
            s_bets += 1
            if hit:
                s_won += 1
                s_pnl += (odds - 1)
            else:
                s_pnl -= 1

    total_bets += s_bets
    total_won += s_won
    total_pnl += s_pnl
    print(f"Season Bets: {s_bets} | Hits: {s_won} | PnL: {s_pnl:+.2f} Units | Hit Rate: {(s_won/s_bets)*100 if s_bets>0 else 0:.1f}%\n")

print("=== 4-SEASON COMBINED PERFORMANCE ===")
print(f"Total Bets Placed: {total_bets}")
print(f"Total Hits: {total_won} ({(total_won/total_bets)*100 if total_bets>0 else 0:.1f}%)")
print(f"Total Net PnL: {total_pnl:+.2f} Units")
if total_bets > 0:
    print(f"Overall ROI: {(total_pnl/total_bets)*100:.1f}%")

