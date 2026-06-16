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
cursor = conn.cursor()

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])
season_groups = {}
for m in matches:
    s = m['season']
    if s not in season_groups:
        season_groups[s] = []
    season_groups[s].append(m)

# Extract the last 3 seasons (2 fully completed + the ongoing one)
last_3_season_names = list(season_groups.keys())[-3:]
base_seasons = [season_groups[s] for s in last_3_season_names]

season_outcomes_list = []

for s_idx, season_matches in enumerate(base_seasons):
    team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
    s_outs = []
    
    for md in range(1, 31):
        ranks = {t: i+1 for i, (t, _) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))}
        md_odds = 1.0
        all_hits = True
        has_bet = False
        
        for m in season_matches:
            if m['match_day'] != md: continue
            
            h, a = m['home_team'], m['away_team']
            s_name = m['season']
            
            h_t = 'Start' if md==1 else get_tier(ranks[h])
            a_t = 'Start' if md==1 else get_tier(ranks[a])
            chunk = get_md_chunk(md)
            
            is_lock = False
            if chunk == 'MD 11-15' and h_t == 'T4(13-16)' and a_t == 'T3(9-12)': is_lock = True
            elif chunk == 'MD 21-25' and h_t == 'T2(5-8)' and a_t == 'T3(9-12)': is_lock = True
            elif chunk == 'MD 26-30' and h_t == 'T1(1-4)' and a_t == 'T3(9-12)': is_lock = True
            elif chunk == 'MD 6-10' and h_t == 'T2(5-8)' and a_t == 'T4(13-16)': is_lock = True
            elif chunk == 'MD 16-20' and h_t == 'T1(1-4)' and a_t == 'T3(9-12)': is_lock = True
            elif chunk == 'MD 16-20' and h_t == 'T1(1-4)' and a_t == 'T2(5-8)': is_lock = True
            
            if is_lock:
                has_bet = True
                hg, ag = m.get('home_goals',0), m.get('away_goals',0)
                win = hg >= ag
                if not win: all_hits = False
                
                cursor.execute('''
                    SELECT d.odds 
                    FROM event_details e
                    JOIN deep_markets d ON e.event_id = d.event_id
                    WHERE e.season_name = ? AND e.match_day = ? AND e.home_team = ? AND e.away_team = ?
                    AND d.market_name = 'Double Chance' AND d.selection_name = '1 X'
                    LIMIT 1
                ''', (s_name, md, h, a))
                res = cursor.fetchone()
                
                if res and res[0] is not None:
                    dc_odds = float(res[0])
                else:
                    o1 = float(m.get('odds', {}).get('home_win', 2.0))
                    ox = float(m.get('odds', {}).get('draw', 3.0))
                    dc_odds = 1.0 / ((1.0/o1) + (1.0/ox)) if o1>0 and ox>0 else 1.25
                
                md_odds *= dc_odds
        
        if has_bet:
            s_outs.append((all_hits, md_odds))
            
        for m in season_matches:
            if m['match_day'] == md:
                hg, ag = m.get('home_goals',0), m.get('away_goals',0)
                if hg > ag: team_pts[m['home_team']] += 3
                elif hg == ag: team_pts[m['home_team']] += 1; team_pts[m['away_team']] += 1
                else: team_pts[m['away_team']] += 3
    
    season_outcomes_list.append(s_outs)

def run_kelly(num_seasons):
    test_outcomes = []
    for i in range(num_seasons):
        test_outcomes.extend(season_outcomes_list[i % len(season_outcomes_list)])
        
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

print('=== 25% KELLY COMPOUNDING (Start: ₦3,000) ===')
print(f"Seasons Evaluated: {', '.join(last_3_season_names)}")
for n in [1, 3]:
    br, pk, mdd, pp, pw = run_kelly(n)
    print(f'\n--- PROGRESS OVER LAST {n} SEASONS ---')
    print(f'Parlays: {pp} | Won: {pw} ({(pw/pp)*100 if pp>0 else 0:.1f}%)')
    print(f'Current Bankroll: ₦{br:.2f}')
    print(f'Net Profit: +₦{(br - 3000):.2f}')
    print(f'Max Drawdown: {mdd:.1f}%')
