import json
from collections import defaultdict

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])
seasons = [matches[i:i+240] for i in range(0, len(matches), 240) if len(matches[i:i+240]) == 240]
seasons_to_test = seasons[-2:]

def get_tier(rank):
    if rank <= 4: return "T1(1-4)"
    if rank <= 8: return "T2(5-8)"
    if rank <= 12: return "T3(9-12)"
    return "T4(13-16)"

def get_md_chunk(md):
    if md <= 5: return "MD 1-5"
    if md <= 10: return "MD 6-10"
    if md <= 15: return "MD 11-15"
    if md <= 20: return "MD 16-20"
    if md <= 25: return "MD 21-25"
    return "MD 26-30"

stake_per_md = 50.0 # Naira
total_profit = 0.0
total_staked = 0.0
total_parlays = 0
parlays_won = 0

print(f"=== TIER-ROUTING PARLAY TEST (Last 2 Seasons) ===\nStake per Matchday: ₦50\n")

for s_idx, season_matches in enumerate(seasons_to_test):
    print(f"--- SEASON {s_idx + 1} ---")
    team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
    
    season_staked = 0
    season_returned = 0
    
    for md in range(1, 31):
        ranks = {t: i+1 for i, (t, _) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))}
        
        md_picks = []
        md_odds_accumulator = 1.0
        all_hits = True
        
        for m in season_matches:
            if m['match_day'] != md: continue
            
            h, a = m['home_team'], m['away_team']
            if md == 1:
                h_tier, a_tier = "Start", "Start"
            else:
                h_tier, a_tier = get_tier(ranks[h]), get_tier(ranks[a])
                
            chunk = get_md_chunk(md)
            
            # The 5 universal routings (all are Home 1X)
            is_lock = False
            if chunk == "MD 11-15" and h_tier == "T4(13-16)" and a_tier == "T3(9-12)": is_lock = True
            elif chunk == "MD 21-25" and h_tier == "T2(5-8)" and a_tier == "T3(9-12)": is_lock = True
            elif chunk == "MD 26-30" and h_tier == "T1(1-4)" and a_tier == "T3(9-12)": is_lock = True
            elif chunk == "MD 6-10" and h_tier == "T2(5-8)" and a_tier == "T4(13-16)": is_lock = True
            elif chunk == "MD 16-20" and h_tier == "T1(1-4)" and a_tier == "T3(9-12)": is_lock = True
            elif chunk == "MD 16-20" and h_tier == "T1(1-4)" and a_tier == "T2(5-8)": is_lock = True
            
            if is_lock:
                hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
                win_or_draw = hg >= ag
                
                # Calculate Double Chance 1X odds from 1X2 odds
                o1 = float(m.get('odds', {}).get('home_win', 2.0))
                ox = float(m.get('odds', {}).get('draw', 3.0))
                if o1 > 0 and ox > 0:
                    dc_odds = 1.0 / ((1.0/o1) + (1.0/ox))
                else:
                    dc_odds = 1.25 # fallback if odds missing
                
                md_picks.append({
                    'match': f"{h} vs {a}",
                    'odds': round(dc_odds, 2),
                    'hit': win_or_draw
                })
                md_odds_accumulator *= dc_odds
                if not win_or_draw:
                    all_hits = False
                    
        if len(md_picks) > 0:
            total_staked += stake_per_md
            season_staked += stake_per_md
            total_parlays += 1
            
            print(f"MD {md}: {len(md_picks)} Picks | Parlay Odds: {md_odds_accumulator:.2f}")
            for p in md_picks:
                res = "✅" if p['hit'] else "❌"
                print(f"  {res} {p['match']} (1X @ {p['odds']})")
                
            if all_hits:
                winnings = stake_per_md * md_odds_accumulator
                season_returned += winnings
                total_profit += (winnings - stake_per_md)
                parlays_won += 1
                print(f"  >>> PARLAY WON: +₦{(winnings - stake_per_md):.2f}\n")
            else:
                total_profit -= stake_per_md
                print(f"  >>> PARLAY LOST: -₦{stake_per_md:.2f}\n")
                
        # Update points
        for m in season_matches:
            if m['match_day'] == md:
                hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
                h, a = m['home_team'], m['away_team']
                if hg > ag: team_pts[h] += 3
                elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
                else: team_pts[a] += 3
                
    s_profit = season_returned - season_staked
    print(f"--- SEASON {s_idx + 1} SUMMARY ---")
    print(f"Staked: ₦{season_staked:.2f} | Returned: ₦{season_returned:.2f} | Profit: ₦{s_profit:+.2f}\n")

print("=== FINAL 2-SEASON RESULTS ===")
print(f"Total Parlays Placed: {total_parlays}")
print(f"Parlays Won: {parlays_won} ({(parlays_won/total_parlays)*100 if total_parlays>0 else 0:.1f}%)")
print(f"Total Amount Staked: ₦{total_staked:.2f}")
print(f"Total Net Profit: ₦{total_profit:+.2f}")
if total_staked > 0:
    print(f"Overall ROI: {(total_profit/total_staked)*100:.1f}%")
