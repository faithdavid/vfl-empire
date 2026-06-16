import json
from collections import defaultdict

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])
seasons = [matches[i:i+240] for i in range(0, len(matches), 240) if len(matches[i:i+240]) == 240]

# Take the last 8 seasons
seasons_to_test = seasons[-8:]

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

total_parlays = 0
parlays_won = 0

flat_profit = 0.0
flat_staked = 0.0

# 25% Kelly logic
kelly_bankroll = 1000.0

print(f"=== TIER-ROUTING PARLAY TEST (Last {len(seasons_to_test)} Seasons) ===")

for s_idx, season_matches in enumerate(seasons_to_test):
    team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
    
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
                
                o1 = float(m.get('odds', {}).get('home_win', 2.0))
                ox = float(m.get('odds', {}).get('draw', 3.0))
                if o1 > 0 and ox > 0:
                    dc_odds = 1.0 / ((1.0/o1) + (1.0/ox))
                else:
                    dc_odds = 1.25
                
                md_picks.append({'hit': win_or_draw})
                md_odds_accumulator *= dc_odds
                if not win_or_draw:
                    all_hits = False
                    
        if len(md_picks) > 0:
            total_parlays += 1
            
            # 1. Flat Staking Math
            flat_staked += 50.0
            if all_hits:
                parlays_won += 1
                flat_profit += (50.0 * md_odds_accumulator) - 50.0
            else:
                flat_profit -= 50.0
                
            # 2. Kelly Math (25% Bankroll)
            k_stake = kelly_bankroll * 0.25
            if all_hits:
                kelly_bankroll += k_stake * (md_odds_accumulator - 1)
            else:
                kelly_bankroll -= k_stake
                
        # Update points
        for m in season_matches:
            if m['match_day'] == md:
                hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
                h, a = m['home_team'], m['away_team']
                if hg > ag: team_pts[h] += 3
                elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
                else: team_pts[a] += 3

print(f"Total Parlays Placed: {total_parlays}")
print(f"Parlays Won: {parlays_won} ({(parlays_won/total_parlays)*100 if total_parlays>0 else 0:.1f}%)")
print("\n--- 1. FLAT STAKING (₦50 / Matchday) ---")
print(f"Total Staked: ₦{flat_staked:.2f}")
print(f"Total Net Profit: ₦{flat_profit:+.2f}")

print("\n--- 2. 25% KELLY COMPOUNDING (Start: ₦1000) ---")
print(f"Final Bankroll: ₦{kelly_bankroll:.2f}")
print(f"Total Net Profit: ₦{(kelly_bankroll - 1000):+.2f}")
