#!/usr/bin/env python3
"""
Torin — Pattern Recognition Analysis v3 (final)
"""
import json, re, sqlite3, os, sys
from collections import defaultdict, Counter
from datetime import datetime

DATA_DIR = "/home/faith/Documents/Projects/vfl-data"
EXTRACTED_DIR = f"{DATA_DIR}/extracted"
DB_PATH = f"{DATA_DIR}/databases/history.db"

def parse_betdata_files():
    """Extract rank data, odds from betdata JSON responses"""
    betdata_files = [
        "responsesSat27betdata.txt", "responsesSat27betdata3.txt", 
        "responsesSat27betdata4.txt", "responsesSat27betdata5.txt",
        "responsesSat27betdata6.txt", "responsesSat27.txt",
        "responsesundaydata1.txt",
    ]
    matches_data = []
    
    for fname in betdata_files:
        fpath = os.path.join(EXTRACTED_DIR, fname)
        if not os.path.exists(fpath):
            continue
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        sections = re.split(r'===== MATCH #\d+ =====', content)
        for section in sections:
            if 'bizCode' not in section:
                continue
            
            # Extract URL info
            season = None
            matchday = None
            url_match = re.search(r'seasonId=([^&\s]+)', section)
            if url_match:
                import urllib.parse
                season = urllib.parse.unquote(url_match.group(1))
            day_match = re.search(r'matchDay=(\d+)', section)
            if day_match:
                matchday = int(day_match.group(1))
            
            # Find JSON 
            json_start = section.find('{\n  "bizCode"')
            if json_start == -1:
                json_start = section.find('{"bizCode"')
            if json_start == -1:
                continue
            
            json_text = section[json_start:]
            depth, end = 0, 0
            in_str, esc = False, False
            for i, ch in enumerate(json_text):
                if esc: esc = False; continue
                if ch == '\\' and in_str: esc = True; continue
                if ch == '"' and not esc: in_str = not in_str; continue
                if in_str: continue
                if ch == '{': depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0: end = i+1; break
            
            try:
                data = json.loads(json_text[:end])
            except:
                continue
            
            events = data.get('data', {}).get('events', [])
            for ev in events:
                match_info = {
                    'season': season, 'matchday': matchday,
                    'homeTeam': ev.get('homeTeam'), 'awayTeam': ev.get('awayTeam'),
                    'homeRank': ev.get('homeRank'), 'awayRank': ev.get('awayRank'),
                    'homeRankChange': ev.get('homeRankChange'), 'awayRankChange': ev.get('awayRankChange'),
                    'isTopTeam': ev.get('isTopTeam'), 'source_file': fname,
                }
                for market in ev.get('markets', []):
                    if market.get('name') == '1x2':
                        for outcome in market.get('outcomes', []):
                            desc = outcome.get('description', '')
                            odds = outcome.get('odds')
                            if desc == 'Home': match_info['odds_h'] = odds
                            elif desc == 'Draw': match_info['odds_d'] = odds
                            elif desc == 'Away': match_info['odds_a'] = odds
                        break
                matches_data.append(match_info)
    
    return matches_data

def query_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""SELECT id, season, day, home, away, outcome, h, a, total, gg, o25,
                   half_time, first_goal, oh, od, oa FROM matches 
                   WHERE outcome IN ('HOME','AWAY','DRAW') ORDER BY season, day""")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def explore_ht_lead_ft_outcome(matches):
    """Explore 1: Half-time lead → Full-time outcome"""
    results = {"explore": "Half-time Lead → Full-time Outcome"}
    print("\n=== EXPLORE 1: Half-time Lead → Full-time Outcome ===")
    
    ht_gd = defaultdict(list)
    for m in matches:
        ht = m.get('half_time')
        if not ht or ht in ('', '--'): continue
        parts = ht.split(':')
        if len(parts) != 2: continue
        try:
            gd = int(parts[0]) - int(parts[1])
        except: continue
        ht_gd[gd].append(m)
    
    table = {}
    print(f"{'GD':>4} | {'Total':>6} | {'Home%':>7} | {'Draw%':>7} | {'Away%':>7}")
    for gd in sorted(ht_gd.keys()):
        g = ht_gd[gd]; n = len(g)
        h = sum(1 for m in g if m['outcome']=='HOME')/n*100
        d = sum(1 for m in g if m['outcome']=='DRAW')/n*100
        a = sum(1 for m in g if m['outcome']=='AWAY')/n*100
        table[gd] = {'n': n, 'home%': round(h,1), 'draw%': round(d,1), 'away%': round(a,1)}
        print(f"{gd:>4} | {n:>6} | {h:>6.1f}% | {d:>6.1f}% | {a:>6.1f}%")
    
    insights = {}
    
    # 1-goal vs 2-goal certainty jump
    for side, gd1, gd2, label in [('home', 1, 2, 'Home'), ('away', -1, -2, 'Away')]:
        if gd1 in table and gd2 in table:
            v1 = table[gd1][f'{side}%']
            v2 = table[gd2][f'{side}%']
            jump = round(v2 - v1, 1)
            msg = f"{label} {abs(gd1)}-goal HT lead → {label} wins {v1}%. {label} {abs(gd2)}-goal lead → {v2}%. Certainty jump: +{jump}pp"
            print(f">>> {msg}")
            insights[f'{side}_certainty_jump'] = {'one_goal': v1, 'two_goal': v2, 'jump_pp': jump, 'detail': msg}
    
    # 0-0 at HT
    if 0 in table:
        t = table[0]
        msg = f"0-0 at HT: Draw MOST likely ({t['draw%']}%) — higher than home ({t['home%']}%) or away ({t['away%']}%)"
        print(f">>> {msg}")
        insights['ht_0_0_draw_tendency'] = {**t, 'detail': msg}
    
    # 1-1 at HT
    ht_11 = [m for m in matches if m.get('half_time') == '1:1']
    if ht_11:
        n = len(ht_11)
        h = sum(1 for m in ht_11 if m['outcome']=='HOME')/n*100
        a = sum(1 for m in ht_11 if m['outcome']=='AWAY')/n*100
        d = sum(1 for m in ht_11 if m['outcome']=='DRAW')/n*100
        msg = f"1-1 at HT: Home {h:.1f}%, Draw {d:.1f}%, Away {a:.1f}%"
        print(f">>> {msg}")
        insights['ht_1_1'] = {'home%': round(h,1), 'draw%': round(d,1), 'away%': round(a,1), 'detail': msg}
    
    results['table'] = table
    results['insights'] = insights
    return results

def explore_first_goal(matches, betdata):
    """Explore 2: First goal → match story"""
    results = {"explore": "First Goal → Match Story"}
    print("\n\n=== EXPLORE 2: First Goal = Match Story ===")
    
    fg_data = {'Home': [], 'Away': []}
    for m in matches:
        fg = m.get('first_goal')
        if fg in ('Home', 'Away'): fg_data[fg].append(m)
    
    insights = {}
    print(f"\n--- First Goal → Final Outcome ---")
    for fg, group in [('Home', fg_data['Home']), ('Away', fg_data['Away'])]:
        n = len(group)
        h = sum(1 for m in group if m['outcome']=='HOME')/n*100
        a = sum(1 for m in group if m['outcome']=='AWAY')/n*100
        d = sum(1 for m in group if m['outcome']=='DRAW')/n*100
        wr = h if fg == 'Home' else a
        print(f"  {fg:>4} scores first: n={n:>6} | Home: {h:>5.1f}% | Draw: {d:>5.1f}% | Away: {a:>5.1f}%")
        insights[f'{fg.lower()}_first'] = {'n': n, 'home%': round(h,1), 'draw%': round(d,1), 'away%': round(a,1)}
    
    first_wins = (sum(1 for m in fg_data['Home'] if m['outcome']=='HOME') + 
                  sum(1 for m in fg_data['Away'] if m['outcome']=='AWAY'))
    first_total = len(fg_data['Home']) + len(fg_data['Away'])
    first_wr = first_wins/first_total*100
    msg = f"First scorer wins {first_wr:.1f}% (n={first_total})"
    print(f">>> {msg}")
    insights['first_scorer_wins_pct'] = round(first_wr,1)
    insights['first_scorer_wins_detail'] = msg
    
    # Home scores first but loses
    hfl = [m for m in fg_data['Home'] if m['outcome']=='AWAY']
    ht_cnt = Counter()
    for m in hfl:
        ht = m.get('half_time','N/A')
        ht_cnt[ht] += 1
    print(f">>> Home scores first but LOSES: {len(hfl)} ({len(hfl)/len(fg_data['Home'])*100:.1f}%)")
    print(f"  Top HT: {ht_cnt.most_common(5)}")
    insights['home_first_then_lose'] = {
        'n': len(hfl), 'pct': round(len(hfl)/len(fg_data['Home'])*100,1),
        'common_ht': [f"{k}:{v}" for k,v in ht_cnt.most_common(5)]
    }
    
    # Cross-reference with rank data
    import urllib.parse
    db_index = {}
    for m in matches:
        db_index[(m['season'], m['day'], m['home'].lower(), m['away'].lower())] = m
    
    matched = []
    for bd in betdata:
        season = bd.get('season')
        day = bd.get('matchday')
        home = (bd.get('homeTeam') or '').lower()
        away = (bd.get('awayTeam') or '').lower()
        if not all([season, day, home, away]): continue
        key = (season, day, home, away)
        if key in db_index:
            matched.append({**bd, 'outcome': db_index[key]['outcome'], 'first_goal': db_index[key]['first_goal']})
    
    if matched:
        print(f"\n--- First Goal by Tier (rank-based) (n={len(matched)} matched) ---")
        tier_groups = defaultdict(lambda: {'fg_home': 0, 'fg_away': 0, 'total': 0})
        for m in matched:
            hr = m.get('homeRank')
            ar = m.get('awayRank')
            if hr is None or ar is None: continue
            rd = ar - hr  # positive = home favored
            
            if rd >= 6: tier = 'Home heavy favorite (rd≥6)'
            elif rd >= 2: tier = 'Home slight favorite (rd2-5)'
            elif rd <= -6: tier = 'Home heavy underdog (rd≤-6)'
            elif rd <= -2: tier = 'Home slight underdog (rd-2--5)'
            else: tier = 'Even matchup (rd±1)'
            
            fg = m.get('first_goal')
            if fg == 'Home': tier_groups[tier]['fg_home'] += 1
            elif fg == 'Away': tier_groups[tier]['fg_away'] += 1
            tier_groups[tier]['total'] += 1
        
        for tier in ['Home heavy favorite (rd≥6)', 'Home slight favorite (rd2-5)', 
                      'Even matchup (rd±1)', 'Home slight underdog (rd-2--5)', 
                      'Home heavy underdog (rd≤-6)']:
            d = tier_groups[tier]
            if d['total'] < 10: continue
            hf_pct = d['fg_home']/d['total']*100
            print(f"  {tier:<35}: n={d['total']:>4} | Home-first: {hf_pct:>5.1f}% | Away-first: {100-hf_pct:>5.1f}%")
            
            # Win rate when that side scores first in this tier
            tier_matches = [m for m in matched if 
                          (m.get('homeRank') is not None and m.get('awayRank') is not None)]
            for m in tier_matches:
                hr = m.get('homeRank'); ar = m.get('awayRank')
                if ar-hr >= 6: m_tier = 'Home heavy favorite (rd≥6)'
                elif ar-hr >= 2: m_tier = 'Home slight favorite (rd2-5)'
                elif ar-hr <= -6: m_tier = 'Home heavy underdog (rd≤-6)'
                elif ar-hr <= -2: m_tier = 'Home slight underdog (rd-2--5)'
                else: m_tier = 'Even matchup (rd±1)'
                if m_tier != tier: continue
                
                fg = m.get('first_goal')
                if fg == 'Home' and m['outcome'] == 'HOME':
                    d['home_fg_wins'] = d.get('home_fg_wins', 0) + 1
                if fg == 'Away' and m['outcome'] == 'AWAY':
                    d['away_fg_wins'] = d.get('away_fg_wins', 0) + 1
            
            if d.get('home_fg_wins') and tier_groups[tier]['fg_home'] > 0:
                wr = d['home_fg_wins']/max(1, tier_groups[tier]['fg_home'])*100
                print(f"    → Home-first→Home-win: {wr:.1f}%")
            if d.get('away_fg_wins') and tier_groups[tier]['fg_away'] > 0:
                wr = d['away_fg_wins']/max(1, tier_groups[tier]['fg_away'])*100
                print(f"    → Away-first→Away-win: {wr:.1f}%")
    
    results['insights'] = insights
    return results

def explore_rank_changes(betdata, db_matches):
    """Explore 3: Team rank changes"""
    results = {"explore": "Team Rank Changes & Value Bets"}
    print("\n\n=== EXPLORE 3: Team Rank Changes ===")
    
    # Build DB index
    db_index = {}
    for m in db_matches:
        db_index[(m['season'], m['day'], m['home'].lower(), m['away'].lower())] = m
    
    matched_results = []
    for bd in betdata:
        season = bd.get('season')
        day = bd.get('matchday')
        home = (bd.get('homeTeam') or '').lower()
        away = (bd.get('awayTeam') or '').lower()
        if not all([season, day, home, away]): continue
        key = (season, day, home, away)
        if key in db_index:
            matched_results.append({**bd, 'outcome': db_index[key]['outcome']})
    
    print(f"Matched {len(matched_results)} entries")
    insights = {'matched': len(matched_results)}
    
    if len(matched_results) < 50:
        print("Not enough data")
        results['insights'] = insights
        return results
    
    # Helper
    def pct(g, cond): return sum(1 for m in g if m['outcome']==cond)/len(g)*100 if g else 0
    
    for side, side_label in [('home', 'Home'), ('away', 'Away')]:
        print(f"\n--- {side_label} Rank Change → Outcome ---")
        rc_data = {}
        for chg in ['UP', 'DOWN', 'SAME']:
            group = [m for m in matched_results if m.get(f'{side}RankChange') == chg]
            if not group: continue
            w = pct(group, side_label.upper())
            d = pct(group, 'DRAW')
            l = pct(group, 'AWAY' if side=='home' else 'HOME')
            print(f"  {side_label} Rank {chg:>4}: n={len(group):>5} | Win: {w:>5.1f}% | Draw: {d:>5.1f}% | Loss: {l:>5.1f}%")
            rc_data[chg] = {'n': len(group), 'win%': round(w,1), 'draw%': round(d,1), 'loss%': round(l,1)}
        insights[f'{side}_rank_change'] = rc_data
    
    # Top teams (rank 1-5)
    print(f"\n--- Top Teams (Rank 1-5) ---")
    top_data = {}
    for side in ['home', 'away']:
        sd = {}
        for chg in ['UP', 'DOWN', 'SAME']:
            group = [m for m in matched_results if m.get(f'{side}RankChange')==chg 
                    and m.get(f'{side}Rank') is not None and m[f'{side}Rank'] <= 5]
            if not group: continue
            wr = pct(group, side.upper())
            print(f"  {side.title()} Top5 {chg:>4}: n={len(group):>4} | Win: {wr:>5.1f}%")
            sd[chg] = {'n': len(group), 'win%': round(wr,1)}
        top_data[side] = sd
    
    # Also check: what's the baseline win rate for top 5 teams regardless of rank change?
    for side, label in [('home', 'Home'), ('away', 'Away')]:
        group = [m for m in matched_results if m.get(f'{side}Rank') is not None and m[f'{side}Rank'] <= 5]
        if group:
            wr = pct(group, label.upper())
            print(f"  {label} Top5 baseline win rate: {wr:.1f}% (n={len(group)})")
            top_data[f'{side}_baseline'] = {'n': len(group), 'win%': round(wr,1)}
    
    insights['top_teams'] = top_data
    
    # Low teams (rank 15+) 
    print(f"\n--- Low Teams (Rank 15+) ---")
    low_data = {}
    for side in ['home', 'away']:
        sd = {}
        for chg in ['UP', 'DOWN', 'SAME']:
            group = [m for m in matched_results if m.get(f'{side}RankChange')==chg 
                    and m.get(f'{side}Rank') is not None and m[f'{side}Rank'] >= 15]
            if not group: continue
            wr = pct(group, side.upper())
            dr = pct(group, 'DRAW')
            pts = (wr*3 + dr*1)/100
            print(f"  {side.title()} Low {chg:>4}: n={len(group):>4} | Win: {wr:>5.1f}% | Draw: {dr:>5.1f}% | PtsExp: {pts:.2f}")
            sd[chg] = {'n': len(group), 'win%': round(wr,1), 'draw%': round(dr,1), 'pts_expect': round(pts,2)}
        low_data[side] = sd
    
    # Baseline for low teams
    for side, label in [('home', 'Home'), ('away', 'Away')]:
        group = [m for m in matched_results if m.get(f'{side}Rank') is not None and m[f'{side}Rank'] >= 15]
        if group:
            wr = pct(group, label.upper())
            dr = pct(group, 'DRAW')
            print(f"  {label} Low (15+) baseline: Win {wr:.1f}%, Draw {dr:.1f}%  (n={len(group)})")
            low_data[f'{side}_baseline'] = {'n': len(group), 'win%': round(wr,1), 'draw%': round(dr,1)}
    
    insights['low_teams'] = low_data
    
    # Value bets
    print(f"\n--- Value Bet Analysis ---")
    value_bets = []
    for m in matched_results:
        try:
            oh = float(m.get('odds_h', 0))
            oa = float(m.get('odds_a', 0))
            od = float(m.get('odds_d', 0))
        except: continue
        hr = m.get('homeRank'); ar = m.get('awayRank')
        hrc = m.get('homeRankChange'); arc = m.get('awayRankChange')
        if hr is None or ar is None: continue
        
        if hr >= 15 and hrc == 'UP':
            imp = round(1/oh*100, 1)
            value_bets.append({'type': 'home_low_up', 'team': m['homeTeam'], 'odds': oh, 'implied%': imp, 'outcome': m['outcome']})
        if ar >= 15 and arc == 'UP':
            imp = round(1/oa*100, 1)
            value_bets.append({'type': 'away_low_up', 'team': m['awayTeam'], 'odds': oa, 'implied%': imp, 'outcome': m['outcome']})
    
    if value_bets:
        vb_won = sum(1 for vb in value_bets if 
                    (vb['type']=='home_low_up' and vb['outcome']=='HOME') or
                    (vb['type']=='away_low_up' and vb['outcome']=='AWAY'))
        print(f"  Low-rank+UP bets: {vb_won}/{len(value_bets)} won ({vb_won/len(value_bets)*100:.1f}%)")
        insights['value_bets'] = {'total': len(value_bets), 'won': vb_won, 'win_rate': round(vb_won/len(value_bets)*100,1)}
        for vt in ['home_low_up', 'away_low_up']:
            subset = [v for v in value_bets if v['type']==vt]
            if subset:
                sw = sum(1 for v in subset if (v['type']=='home_low_up' and v['outcome']=='HOME') or (v['type']=='away_low_up' and v['outcome']=='AWAY'))
                print(f"  {vt}: {sw}/{len(subset)} ({sw/len(subset)*100:.1f}%)")
    else:
        print("  No value bet candidates")
    
    # Also check: low teams with SAME rank change
    print(f"\n--- Side finding: Top teams UP vs Low teams UP differentials ---")
    if 'home' in top_data and 'UP' in top_data['home'] and 'home' in low_data and 'UP' in low_data['home']:
        tw = top_data['home']['UP']['win%']
        lw = low_data['home']['UP']['win%']
        print(f"  Home Top5+UP: {tw}% vs Home Low+UP: {lw}% (Δ = {tw-lw}pp)")
        insights['home_up_differential'] = {'top_win%': tw, 'low_win%': lw, 'delta': round(tw-lw,1)}
    
    results['insights'] = insights
    return results

def explore_streaks(matches):
    """Explore 4: Consecutive match patterns"""
    results = {"explore": "Consecutive Match Patterns & Streaks"}
    print("\n\n=== EXPLORE 4: Consecutive Match Patterns & Streaks ===")
    
    # Build team sequences
    from collections import defaultdict, Counter
    ms_by_season = defaultdict(list)
    for m in matches:
        ms_by_season[m['season']].append(m)
    
    team_seq = defaultdict(list)
    for season, ms in ms_by_season.items():
        ms.sort(key=lambda x: x['day'])
        tg = defaultdict(list)
        for m in ms:
            tg[(season, m['home'])].append({'outcome': m['outcome'], 'side': 'home', 'gf': m['h'], 'ga': m['a']})
            tg[(season, m['away'])].append({'outcome': m['outcome'], 'side': 'away', 'gf': m['a'], 'ga': m['h']})
        for k, games in tg.items():
            team_seq[k].extend(games)
    
    print(f"Tracking {len(team_seq)} team-seasons")
    
    def find_streak(seq, pattern, lookahead):
        """Count outcomes after a pattern of consecutive results"""
        results = Counter()
        for i in range(len(seq) - len(pattern)):
            if all(seq[i+j]['outcome'] == pattern[j] for j in range(len(pattern))):
                if i+len(pattern) < len(seq):
                    results[seq[i+len(pattern)]['outcome']] += 1
        return results
    
    insights = {}
    
    patterns = [
        (['HOME','HOME','HOME'], "3 wins in a row"),
        (['AWAY','AWAY','AWAY'], "3 away wins in a row"),
        (['DRAW','DRAW','DRAW'], "3 draws in a row"),
        (['DRAW','DRAW'], "2 draws in a row"),
    ]
    
    for pattern, label in patterns:
        for key, games in team_seq.items():
            pass  # need to flatten
        all_outcomes = []
        for key, games in team_seq.items():
            all_outcomes.extend([g['outcome'] for g in games])
        
        cnts = find_streak(list(zip(*[(g['outcome'],) for g in team_seq[next(iter(team_seq))]])) if False else [], pattern, 1)
        # Re-do properly
        break
    
    # Simpler approach: iterate team_seqs
    streak_data = {}
    for pat, label in [(['HOME','HOME','HOME'], '3_home_wins'), (['AWAY','AWAY','AWAY'], '3_away_wins'),
                       (['DRAW','DRAW','DRAW'], '3_draws'), (['DRAW','DRAW'], '2_draws')]:
        cnts = Counter()
        for key, games in team_seq.items():
            outcomes = [g['outcome'] for g in games]
            for i in range(len(outcomes) - len(pat)):
                if all(outcomes[i+j] == pat[j] for j in range(len(pat))):
                    if i+len(pat) < len(outcomes):
                        cnts[outcomes[i+len(pat)]] += 1
        if cnts:
            total = sum(cnts.values())
            print(f"\n--- After {label.replace('_', ' ')} → Next match (n={total}) ---")
            for o in ['HOME','DRAW','AWAY']:
                c = cnts.get(o, 0)
                if c:
                    print(f"  {o:>5}: {c:>4} ({c/total*100:.1f}%)")
            streak_data[label] = {o.lower(): {'n': c, 'pct': round(c/total*100,1) if total else 0} for o,c in cnts.items()}
    
    insights['streaks'] = streak_data
    
    # Bounce back after big results
    for label, margin, condition in [('big_loss', -3, lambda gf, ga: ga-gf >= 3),
                                      ('big_win', 3, lambda gf, ga: gf-ga >= 3)]:
        bounce = Counter()
        for key, games in team_seq.items():
            for i, g in enumerate(games):
                gf = g.get('gf'); ga = g.get('ga')
                if gf is not None and ga is not None and condition(gf, ga):
                    if i+1 < len(games):
                        bounce[games[i+1]['outcome']] += 1
        if bounce:
            total = sum(bounce.values())
            print(f"\n--- After {label.replace('_', ' ')} (3+ goal) → (n={total}) ---")
            for o in ['HOME','DRAW','AWAY']:
                c = bounce.get(o, 0)
                if c:
                    print(f"  Next: {o:>5} → {c:>4} ({c/total*100:.1f}%)")
            insights[label] = {o.lower(): {'n': c, 'pct': round(c/total*100,1)} for o,c in bounce.items()}
    
    results['insights'] = insights
    return results

def explore_seasonal_position(matches):
    """Explore 5: Seasonal position"""
    results = {"explore": "Seasonal Position Effects"}
    print("\n\n=== EXPLORE 5: Seasonal Position ===")
    
    season_days = defaultdict(set)
    for m in matches:
        season_days[m['season']].add(m['day'])
    season_max = {s: max(days) for s, days in season_days.items()}
    
    phase_data = defaultdict(lambda: {'HOME':0,'AWAY':0,'DRAW':0,'total':0,'goals':[],'o25':0})
    
    for m in matches:
        mx = season_max.get(m['season'])
        if not mx or mx <= 0: continue
        pr = m['day'] / mx
        if pr <= 0.25: lbl = 'Early (0-25%)'
        elif pr <= 0.50: lbl = 'Mid-Early (25-50%)'
        elif pr <= 0.75: lbl = 'Mid-Late (50-75%)'
        else: lbl = 'Late (75-100%)'
        
        if m['outcome'] in ('HOME','AWAY','DRAW'):
            phase_data[lbl][m['outcome']] += 1
            phase_data[lbl]['total'] += 1
        if m.get('total') is not None:
            phase_data[lbl]['goals'].append(m['total'])
            if m.get('o25') == 1:
                phase_data[lbl]['o25'] += 1
    
    print(f"\n--- Outcome by Season Phase ---")
    print(f"{'Phase':<20} | {'Total':>6} | {'Home%':>7} | {'Draw%':>7} | {'Away%':>7} | {'AvgGls':>7} | {'O25%':>7}")
    phase_ins = {}
    for lbl in ['Early (0-25%)', 'Mid-Early (25-50%)', 'Mid-Late (50-75%)', 'Late (75-100%)']:
        d = phase_data[lbl]
        if d['total'] == 0: continue
        hp = d['HOME']/d['total']*100
        dp = d['DRAW']/d['total']*100
        ap = d['AWAY']/d['total']*100
        ag = sum(d['goals'])/len(d['goals']) if d['goals'] else 0
        o25p = d['o25']/d['total']*100
        print(f"{lbl:<20} | {d['total']:>6} | {hp:>6.1f}% | {dp:>6.1f}% | {ap:>6.1f}% | {ag:>6.2f} | {o25p:>6.1f}%")
        phase_ins[lbl] = {'n': d['total'], 'home%': round(hp,1), 'draw%': round(dp,1), 'away%': round(ap,1),
                          'avg_goals': round(ag,2), 'o25%': round(o25p,1)}
    insights = {'phase_outcomes': phase_ins}
    
    # Upset analysis
    odds_matches = [m for m in matches if m.get('oh') and m.get('oa') and str(m['oh']).strip() and str(m['oa']).strip()]
    if odds_matches:
        print(f"\n--- Upsets by Phase (odds-based) ---")
        p_upsets = defaultdict(lambda: {'fav':0,'upset':0,'draw':0,'total':0})
        for m in odds_matches:
            mx = season_max.get(m['season'])
            if not mx or mx <= 0: continue
            pr = m['day'] / mx
            if pr <= 0.25: lbl = 'Early'
            elif pr <= 0.50: lbl = 'Mid-Early'
            elif pr <= 0.75: lbl = 'Mid-Late'
            else: lbl = 'Late'
            try:
                oh = float(m['oh']); oa = float(m['oa'])
            except: continue
            p_upsets[lbl]['total'] += 1
            if m['outcome'] == 'DRAW':
                p_upsets[lbl]['draw'] += 1
            elif (oh < oa and m['outcome']=='HOME') or (oa < oh and m['outcome']=='AWAY'):
                p_upsets[lbl]['fav'] += 1
            else:
                p_upsets[lbl]['upset'] += 1
        
        for lbl in ['Early', 'Mid-Early', 'Mid-Late', 'Late']:
            d = p_upsets[lbl]
            if d['total'] == 0: continue
            print(f"  {lbl:<15}: n={d['total']:>5} | Fav: {d['fav']/d['total']*100:>5.1f}% | Upset: {d['upset']/d['total']*100:>5.1f}% | Draw: {d['draw']/d['total']*100:>5.1f}%")
        
        insights['upsets_by_phase'] = {k: {
            'n': v['total'], 'fav%': round(v['fav']/v['total']*100,1),
            'upset%': round(v['upset']/v['total']*100,1), 'draw%': round(v['draw']/v['total']*100,1)
        } for k,v in p_upsets.items()}
    
    results['insights'] = insights
    return results

# ════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("TORIN — Pattern Recognition Analysis v3")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)
    
    print("\nLoading database...")
    db_matches = query_db()
    print(f"Loaded {len(db_matches)} matches")
    
    print("\nParsing betdata files...")
    betdata = parse_betdata_files()
    print(f"Parsed {len(betdata)} entries")
    
    all_results = {
        'meta': {'timestamp': datetime.now().isoformat(), 'total_db_matches': len(db_matches), 'total_betdata': len(betdata)},
        'explorations': {}
    }
    
    all_results['explorations']['explore_1_ht_lead'] = explore_ht_lead_ft_outcome(db_matches)
    all_results['explorations']['explore_2_first_goal'] = explore_first_goal(db_matches, betdata)
    all_results['explorations']['explore_3_rank_changes'] = explore_rank_changes(betdata, db_matches)
    all_results['explorations']['explore_4_streaks'] = explore_streaks(db_matches)
    all_results['explorations']['explore_5_seasonal'] = explore_seasonal_position(db_matches)
    
    print("\n\n=== ANALYSIS COMPLETE ===")
    
    os.makedirs(f"{DATA_DIR}/analysis", exist_ok=True)
    outpath = f"{DATA_DIR}/analysis/torin-patterns.json"
    with open(outpath, 'w') as f:
        json.dump(all_results, f, default=str, indent=2)
    print(f"Saved to {outpath}")

if __name__ == '__main__':
    main()
