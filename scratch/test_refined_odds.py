import sqlite3
import json

def get_tier(rank):
    if rank <= 4: return 'T1(1-4)'
    if rank <= 8: return 'T2(5-8)'
    if rank <= 12: return 'T3(9-12)'
    return 'T4(13-16)'

def get_md_chunk(md):
    if md <= 5: return 'MD 1-5'
    if md <= 10: return 'MD 6-10'
    if md <= 15: return 'MD 11-15'
    if md <= 20: return 'MD 16-20'
    if md <= 25: return 'MD 21-25'
    return 'MD 26-30'

conn = sqlite3.connect('/home/ubuntu/faith-workspace/vfl-complete-data/vfl_odds.db')
conn.execute("ATTACH DATABASE '/home/ubuntu/faith-workspace/vfl-complete-data/history.db' AS h_db")
cursor = conn.cursor()

# Get the last 20 fully completed seasons from history.db
cursor.execute("SELECT season FROM h_db.matches ORDER BY id DESC LIMIT 15000")
recent_seasons = [r[0] for r in cursor.fetchall()]
from collections import Counter
c = Counter(recent_seasons)

completed_seasons = []
for s in sorted(set(recent_seasons), reverse=True):
    if c[s] == 240:
        completed_seasons.append(s)
    if len(completed_seasons) == 20:
        break

# Reverse so they are chronological (oldest to newest)
completed_seasons = completed_seasons[::-1]

season_outcomes_list = []
route_stats = {}

for s_name in completed_seasons:
    cursor.execute("SELECT day, home, away, h, a FROM h_db.matches WHERE season = ? ORDER BY id ASC", (s_name,))
    matches = cursor.fetchall()
    
    team_pts = {t: 0 for t in set(m[1] for m in matches)}
    s_outs = []
    
    for md in range(1, 31):
        ranks = {t: i+1 for i, (t, _) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))}
        md_odds = 1.0
        all_hits = True
        has_bet = False
        
        for m in matches:
            if m[0] != md: continue
            
            h, a = m[1], m[2]
            hg, ag = m[3], m[4]
            if hg is None or ag is None: continue
            
            h_t = 'Start' if md==1 else get_tier(ranks[h])
            a_t = 'Start' if md==1 else get_tier(ranks[a])
            chunk = get_md_chunk(md)
            
            is_lock = False
            route_name = ""
            if chunk == 'MD 11-15' and h_t == 'T4(13-16)' and a_t == 'T3(9-12)': is_lock = True; route_name = "MD11-15 T4 v T3"
            elif chunk == 'MD 21-25' and h_t == 'T2(5-8)' and a_t == 'T3(9-12)': is_lock = True; route_name = "MD21-25 T2 v T3"
            elif chunk == 'MD 26-30' and h_t == 'T1(1-4)' and a_t == 'T3(9-12)': is_lock = True; route_name = "MD26-30 T1 v T3"
            elif chunk == 'MD 6-10' and h_t == 'T2(5-8)' and a_t == 'T4(13-16)': is_lock = True; route_name = "MD6-10 T2 v T4"
            elif chunk == 'MD 16-20' and h_t == 'T1(1-4)' and a_t == 'T3(9-12)': is_lock = True; route_name = "MD16-20 T1 v T3"
            elif chunk == 'MD 16-20' and h_t == 'T1(1-4)' and a_t == 'T2(5-8)': is_lock = True; route_name = "MD16-20 T1 v T2"
            
            if is_lock:
                has_bet = True
                win = hg >= ag
                if not win: all_hits = False
                
                if route_name not in route_stats:
                    route_stats[route_name] = {'hits': 0, 'total': 0}
                route_stats[route_name]['total'] += 1
                if win: route_stats[route_name]['hits'] += 1
                
                # Fetch exact real-world odds from our deep markets
                cursor.execute('''
                    SELECT d.odds 
                    FROM event_details e
                    JOIN deep_markets d ON e.event_id = d.event_id
                    WHERE e.season_name = ? AND e.match_day = ? AND e.home_team = ? AND e.away_team = ?
                    AND d.market_name = 'Double Chance' AND d.selection_name = '1 X'
                    LIMIT 1
                ''', (str(s_name), md, h, a))
                res = cursor.fetchone()
                
                if res and res[0] is not None:
                    dc_odds = float(res[0])
                else:
                    dc_odds = 1.25 # Fallback average for 1X
                
                md_odds *= dc_odds
        
        if has_bet:
            s_outs.append((all_hits, md_odds))
            
        for m in matches:
            if m[0] == md:
                h, a = m[1], m[2]
                hg, ag = m[3], m[4]
                if hg is None or ag is None: continue
                if hg > ag: team_pts[h] += 3
                elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
                else: team_pts[a] += 3
    
    season_outcomes_list.append(s_outs)


def run_kelly(num_seasons):
    test_outcomes = []
    # Take the LAST `num_seasons` from our chronological list
    for i in range(len(season_outcomes_list) - num_seasons, len(season_outcomes_list)):
        test_outcomes.extend(season_outcomes_list[i])
        
    bankroll = 3000.0
    peak = 3000.0
    max_drawdown = 0.0
    
    parlays_placed = len(test_outcomes)
    parlays_won = sum(1 for o in test_outcomes if o[0])
    
    for hit, odds in test_outcomes:
        stake = bankroll * 0.25
        if hit:
            bankroll += stake * (odds - 1)
        else:
            bankroll -= stake
            
        if bankroll > peak:
            peak = bankroll
        else:
            dd_percent = (peak - bankroll) / peak * 100
            if dd_percent > max_drawdown:
                max_drawdown = dd_percent

    return bankroll, peak, max_drawdown, parlays_placed, parlays_won

print('=== 25% KELLY COMPOUNDING (Start: ₦3,000) (REFINED RULES) ===')
for n in [1, 3, 9, 12, 15, 20]:
    if n > len(completed_seasons):
        break
    br, pk, mdd, pp, pw = run_kelly(n)
    print(f'\n--- LAST {n} COMPLETED SEASONS ---')
    print(f'Parlays: {pp} | Won: {pw} ({(pw/pp)*100 if pp>0 else 0:.1f}%)')
    print(f'Final Bankroll: ₦{br:,.2f}')
    print(f'Net Profit: +₦{(br - 3000):,.2f}')
    print(f'Max Drawdown: {mdd:.1f}%')

print('\n=== INDIVIDUAL ROUTE HIT RATES (OVER 20 SEASONS) ===')
for r, stats in route_stats.items():
    print(f"{r}: {(stats['hits']/stats['total'])*100:.1f}% ({stats['hits']}/{stats['total']})")
