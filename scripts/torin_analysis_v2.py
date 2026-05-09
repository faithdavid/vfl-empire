#!/usr/bin/env python3
"""
Torin — Pattern Recognition Analysis v2
Simpler, more robust JSON extraction from betdata files
"""
import json, re, sqlite3, os, sys
from collections import defaultdict, Counter
from datetime import datetime

DATA_DIR = "/home/faith/Documents/Projects/vfl-data"
EXTRACTED_DIR = f"{DATA_DIR}/extracted"
DB_PATH = f"{DATA_DIR}/databases/history.db"

# ────────────────────────────────────────────────────────────────
# 1. PARSE BETDATA FILES
# ────────────────────────────────────────────────────────────────
def parse_betdata_files():
    """Extract rank data, odds from betdata JSON responses"""
    betdata_files = [
        "responsesSat27betdata.txt",
        "responsesSat27betdata3.txt", 
        "responsesSat27betdata4.txt",
        "responsesSat27betdata5.txt",
        "responsesSat27betdata6.txt",
        "responsesSat27.txt",
        "responsesundaydata1.txt",
    ]
    
    matches_data = []
    
    for fname in betdata_files:
        fpath = os.path.join(EXTRACTED_DIR, fname)
        if not os.path.exists(fpath):
            continue
        print(f"Parsing {fname}...")
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # Split by match boundaries
        sections = re.split(r'===== MATCH #\d+ =====', content)
        
        for section in sections:
            if not section.strip():
                continue
            
            # Extract URL info
            season = None
            matchday = None
            url_match = re.search(r'seasonId=([^&\s]+)', section)
            if url_match:
                season = url_match.group(1)
            day_match = re.search(r'matchDay=(\d+)', section)
            if day_match:
                matchday = int(day_match.group(1))
            
            # Find JSON response - starts with { and is valid JSON
            # Look for lines that start with { and contain bizCode
            json_start = section.find('{\n  "bizCode"')
            if json_start == -1:
                json_start = section.find('{"bizCode"')
            if json_start == -1:
                continue
            
            # Find the closing brace (needle in haystack)
            # Count braces to find matching close
            json_text = section[json_start:]
            depth = 0
            json_end = 0
            in_string = False
            escape = False
            for i, ch in enumerate(json_text):
                if escape:
                    escape = False
                    continue
                if ch == '\\' and in_string:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        json_end = i + 1
                        break
            
            if json_end == 0:
                continue
            
            json_str = json_text[:json_end]
            
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as e:
                continue
            
            events = data.get('data', {}).get('events', [])
            for ev in events:
                match_info = {
                    'season': season,
                    'matchday': matchday,
                    'homeTeam': ev.get('homeTeam'),
                    'awayTeam': ev.get('awayTeam'),
                    'homeRank': ev.get('homeRank'),
                    'awayRank': ev.get('awayRank'),
                    'homeRankChange': ev.get('homeRankChange'),
                    'awayRankChange': ev.get('awayRankChange'),
                    'isTopTeam': ev.get('isTopTeam'),
                    'source_file': fname,
                }
                
                # Extract 1x2 odds
                for market in ev.get('markets', []):
                    if market.get('name') == '1x2':
                        for outcome in market.get('outcomes', []):
                            desc = outcome.get('description', '')
                            odds = outcome.get('odds')
                            if desc == 'Home':
                                match_info['odds_h'] = odds
                            elif desc == 'Draw':
                                match_info['odds_d'] = odds
                            elif desc == 'Away':
                                match_info['odds_a'] = odds
                        break
                
                matches_data.append(match_info)
    
    print(f"Parsed {len(matches_data)} match entries from betdata files")
    return matches_data


# ────────────────────────────────────────────────────────────────
# 2. QUERY DATABASE
# ────────────────────────────────────────────────────────────────
def query_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("""
        SELECT id, season, day, home, away, outcome, h, a, total, gg, o25,
               half_time, first_goal, oh, od, oa
        FROM matches 
        WHERE outcome IN ('HOME', 'AWAY', 'DRAW')
        ORDER BY season, day
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ────────────────────────────────────────────────────────────────
# 3. EXPLORE 1: Half-time lead → Full-time outcome
# ────────────────────────────────────────────────────────────────
def explore_ht_lead_ft_outcome(matches):
    results = {"explore": "Half-time Lead → Full-time Outcome"}
    print("\n=== EXPLORE 1: Half-time Lead → Full-time Outcome ===")
    
    # Parse HT scores
    ht_gd_groups = defaultdict(list)
    for m in matches:
        ht = m.get('half_time')
        if not ht or ht in ('', '--'):
            continue
        parts = ht.split(':')
        if len(parts) != 2:
            continue
        try:
            h_goals = int(parts[0])
            a_goals = int(parts[1])
        except ValueError:
            continue
        gd = h_goals - a_goals
        ht_gd_groups[gd].append(m)
    
    print(f"\n{'HT GD':>6} | {'Total':>6} | {'Home%':>7} | {'Draw%':>7} | {'Away%':>7}")
    ht_data = {}
    for gd in sorted(ht_gd_groups.keys()):
        group = ht_gd_groups[gd]
        n = len(group)
        h = sum(1 for m in group if m['outcome'] == 'HOME')
        d = sum(1 for m in group if m['outcome'] == 'DRAW')
        a = sum(1 for m in group if m['outcome'] == 'AWAY')
        hp = round(h/n*100, 1)
        dp = round(d/n*100, 1)
        ap = round(a/n*100, 1)
        print(f"{gd:>6} | {n:>6} | {hp:>6.1f}% | {dp:>6.1f}% | {ap:>6.1f}%")
        ht_data[gd] = {'total': n, 'home%': hp, 'draw%': dp, 'away%': ap}
    
    # Key insight calculations
    insights = {}
    
    # Certainty jump 1→2 goals (home)
    if 1 in ht_gd_groups and 2 in ht_gd_groups:
        h1 = ht_data[1]['home%']
        h2 = ht_data[2]['home%']
        jump = round(h2 - h1, 1)
        msg = f"1-goal HT lead → {h1}% home win. 2-goal HT lead → {h2}% home win. Certainty jump: +{jump}pp"
        print(f">>> {msg}")
        insights['home_certainty_jump_1_to_2'] = {"one_goal": h1, "two_goal": h2, "jump_pp": jump, "detail": msg}
    
    if -1 in ht_gd_groups and -2 in ht_gd_groups:
        a1 = ht_data[-1]['away%']
        a2 = ht_data[-2]['away%']
        jump = round(a2 - a1, 1)
        msg = f"1-goal away HT lead → {a1}% away win. 2-goal away HT lead → {a2}% away win. Certainty jump: +{jump}pp"
        print(f">>> {msg}")
        insights['away_certainty_jump_1_to_2'] = {"one_goal": a1, "two_goal": a2, "jump_pp": jump, "detail": msg}
    
    # 0-0 at HT
    if 0 in ht_gd_groups:
        g0 = ht_gd_groups[0]
        h0 = ht_data[0]['home%']
        d0 = ht_data[0]['draw%']
        a0 = ht_data[0]['away%']
        msg = f"0-0 at HT: Draw {d0}%, making it the MOST likely outcome (higher than home {h0}%)"
        print(f">>> {msg}")
        insights['ht_0_0_draw_tendency'] = {"total": len(g0), "draw%": d0, "home%": h0, "away%": a0, "detail": msg}
    
    # HT draw (any score)
    ht_draw = [m for gd, group in ht_gd_groups.items() if gd == 0 for m in group]
    if ht_draw:
        hd = ht_data[0]
        msg = f"HT draw → [{hd['home%']}% home win / {hd['draw%']}% full draw / {hd['away%']}% away win]"
        insights['ht_draw_outcome'] = hd
    
    # Interesting: 1-1 at HT
    ht_11 = [m for m in matches if m.get('half_time') == '1:1']
    if ht_11:
        n11 = len(ht_11)
        h11 = sum(1 for m in ht_11 if m['outcome'] == 'HOME')/n11*100
        a11 = sum(1 for m in ht_11 if m['outcome'] == 'AWAY')/n11*100
        d11 = sum(1 for m in ht_11 if m['outcome'] == 'DRAW')/n11*100
        msg = f"1-1 at HT: Home win {h11:.1f}%, Draw {d11:.1f}%, Away win {a11:.1f}%"
        print(f">>> {msg}")
        insights['ht_1_1'] = {"home%": round(h11,1), "draw%": round(d11,1), "away%": round(a11,1), "detail": msg}
    
    results['data'] = ht_data
    results['insights'] = insights
    return results


# ────────────────────────────────────────────────────────────────
# 4. EXPLORE 2: First goal = match story
# ────────────────────────────────────────────────────────────────
def explore_first_goal(matches, betdata):
    results = {"explore": "First Goal → Match Story"}
    print("\n\n=== EXPLORE 2: First Goal = Match Story ===")
    
    fg_data = {'Home': [], 'Away': []}
    for m in matches:
        fg = m.get('first_goal')
        if fg in ('Home', 'Away'):
            fg_data[fg].append(m)
    
    insights = {}
    print(f"\n--- First Goal → Final Outcome ---")
    for fg, group in [('Home', fg_data['Home']), ('Away', fg_data['Away'])]:
        n = len(group)
        h = sum(1 for m in group if m['outcome'] == 'HOME')
        d = sum(1 for m in group if m['outcome'] == 'DRAW')
        a = sum(1 for m in group if m['outcome'] == 'AWAY')
        msg = f"Team scoring first ({fg}) wins {max(h,a)/n*100:.1f}% of matches"
        print(f"  {fg:>4} scores first: n={n:>6} | Home: {h/n*100:>5.1f}% | Draw: {d/n*100:>5.1f}% | Away: {a/n*100:>5.1f}%  → {msg}")
        insights[f'{fg.lower()}_first'] = {
            'total': n, 'home%': round(h/n*100,1), 'draw%': round(d/n*100,1), 'away%': round(a/n*100,1),
            'detail': msg
        }
    
    # First scorer wins rate
    first_wins = (sum(1 for m in fg_data['Home'] if m['outcome'] == 'HOME') + 
                  sum(1 for m in fg_data['Away'] if m['outcome'] == 'AWAY'))
    first_total = len(fg_data['Home']) + len(fg_data['Away'])
    first_win_rate = first_wins / first_total * 100
    msg = f"Whoever scores first wins {first_win_rate:.1f}% of matches (n={first_total})"
    print(f">>> {msg}")
    insights['first_scorer_wins'] = {"rate": round(first_win_rate,1), "total": first_total, "detail": msg}
    
    # When home scores first but loses — how?
    home_first_losses = [m for m in fg_data['Home'] if m['outcome'] == 'AWAY']
    msg = f"Home scores first but still LOSES: {len(home_first_losses)} cases ({len(home_first_losses)/len(fg_data['Home'])*100:.1f}%)"
    print(f">>> {msg}")
    
    ht_losses = Counter()
    big_losses = Counter()
    for m in home_first_losses:
        ht = m.get('half_time', 'N/A')
        ht_losses[ht] += 1
        # What HT scores correlate with home losing after scoring first?
        if ht != 'N/A' and ':' in ht:
            parts = ht.split(':')
            try:
                h_g, a_g = int(parts[0]), int(parts[1])
                big_losses[a_g - h_g] += 1
            except ValueError:
                pass
    
    print(f"  Top HT scores for home-first-then-lose: {ht_losses.most_common(5)}")
    insights['home_first_then_lose'] = {
        "total": len(home_first_losses),
        "pct": round(len(home_first_losses)/len(fg_data['Home'])*100, 1),
        "common_ht_scores": [f"{k}:{v}" for k,v in ht_losses.most_common(5)]
    }
    
    # Cross-reference first goal with rank difference
    # Match betdata to results using team names
    matched = []
    for bd in betdata:
        home = bd.get('homeTeam')
        away = bd.get('awayTeam')
        season = bd.get('season')
        day = bd.get('matchday')
        if not all([home, away, season, day]):
            continue
        for m in matches:
            if m['season'] == season and m['day'] == day and m['home'] == home and m['away'] == away:
                matched.append({**bd, 'outcome': m['outcome'], 'first_goal': m['first_goal']})
                break
    
    if matched:
        print(f"\n--- First Goal by Rank Difference (n={len(matched)} matched) ---")
        # Tier: top teams (avg rank 1-6), mid (7-12), low (13-18)
        tier_matches = defaultdict(lambda: {'Home_first': [], 'Away_first': []})
        for m in matched:
            hr = m.get('homeRank')
            ar = m.get('awayRank')
            if hr is None or ar is None:
                continue
            rank_diff = ar - hr  # positive = home is better ranked (lower number)
            
            if rank_diff <= -6:
                tier = 'Home_heavy_underdog'
            elif rank_diff <= -2:
                tier = 'Home_slight_underdog'
            elif rank_diff >= 6:
                tier = 'Home_heavy_favorite'
            elif rank_diff >= 2:
                tier = 'Home_slight_favorite'
            else:
                tier = 'Even_matchup'
            
            fg = m.get('first_goal')
            if fg == 'Home':
                tier_matches[tier]['Home_first'].append(m)
            elif fg == 'Away':
                tier_matches[tier]['Away_first'].append(m)
        
        for tier in ['Home_heavy_underdog', 'Home_slight_underdog', 'Even_matchup', 'Home_slight_favorite', 'Home_heavy_favorite']:
            data = tier_matches[tier]
            total_fg = len(data['Home_first']) + len(data['Away_first'])
            if total_fg < 10:
                continue
            hf_pct = len(data['Home_first'])/total_fg*100
            tier_label = tier.replace('_', ' ')
            print(f"  {tier_label:<25}: Home-first {hf_pct:.1f}% | Away-first {100-hf_pct:.1f}% | n={total_fg}")
            insights[f'first_goal_by_{tier}'] = {
                "total": total_fg, "home_first%": round(hf_pct,1), "away_first%": round(100-hf_pct,1)
            }
            
            # For each tier, check win rate when that team scores first
            for side_name, side_key in [('Home', 'Home_first'), ('Away', 'Away_first')]:
                fg_group = data[side_key]
                if not fg_group:
                    continue
                wins = sum(1 for m in fg_group if m['outcome'] == side_name.upper())
                wr = wins/len(fg_group)*100
                print(f"      {side_name} scores first → {side_name} wins {wr:.1f}%")
                insights.setdefault(f'first_goal_tier_detail', {})[f'{tier}_{side_name}_scores_first'] = {
                    "total": len(fg_group), "win_rate": round(wr,1)
                }
    
    results['insights'] = insights
    return results


# ────────────────────────────────────────────────────────────────
# 5. EXPLORE 3: Team rank changes
# ────────────────────────────────────────────────────────────────
def explore_rank_changes(betdata, db_matches):
    results = {"explore": "Team Rank Changes & Value Bets"}
    print("\n\n=== EXPLORE 3: Team Rank Changes ===")
    
    insights = {}
    
    # Match betdata to database
    matched_results = []
    for bd in betdata:
        season = bd.get('season')
        day = bd.get('matchday')
        home = bd.get('homeTeam')
        away = bd.get('awayTeam')
        if not all([season, day, home, away]):
            continue
        for m in db_matches:
            if (m['season'] == season and m['day'] == day and 
                m['home'] == home and m['away'] == away):
                matched_results.append({**bd, 'outcome': m['outcome'], 'h': m['h'], 'a': m['a']})
                break
    
    print(f"Matched {len(matched_results)} entries")
    insights['matched_count'] = len(matched_results)
    
    if len(matched_results) < 50:
        print("Not enough data for rank analysis")
        results['insights'] = insights
        return results
    
    # Home rank change impact
    print(f"\n--- Home Rank Change → Outcome ---")
    hrc_data = {}
    for chg in ['UP', 'DOWN', 'SAME']:
        group = [m for m in matched_results if m.get('homeRankChange') == chg]
        if group:
            hw = sum(1 for m in group if m['outcome'] == 'HOME')/len(group)*100
            dw = sum(1 for m in group if m['outcome'] == 'DRAW')/len(group)*100
            aw = sum(1 for m in group if m['outcome'] == 'AWAY')/len(group)*100
            print(f"  Home Rank {chg:>4}: n={len(group):>5} | Win: {hw:>5.1f}% | Draw: {dw:>5.1f}% | Loss: {aw:>5.1f}%")
            hrc_data[chg] = {'n': len(group), 'win%': round(hw,1), 'draw%': round(dw,1), 'loss%': round(aw,1)}
    
    insights['home_rank_change'] = hrc_data
    
    # Away rank change impact
    print(f"\n--- Away Rank Change → Outcome ---")
    arc_data = {}
    for chg in ['UP', 'DOWN', 'SAME']:
        group = [m for m in matched_results if m.get('awayRankChange') == chg]
        if group:
            aw = sum(1 for m in group if m['outcome'] == 'AWAY')/len(group)*100
            dw = sum(1 for m in group if m['outcome'] == 'DRAW')/len(group)*100
            hw = sum(1 for m in group if m['outcome'] == 'HOME')/len(group)*100
            print(f"  Away Rank {chg:>4}: n={len(group):>5} | Win: {aw:>5.1f}% | Draw: {dw:>5.1f}% | Loss: {hw:>5.1f}%")
            arc_data[chg] = {'n': len(group), 'win%': round(aw,1), 'draw%': round(dw,1), 'loss%': round(hw,1)}
    
    insights['away_rank_change'] = arc_data
    
    # Top teams (rank 1-5) analysis
    print(f"\n--- Top Teams (Rank 1-5): Rank Change → Win Rate ---")
    top_data = {}
    for side in ['home', 'away']:
        side_data = {}
        for chg in ['UP', 'DOWN', 'SAME']:
            group = [m for m in matched_results 
                    if m.get(f'{side}RankChange') == chg 
                    and m.get(f'{side}Rank') is not None 
                    and m[f'{side}Rank'] <= 5]
            if group:
                wr = sum(1 for m in group if m['outcome'] == side.upper())/len(group)*100
                print(f"  {side.title()} Top5 {chg:>4}: n={len(group):>4} | Win: {wr:>5.1f}%")
                side_data[chg] = {'n': len(group), 'win%': round(wr,1)}
        top_data[side] = side_data
    insights['top_teams_rank_change'] = top_data
    
    # Low teams (rank 15+) analysis  
    print(f"\n--- Low Teams (Rank 15+): Rank Change → Win/Draw Rate ---")
    low_data = {}
    for side in ['home', 'away']:
        side_data = {}
        for chg in ['UP', 'DOWN', 'SAME']:
            group = [m for m in matched_results 
                    if m.get(f'{side}RankChange') == chg 
                    and m.get(f'{side}Rank') is not None 
                    and m[f'{side}Rank'] >= 15]
            if group:
                wr = sum(1 for m in group if m['outcome'] == side.upper())/len(group)*100
                dr = sum(1 for m in group if m['outcome'] == 'DRAW')/len(group)*100
                print(f"  {side.title()} Low {chg:>4}: n={len(group):>4} | Win: {wr:>5.1f}% | Draw: {dr:>5.1f}%")
                # Value: win rate × draw rate (points expectation)
                pts_expect = wr * 3 + dr * 1
                print(f"          Points expectancy: {pts_expect/100:.2f}")
                side_data[chg] = {'n': len(group), 'win%': round(wr,1), 'draw%': round(dr,1), 'pts_expect': round(pts_expect/100,2)}
        low_data[side] = side_data
    insights['low_teams_rank_change'] = low_data
    
    # Value bet detection
    print(f"\n--- Value Bet Analysis ---")
    value_bets = []
    for m in matched_results:
        odds_h = m.get('odds_h')
        odds_a = m.get('odds_a')
        odds_d = m.get('odds_d')
        hr = m.get('homeRank')
        ar = m.get('awayRank')
        hrc = m.get('homeRankChange')
        arc = m.get('awayRankChange')
        
        if not all([odds_h, odds_a, odds_d, hr is not None, ar is not None]):
            continue
        
        odds_h = float(odds_h)
        odds_a = float(odds_a)
        
        # Value bet: low-ranked team with UP momentum, check if odds underprice them
        if hr >= 15 and hrc == 'UP':
            implied = 1/odds_h * 100
            actual = 1 if m['outcome'] == 'HOME' else 0
            value_bets.append({'type': 'home_low_rank_up', 'team': m['homeTeam'], 'odds': odds_h, 'implied_pct': round(implied,1), 'won': actual, 'opponent': m['awayTeam']})
        
        if ar >= 15 and arc == 'UP':
            implied = 1/odds_a * 100
            actual = 1 if m['outcome'] == 'AWAY' else 0
            value_bets.append({'type': 'away_low_rank_up', 'team': m['awayTeam'], 'odds': odds_a, 'implied_pct': round(implied,1), 'won': actual, 'opponent': m['homeTeam']})
    
    if value_bets:
        vb_won = sum(1 for vb in value_bets if vb['won'])
        vb_total = len(value_bets)
        print(f"  Low-rank+UP bets: {vb_won}/{vb_total} won ({vb_won/vb_total*100:.1f}%)")
        insights['value_bets'] = {'total': vb_total, 'won': vb_won, 'win_rate': round(vb_won/vb_total*100,1)}
        if vb_total > 0:
            # Break out by type
            for vb_type in ['home_low_rank_up', 'away_low_rank_up']:
                subset = [vb for vb in value_bets if vb['type'] == vb_type]
                if subset:
                    sw = sum(1 for vb in subset if vb['won'])
                    print(f"  {vb_type}: {sw}/{len(subset)} ({sw/len(subset)*100:.1f}%)")
    
    results['insights'] = insights
    return results


# ────────────────────────────────────────────────────────────────
# 6. EXPLORE 4: Streaks
# ────────────────────────────────────────────────────────────────
def explore_streaks(matches):
    results = {"explore": "Consecutive Match Patterns & Streaks"}
    print("\n\n=== EXPLORE 4: Consecutive Match Patterns & Streaks ===")
    
    insights = {}
    
    # Build per-team sequences
    matches_by_season = defaultdict(list)
    for m in matches:
        matches_by_season[m['season']].append(m)
    
    team_seq = defaultdict(list)  # (season, team) -> [outcome_list]
    for season, season_matches in matches_by_season.items():
        season_matches.sort(key=lambda x: x['day'])
        team_games = defaultdict(list)
        for m in season_matches:
            team_games[(season, m['home'])].append({
                'opponent': m['away'], 'side': 'home', 'outcome': m['outcome'],
                'gf': m['h'], 'ga': m['a'], 'day': m['day']
            })
            team_games[(season, m['away'])].append({
                'opponent': m['home'], 'side': 'away', 'outcome': m['outcome'],
                'gf': m['a'], 'ga': m['h'], 'day': m['day']
            })
        
        for key, games in team_games.items():
            games.sort(key=lambda x: x['day'])
            team_seq[key] = games
    
    print(f"Tracking {len(team_seq)} team-seasons")
    insights['total_team_seasons'] = len(team_seq)
    
    # --- After 3 consecutive HOME wins ---
    three_home_wins_seq = Counter()
    for key, games in team_seq.items():
        for i in range(len(games) - 3):
            if games[i]['outcome'] == 'HOME' and games[i+1]['outcome'] == 'HOME' and games[i+2]['outcome'] == 'HOME':
                if i+3 < len(games):
                    three_home_wins_seq[games[i+3]['outcome']] += 1
    
    if three_home_wins_seq:
        total_3w = sum(three_home_wins_seq.values())
        print(f"\n--- After 3 wins → Next match (n={total_3w}) ---")
        for outcome in ['HOME', 'DRAW', 'AWAY']:
            cnt = three_home_wins_seq.get(outcome, 0)
            print(f"  {outcome:>5}: {cnt:>4} ({cnt/total_3w*100:.1f}%)")
        insights['after_3_wins'] = {k.lower(): {'count': v, 'pct': round(v/total_3w*100,1)} for k,v in dict(three_home_wins_seq).items()}
    
    # --- After 3 consecutive DRAWS ---
    three_draws_seq = Counter()
    for key, games in team_seq.items():
        for i in range(len(games) - 3):
            if games[i]['outcome'] == 'DRAW' and games[i+1]['outcome'] == 'DRAW' and games[i+2]['outcome'] == 'DRAW':
                if i+3 < len(games):
                    three_draws_seq[games[i+3]['outcome']] += 1
    
    if three_draws_seq:
        total_3d = sum(three_draws_seq.values())
        print(f"\n--- After 3 draws → Next match (n={total_3d}) ---")
        for outcome in ['HOME', 'DRAW', 'AWAY']:
            cnt = three_draws_seq.get(outcome, 0)
            if cnt:
                print(f"  {outcome:>5}: {cnt:>4} ({cnt/total_3d*100:.1f}%)")
        insights['after_3_draws'] = {k.lower(): {'count': v, 'pct': round(v/total_3d*100,1)} for k,v in dict(three_draws_seq).items()}
    
    # --- After 3 consecutive AWAY wins ---
    three_away_wins_seq = Counter()
    for key, games in team_seq.items():
        for i in range(len(games) - 3):
            if games[i]['outcome'] == 'AWAY' and games[i+1]['outcome'] == 'AWAY' and games[i+2]['outcome'] == 'AWAY':
                if i+3 < len(games):
                    three_away_wins_seq[games[i+3]['outcome']] += 1
    
    if three_away_wins_seq:
        total_3aw = sum(three_away_wins_seq.values())
        print(f"\n--- After 3 away wins → Next match (n={total_3aw}) ---")
        for outcome in ['HOME', 'DRAW', 'AWAY']:
            cnt = three_away_wins_seq.get(outcome, 0)
            if cnt:
                print(f"  {outcome:>5}: {cnt:>4} ({cnt/total_3aw*100:.1f}%)")
        insights['after_3_away_wins'] = {k.lower(): {'count': v, 'pct': round(v/total_3aw*100,1)} for k,v in dict(three_away_wins_seq).items()}
    
    # --- After 2 consecutive draws ---
    two_draws_seq = Counter()
    for key, games in team_seq.items():
        for i in range(len(games) - 2):
            if games[i]['outcome'] == 'DRAW' and games[i+1]['outcome'] == 'DRAW':
                if i+2 < len(games):
                    two_draws_seq[games[i+2]['outcome']] += 1
    
    if two_draws_seq:
        total_2d = sum(two_draws_seq.values())
        print(f"\n--- After 2 draws → Next match (n={total_2d}) ---")
        for outcome in ['HOME', 'DRAW', 'AWAY']:
            cnt = two_draws_seq.get(outcome, 0)
            if cnt:
                print(f"  {outcome:>5}: {cnt:>4} ({cnt/total_2d*100:.1f}%)")
        insights['after_2_draws'] = {k.lower(): {'count': v, 'pct': round(v/total_2d*100,1)} for k,v in dict(two_draws_seq).items()}
    
    # --- Big loss bounce-back ---
    big_loss_bounce = Counter()
    for key, games in team_seq.items():
        for i, game in enumerate(games):
            gf = game.get('gf')
            ga = game.get('ga')
            if gf is not None and ga is not None and ga - gf >= 3:  # Loss by 3+
                if i + 1 < len(games):
                    big_loss_bounce[games[i+1]['outcome']] += 1
    
    if big_loss_bounce:
        total_bl = sum(big_loss_bounce.values())
        print(f"\n--- Bounce back after big loss (3+ goal margin) (n={total_bl}) ---")
        for outcome in ['HOME', 'DRAW', 'AWAY']:
            cnt = big_loss_bounce.get(outcome, 0)
            if cnt:
                print(f"  Next: {outcome:>5} → {cnt:>4} ({cnt/total_bl*100:.1f}%)")
        insights['big_loss_bounce'] = {k.lower(): {'count': v, 'pct': round(v/total_bl*100,1)} for k,v in dict(big_loss_bounce).items()}
    
    # --- Big WIN bounce (win by 3+, then regression?) ---
    big_win_follow = Counter()
    for key, games in team_seq.items():
        for i, game in enumerate(games):
            gf = game.get('gf')
            ga = game.get('ga')
            if gf is not None and ga is not None and gf - ga >= 3:  # Win by 3+
                if i + 1 < len(games):
                    big_win_follow[games[i+1]['outcome']] += 1
    
    if big_win_follow:
        total_bw = sum(big_win_follow.values())
        print(f"\n--- After big WIN (3+ goal margin) → (n={total_bw}) ---")
        for outcome in ['HOME', 'DRAW', 'AWAY']:
            cnt = big_win_follow.get(outcome, 0)
            if cnt:
                print(f"  Next: {outcome:>5} → {cnt:>4} ({cnt/total_bw*100:.1f}%)")
        insights['big_win_follow'] = {k.lower(): {'count': v, 'pct': round(v/total_bw*100,1)} for k,v in dict(big_win_follow).items()}
    
    # --- Overall win streak length distribution ---
    print(f"\n--- Win streak length distribution ---")
    streak_lengths = Counter()
    for key, games in team_seq.items():
        current_streak = 0
        for g in games:
            outcome = g['outcome']
            if outcome == 'HOME' or (outcome == 'AWAY' and g['side'] == 'away'):
                current_streak += 1
            else:
                if current_streak > 0:
                    streak_lengths[current_streak] += 1
                current_streak = 0
        if current_streak > 0:
            streak_lengths[current_streak] += 1
    
    for length in sorted(streak_lengths.keys()):
        pass  # Collecting but not printing every detail
    
    results['insights'] = insights
    return results


# ────────────────────────────────────────────────────────────────
# 7. EXPLORE 5: Seasonal position
# ────────────────────────────────────────────────────────────────
def explore_seasonal_position(matches):
    results = {"explore": "Seasonal Position Effects"}
    print("\n\n=== EXPLORE 5: Seasonal Position ===")
    
    insights = {}
    
    # Determine season lengths
    season_days = defaultdict(set)
    for m in matches:
        season_days[m['season']].add(m['day'])
    season_max_day = {s: max(days) for s, days in season_days.items()}
    
    # Phase classification
    phase_data = defaultdict(lambda: {'HOME': 0, 'AWAY': 0, 'DRAW': 0, 'total': 0, 'goals': [], 'o25': 0})
    
    for m in matches:
        max_day = season_max_day.get(m['season'])
        if not max_day or max_day <= 0:
            continue
        phase_ratio = m['day'] / max_day
        if phase_ratio <= 0.25:
            phase_label = 'Early (0-25%)'
        elif phase_ratio <= 0.50:
            phase_label = 'Mid-Early (25-50%)'
        elif phase_ratio <= 0.75:
            phase_label = 'Mid-Late (50-75%)'
        else:
            phase_label = 'Late (75-100%)'
        
        if m['outcome'] in ('HOME', 'AWAY', 'DRAW'):
            phase_data[phase_label][m['outcome']] += 1
            phase_data[phase_label]['total'] += 1
        
        if m.get('total') is not None:
            phase_data[phase_label]['goals'].append(m['total'])
            if m.get('o25') == 1:
                phase_data[phase_label]['o25'] += 1
    
    print(f"\n--- Outcome by Season Phase ---")
    print(f"{'Phase':<20} | {'Total':>6} | {'Home%':>7} | {'Draw%':>7} | {'Away%':>7} | {'AvgGls':>7} | {'O25%':>7}")
    
    phase_insights = {}
    for phase in ['Early (0-25%)', 'Mid-Early (25-50%)', 'Mid-Late (50-75%)', 'Late (75-100%)']:
        d = phase_data[phase]
        if d['total'] == 0:
            continue
        hp = d['HOME']/d['total']*100
        dp = d['DRAW']/d['total']*100
        ap = d['AWAY']/d['total']*100
        avg_goals = sum(d['goals'])/len(d['goals']) if d['goals'] else 0
        o25p = d['o25']/d['total']*100 if d['total'] > 0 else 0
        print(f"{phase:<20} | {d['total']:>6} | {hp:>6.1f}% | {dp:>6.1f}% | {ap:>6.1f}% | {avg_goals:>6.2f} | {o25p:>6.1f}%")
        phase_insights[phase] = {
            'total': d['total'], 'home%': round(hp,1), 'draw%': round(dp,1), 'away%': round(ap,1),
            'avg_goals': round(avg_goals,2), 'over25%': round(o25p,1)
        }
    
    insights['phase_outcomes'] = phase_insights
    
    # Early vs Late: upset analysis using odds from DB
    odds_matches = [m for m in matches if m.get('oh') and m.get('oa') and m.get('oh') != '' and m.get('oa') != '']
    if odds_matches:
        print(f"\n--- Upsets by Phase (odds-based favourite) ---")
        phase_upsets = defaultdict(lambda: {'fav_wins': 0, 'upsets': 0, 'draws': 0, 'total': 0})
        
        for m in odds_matches:
            max_day = season_max_day.get(m['season'])
            if not max_day or max_day <= 0:
                continue
            phase_ratio = m['day'] / max_day
            if phase_ratio <= 0.25:
                lbl = 'Early'
            elif phase_ratio <= 0.50:
                lbl = 'Mid-Early'
            elif phase_ratio <= 0.75:
                lbl = 'Mid-Late'
            else:
                lbl = 'Late'
            
            try:
                oh = float(m['oh'])
                oa = float(m['oa'])
            except (ValueError, TypeError):
                continue
            
            outcome = m['outcome']
            phase_upsets[lbl]['total'] += 1
            
            if outcome == 'DRAW':
                phase_upsets[lbl]['draws'] += 1
            elif (oh < oa and outcome == 'HOME') or (oa < oh and outcome == 'AWAY'):
                phase_upsets[lbl]['fav_wins'] += 1
            else:
                phase_upsets[lbl]['upsets'] += 1
        
        for lbl in ['Early', 'Mid-Early', 'Mid-Late', 'Late']:
            d = phase_upsets[lbl]
            if d['total'] == 0:
                continue
            print(f"  {lbl:<15}: n={d['total']:>5} | Favourite: {d['fav_wins']/d['total']*100:>5.1f}% | Upset: {d['upsets']/d['total']*100:>5.1f}% | Draw: {d['draws']/d['total']*100:>5.1f}%")
        
        insights['upsets_by_phase'] = {k: {
            'total': v['total'], 'fav_wins%': round(v['fav_wins']/v['total']*100,1) if v['total'] else 0,
            'upset%': round(v['upsets']/v['total']*100,1) if v['total'] else 0,
            'draw%': round(v['draws']/v['total']*100,1) if v['total'] else 0
        } for k, v in phase_upsets.items()}
    
    # Early season vs late season: home advantage
    print(f"\n--- Home Win Rate by Matchday (early vs late in season) ---")
    dw = 5  # day window
    if odds_matches:
        day_stats = defaultdict(lambda: {'HOME': 0, 'total': 0})
        for m in odds_matches:
            day_stats[m['day']]['total'] += 1
            if m['outcome'] == 'HOME':
                day_stats[m['day']]['HOME'] += 1
        
        total_days = max(season_max_day.values())
        if total_days:
            first_third = int(total_days * 0.33)
            last_third_start = int(total_days * 0.67)
            
            first_total = sum(day_stats[d]['total'] for d in range(1, first_third+1))
            first_home = sum(day_stats[d]['HOME'] for d in range(1, first_third+1))
            last_total = sum(day_stats[d]['total'] for d in range(last_third_start, total_days+1))
            last_home = sum(day_stats[d]['HOME'] for d in range(last_third_start, total_days+1))
            
            if first_total > 0 and last_total > 0:
                fhw = first_home/first_total*100
                lhw = last_home/last_total*100
                print(f"  First 33% of season: Home win {fhw:.1f}% (n={first_total})")
                print(f"  Last 33% of season:  Home win {lhw:.1f}% (n={last_total})")
                insights['early_vs_late_home_win'] = {
                    'early': {'n': first_total, 'home_win%': round(fhw,1)},
                    'late': {'n': last_total, 'home_win%': round(lhw,1)}
                }
    
    results['insights'] = insights
    return results


# ────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("TORIN — Pattern Recognition Analysis v2")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)
    
    print("\nLoading database...")
    db_matches = query_db()
    print(f"Loaded {len(db_matches)} matches")
    
    print("\nParsing betdata files...")
    betdata = parse_betdata_files()
    print(f"Parsed {len(betdata)} entries")
    
    all_results = {
        'meta': {
            'timestamp': datetime.now().isoformat(),
            'total_db_matches': len(db_matches),
            'total_betdata_entries': len(betdata),
        },
        'explorations': {}
    }
    
    all_results['explorations']['explore_1_ht_lead'] = explore_ht_lead_ft_outcome(db_matches)
    all_results['explorations']['explore_2_first_goal'] = explore_first_goal(db_matches, betdata)
    all_results['explorations']['explore_3_rank_changes'] = explore_rank_changes(betdata, db_matches)
    all_results['explorations']['explore_4_streaks'] = explore_streaks(db_matches)
    all_results['explorations']['explore_5_seasonal'] = explore_seasonal_position(db_matches)
    
    print("\n\n=== ANALYSIS COMPLETE ===")
    
    # Save
    os.makedirs(f"{DATA_DIR}/analysis", exist_ok=True)
    outpath = f"{DATA_DIR}/analysis/torin-patterns.json"
    with open(outpath, 'w') as f:
        json.dump(all_results, f, default=str, indent=2)
    print(f"\nResults saved to {outpath}")


if __name__ == '__main__':
    main()

# ────────────────────────────────────────────────────────────────
# 3b. EXPLORE 3 FIXED: Team rank changes with proper matching
# ────────────────────────────────────────────────────────────────
def explore_rank_changes_v2(betdata, db_matches):
    results = {"explore": "Team Rank Changes & Value Bets (fixed matching)"}
    print("\n\n=== EXPLORE 3 (v2): Team Rank Changes ===")
    
    import urllib.parse
    insights = {}
    
    # Build lookup index for DB matches
    db_index = {}
    for m in db_matches:
        key = (m['season'], m['day'], m['home'].lower(), m['away'].lower())
        db_index[key] = m
    
    matched_results = []
    for bd in betdata:
        season = bd.get('season')
        day = bd.get('matchday')
        if season:
            # URL decode the season
            season = urllib.parse.unquote(season)
        home = bd.get('homeTeam')
        away = bd.get('awayTeam')
        if not all([season, day, home, away]):
            continue
        
        key = (season, day, home.lower(), away.lower())
        m = db_index.get(key)
        if m:
            matched_results.append({**bd, 'outcome': m['outcome'], 'h': m['h'], 'a': m['a']})
    
    print(f"Matched {len(matched_results)} entries (v2 matching)")
    insights['matched_count'] = len(matched_results)
    
    if len(matched_results) < 50:
        print("Still not enough. Let me check what's happening...")
        # Debug: show a few examples
        if betdata:
            bd = betdata[0]
            season = urllib.parse.unquote(bd['season']) if bd.get('season') else None
            print(f"  Example BD: season={season}, day={bd.get('matchday')}, home={bd.get('homeTeam')}, away={bd.get('awayTeam')}")
            # Check if season exists in DB
            curs = sqlite3.connect(DB_PATH).cursor()
            curs.execute("SELECT COUNT(*) FROM matches WHERE season=?", (season,))
            count = curs.fetchone()[0]
            print(f"  Season {season} has {count} matches in DB")
            
            # Check team name matching for first BD entry
            for m in db_matches:
                if m['season'] == season and m['day'] == bd.get('matchday'):
                    print(f"  DB: {m['home']} vs {m['away']}")
                    print(f"  BD: {bd['homeTeam']} vs {bd['awayTeam']}")
                    print(f"  Match: {m['home'].lower() == bd['homeTeam'].lower() and m['away'].lower() == bd['awayTeam'].lower()}")
                    break
            curs.close()
        results['insights'] = insights
        return results
    
    # Home rank change impact
    print(f"\n--- Home Rank Change → Outcome ---")
    hrc_data = {}
    for chg in ['UP', 'DOWN', 'SAME']:
        group = [m for m in matched_results if m.get('homeRankChange') == chg]
        if group:
            hw = sum(1 for m in group if m['outcome'] == 'HOME')/len(group)*100
            dw = sum(1 for m in group if m['outcome'] == 'DRAW')/len(group)*100
            aw = sum(1 for m in group if m['outcome'] == 'AWAY')/len(group)*100
            print(f"  Home Rank {chg:>4}: n={len(group):>5} | Win: {hw:>5.1f}% | Draw: {dw:>5.1f}% | Loss: {aw:>5.1f}%")
            hrc_data[chg] = {'n': len(group), 'win%': round(hw,1), 'draw%': round(dw,1), 'loss%': round(aw,1)}
    insights['home_rank_change'] = hrc_data
    
    # Away rank change impact
    print(f"\n--- Away Rank Change → Outcome ---")
    arc_data = {}
    for chg in ['UP', 'DOWN', 'SAME']:
        group = [m for m in matched_results if m.get('awayRankChange') == chg]
        if group:
            aw = sum(1 for m in group if m['outcome'] == 'AWAY')/len(group)*100
            dw = sum(1 for m in group if m['outcome'] == 'DRAW')/len(group)*100
            hw = sum(1 for m in group if m['outcome'] == 'HOME')/len(group)*100
            print(f"  Away Rank {chg:>4}: n={len(group):>5} | Win: {aw:>5.1f}% | Draw: {dw:>5.1f}% | Loss: {hw:>5.1f}%")
            arc_data[chg] = {'n': len(group), 'win%': round(aw,1), 'draw%': round(dw,1), 'loss%': round(hw,1)}
    insights['away_rank_change'] = arc_data
    
    # Top teams (rank 1-5) analysis
    print(f"\n--- Top Teams (Rank 1-5): Rank Change → Win Rate ---")
    top_data = {}
    for side in ['home', 'away']:
        side_data = {}
        for chg in ['UP', 'DOWN', 'SAME']:
            group = [m for m in matched_results 
                    if m.get(f'{side}RankChange') == chg 
                    and m.get(f'{side}Rank') is not None 
                    and m[f'{side}Rank'] <= 5]
            if group:
                wr = sum(1 for m in group if m['outcome'] == side.upper())/len(group)*100
                print(f"  {side.title()} Top5 {chg:>4}: n={len(group):>4} | Win: {wr:>5.1f}%")
                side_data[chg] = {'n': len(group), 'win%': round(wr,1)}
        top_data[side] = side_data
    insights['top_teams_rank_change'] = top_data
    
    # Low teams (rank 15+) analysis  
    print(f"\n--- Low Teams (Rank 15+): Rank Change → Win/Draw Rate ---")
    low_data = {}
    for side in ['home', 'away']:
        side_data = {}
        for chg in ['UP', 'DOWN', 'SAME']:
            group = [m for m in matched_results 
                    if m.get(f'{side}RankChange') == chg 
                    and m.get(f'{side}Rank') is not None 
                    and m[f'{side}Rank'] >= 15]
            if group:
                wr = sum(1 for m in group if m['outcome'] == side.upper())/len(group)*100
                dr = sum(1 for m in group if m['outcome'] == 'DRAW')/len(group)*100
                pts_expect = (wr * 3 + dr * 1) / 100
                print(f"  {side.title()} Low {chg:>4}: n={len(group):>4} | Win: {wr:>5.1f}% | Draw: {dr:>5.1f}% | PtsExp: {pts_expect:.2f}")
                side_data[chg] = {'n': len(group), 'win%': round(wr,1), 'draw%': round(dr,1), 'pts_expect': round(pts_expect,2)}
        low_data[side] = side_data
    insights['low_teams_rank_change'] = low_data
    
    # Value bet detection
    print(f"\n--- Value Bet Analysis ---")
    value_bets = []
    for m in matched_results:
        odds_h = m.get('odds_h')
        odds_a = m.get('odds_a')
        odds_d = m.get('odds_d')
        hr = m.get('homeRank')
        ar = m.get('awayRank')
        hrc = m.get('homeRankChange')
        arc = m.get('awayRankChange')
        
        if not all([odds_h, odds_a, odds_d, hr is not None, ar is not None]):
            continue
        
        odds_h = float(odds_h)
        odds_a = float(odds_a)
        odds_d = float(odds_d)
        
        # Value bet: low-ranked team with UP momentum
        if hr >= 15 and hrc == 'UP':
            implied = 1/odds_h * 100
            value_bets.append({'type': 'home_low_rank_up', 'team': m['homeTeam'], 'odds': odds_h, 
                             'implied_pct': round(implied,1), 'outcome': m['outcome'],
                             'opponent': m['awayTeam']})
        
        if ar >= 15 and arc == 'UP':
            implied = 1/odds_a * 100
            value_bets.append({'type': 'away_low_rank_up', 'team': m['awayTeam'], 'odds': odds_a,
                             'implied_pct': round(implied,1), 'outcome': m['outcome'],
                             'opponent': m['homeTeam']})
    
    if value_bets:
        vb_won = sum(1 for vb in value_bets if 
                    (vb['type'] == 'home_low_rank_up' and vb['outcome'] == 'HOME') or
                    (vb['type'] == 'away_low_rank_up' and vb['outcome'] == 'AWAY'))
        vb_total = len(value_bets)
        print(f"  Low-rank+UP bets: {vb_won}/{vb_total} won ({vb_won/vb_total*100:.1f}%)")
        insights['value_bets'] = {'total': vb_total, 'won': vb_won, 'win_rate': round(vb_won/vb_total*100,1)}
        for vb_type in ['home_low_rank_up', 'away_low_rank_up']:
            subset = [vb for vb in value_bets if vb['type'] == vb_type]
            if subset:
                sw = sum(1 for vb in subset if 
                       (vb['type'] == 'home_low_rank_up' and vb['outcome'] == 'HOME') or
                       (vb['type'] == 'away_low_rank_up' and vb['outcome'] == 'AWAY'))
                print(f"  {vb_type}: {sw}/{len(subset)} ({sw/len(subset)*100:.1f}%)")
                if vb_type not in insights:
                    insights[vb_type] = {'total': len(subset), 'won': sw, 'win_rate': round(sw/len(subset)*100,1)}
    else:
        print("  No value bet candidates found")
    
    results['insights'] = insights
    return results

# Also add a master function that adds v2 rank analysis
def run_fixed_explore3():
    import urllib.parse
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT season, day, home, away, outcome, h, a FROM matches WHERE outcome IN ('HOME','AWAY','DRAW')")
    db_matches = [dict(r) for r in cur.fetchall()]
    conn.close()
    
    betdata = parse_betdata_files()
    
    # Build DB index
    db_index = {}
    for m in db_matches:
        key = (m['season'], m['day'], m['home'].lower(), m['away'].lower())
        db_index[key] = m
    
    # Test matching
    matched = 0
    for bd in betdata:
        season = bd.get('season')
        day = bd.get('matchday')
        if season:
            season = urllib.parse.unquote(season)
        home = bd.get('homeTeam')
        away = bd.get('awayTeam')
        if not all([season, day, home, away]):
            continue
        key = (season, day, home.lower(), away.lower())
        if key in db_index:
            matched += 1
    
    print(f"Matched {matched}/{len(betdata)} using case-insensitive team names")
    
    # If still 0, debug further
    if matched == 0 and betdata:
        bd = betdata[0]
        sea = urllib.parse.unquote(bd.get('season', ''))
        d = bd.get('matchday')
        h = bd.get('homeTeam', '').lower()
        a = bd.get('awayTeam', '').lower()
        print(f"  Trying: season={sea}, day={d}, home={h}, away={a}")
        
        # Check what's in DB for same season and day
        for m in db_matches[:20]:
            if m['season'] == sea and m['day'] == d:
                print(f"  DB has: {m['home']} vs {m['away']}")
                print(f"  lower: {m['home'].lower()} vs {m['away'].lower()}")
                print(f"  Match home: {m['home'].lower() == h}, Match away: {m['away'].lower() == a}")

if __name__ == '__main__':
    print("=== Debug: Rank Analysis Matching ===")
    run_fixed_explore3()
