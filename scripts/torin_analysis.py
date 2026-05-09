#!/usr/bin/env python3
"""
Torin — Pattern Recognition Analysis for Trillions Empire
Extracts data from API response files + SQLite, finds hidden patterns
"""
import json, re, sqlite3, os, sys
from collections import defaultdict, Counter
from datetime import datetime

DATA_DIR = "/home/faith/Documents/Projects/vfl-data"
EXTRACTED_DIR = f"{DATA_DIR}/extracted"
DB_PATH = f"{DATA_DIR}/databases/history.db"

# ────────────────────────────────────────────────────────────────
# 1. PARSE BETDATA FILES — extract match odds + rank info
# ────────────────────────────────────────────────────────────────
def parse_betdata_files():
    """Extract rank data, odds, team info from betdata JSON responses"""
    betdata_files = [
        "responsesSat27betdata.txt",
        "responsesSat27betdata3.txt", 
        "responsesSat27betdata4.txt",
        "responsesSat27betdata5.txt",
        "responsesSat27betdata6.txt",
        # Also check other files for rank data
        "responsesSat27.txt",
        "responsesundaydata1.txt",
        "msport-responses.txt",
    ]
    
    matches_data = []
    current_match = {}
    json_buffer = ""
    in_json = False
    
    for fname in betdata_files:
        fpath = os.path.join(EXTRACTED_DIR, fname)
        if not os.path.exists(fpath):
            continue
        print(f"Parsing {fname}...")
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # Split by match boundaries
        sections = re.split(r'===== MATCH #(\d+) =====', content)
        if len(sections) > 1:
            # sections[0] is pre-first-match, then alternating: id, content
            for i in range(1, len(sections), 2):
                match_num = sections[i]
                section = sections[i+1] if i+1 < len(sections) else ""
                
                # Extract URL info
                season = None
                matchday = None
                url_match = re.search(r'seasonId=([^&\s]+)', section)
                if url_match:
                    season = url_match.group(1)
                day_match = re.search(r'matchDay=(\d+)', section)
                if day_match:
                    matchday = int(day_match.group(1))
                
                # Extract JSON response body
                json_match = re.search(r'\{[\s\S]*"bizCode":\s*10000[\s\S]*"events":\s*\[', section)
                if not json_match:
                    # Try to find any JSON-like structure
                    json_match = re.search(r'(\{[\s\S]*"bizCode":\s*10000[\s\S]*\})', section)
                
                if json_match:
                    try:
                        data = json.loads(json_match.group(1))
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
                    except json.JSONDecodeError:
                        pass
    
    print(f"Parsed {len(matches_data)} match entries from betdata files")
    return matches_data


# ────────────────────────────────────────────────────────────────
# 2. QUERY DATABASE
# ────────────────────────────────────────────────────────────────
def query_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Get all matches with relevant fields
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
    print("\n=== EXPLORE 1: Half-time Lead → Full-time Outcome ===")
    
    # Parse HT scores - group by goal difference
    ht_gd_groups = defaultdict(list)
    for m in matches:
        ht = m.get('half_time')
        if not ht or ht == '' or ht == '--':
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
    
    results_ht = {}
    print(f"\n--- HT Goal Difference → Outcome ---")
    print(f"{'HT GD':>6} | {'Total':>6} | {'Home%':>7} | {'Draw%':>7} | {'Away%':>7}")
    for gd in sorted(ht_gd_groups.keys()):
        group = ht_gd_groups[gd]
        n = len(group)
        h = sum(1 for m in group if m['outcome'] == 'HOME')
        d = sum(1 for m in group if m['outcome'] == 'DRAW')
        a = sum(1 for m in group if m['outcome'] == 'AWAY')
        hp = h/n*100
        dp = d/n*100
        ap = a/n*100
        results_ht[gd] = {'total': n, 'home%': round(hp,1), 'draw%': round(dp,1), 'away%': round(ap,1)}
        print(f"{gd:>6} | {n:>6} | {hp:>6.1f}% | {dp:>6.1f}% | {ap:>6.1f}%")
    
    # Key insight: certainty increase from 1-goal to 2-goal lead
    if 1 in ht_gd_groups and 2 in ht_gd_groups:
        g1 = ht_gd_groups[1]
        g2 = ht_gd_groups[2]
        h1 = sum(1 for m in g1 if m['outcome'] == 'HOME')/len(g1)*100
        h2 = sum(1 for m in g2 if m['outcome'] == 'HOME')/len(g2)*100
        print(f"\n>>> INSIGHT: 1-goal HT lead → {h1:.1f}% home win")
        print(f">>> INSIGHT: 2-goal HT lead → {h2:.1f}% home win")
        print(f">>> Certainty jump: +{h2-h1:.1f} percentage points")
    
    if -1 in ht_gd_groups and -2 in ht_gd_groups:
        g1 = ht_gd_groups[-1]
        g2 = ht_gd_groups[-2]
        a1 = sum(1 for m in g1 if m['outcome'] == 'AWAY')/len(g1)*100
        a2 = sum(1 for m in g2 if m['outcome'] == 'AWAY')/len(g2)*100
        print(f">>> INSIGHT: 1-goal away HT lead → {a1:.1f}% away win")
        print(f">>> INSIGHT: 2-goal away HT lead → {a2:.1f}% away win") 
        print(f">>> Certainty jump: +{a2-a1:.1f} pp")
    
    # HT 0-0 draw tendency
    zero_count = len(ht_gd_groups.get(0, []))
    z_h = sum(1 for m in ht_gd_groups.get(0, []) if m['outcome'] == 'HOME')
    z_a = sum(1 for m in ht_gd_groups.get(0, []) if m['outcome'] == 'AWAY')
    z_d = sum(1 for m in ht_gd_groups.get(0, []) if m['outcome'] == 'DRAW')
    print(f"\n>>> 0-0 at HT → Draw rate: {z_d/zero_count*100:.1f}% (n={zero_count})")
    
    return results_ht


# ────────────────────────────────────────────────────────────────
# 4. EXPLORE 2: First goal = match story
# ────────────────────────────────────────────────────────────────
def explore_first_goal(matches, betdata):
    print("\n\n=== EXPLORE 2: First Goal = Match Story ===")
    
    # First goal overall stats
    fg_data = {'Home': [], 'Away': []}
    for m in matches:
        fg = m.get('first_goal')
        if fg in ('Home', 'Away'):
            fg_data[fg].append(m)
    
    print(f"\n--- First Goal → Outcome ---")
    for fg, group in [('Home', fg_data['Home']), ('Away', fg_data['Away'])]:
        n = len(group)
        h = sum(1 for m in group if m['outcome'] == 'HOME')
        d = sum(1 for m in group if m['outcome'] == 'DRAW')
        a = sum(1 for m in group if m['outcome'] == 'AWAY')
        print(f"\n{'First=' + fg + ' scores first':>20} | n={n:>6} | Home: {h/n*100:>5.1f}% | Draw: {d/n*100:>5.1f}% | Away: {a/n*100:>5.1f}%")
    
    # When home scores first but loses - what's the pattern?
    home_first_losses = [m for m in matches if m.get('first_goal') == 'Home' and m['outcome'] == 'AWAY']
    print(f"\n--- Home scores first but LOSES: {len(home_first_losses)} cases ---")
    ht_losses = Counter()
    for m in home_first_losses:
        ht = m.get('half_time', 'N/A')
        ht_losses[ht] += 1
    for ht, cnt in ht_losses.most_common(10):
        print(f"  HT {ht}: {cnt} matches")
    
    # First goal by tier (approximate - using rank if available from betdata)
    # Cross-reference: betdata has homeRank, awayRank
    # Let's look at which teams are top-ranked
    rank_by_team = defaultdict(list)
    for bd in betdata:
        if bd.get('homeRank') is not None:
            rank_by_team[bd['homeTeam']].append(bd['homeRank'])
        if bd.get('awayRank') is not None:
            rank_by_team[bd['awayTeam']].append(bd['awayRank'])
    
    avg_ranks = {team: sum(rs)/len(rs) for team, rs in rank_by_team.items()}
    sorted_teams = sorted(avg_ranks.items(), key=lambda x: x[1])
    
    print(f"\n--- Top 15 teams by avg rank (from betdata) ---")
    for team, rank in sorted_teams[:15]:
        print(f"  {team}: avg rank {rank:.1f}")
    
    # Now check: does first_goal correlate with rank difference?
    # We need to get the actual match results that correspond to betdata entries
    print(f"\n--- Cross-reference: rank difference × outcome ---")
    cross = []
    for bd in betdata[:5000]:  # Limit for speed
        season = bd.get('season')
        day = bd.get('matchday')
        home = bd.get('homeTeam')
        away = bd.get('awayTeam')
        if not all([season, day, home, away]):
            continue
        
        # Simple matching: try to match to DB
        # Skip for now as many might not match
    
    return {'home_first_win_rate': len([m for m in fg_data['Home'] if m['outcome'] == 'HOME'])/len(fg_data['Home'])*100 if fg_data['Home'] else 0,
            'away_first_win_rate': len([m for m in fg_data['Away'] if m['outcome'] == 'AWAY'])/len(fg_data['Away'])*100 if fg_data['Away'] else 0}


# ────────────────────────────────────────────────────────────────
# 5. EXPLORE 3: Team rank changes
# ────────────────────────────────────────────────────────────────
def explore_rank_changes(betdata, db_matches):
    print("\n\n=== EXPLORE 3: Team Rank Changes ===")
    
    # Count rank change types
    rank_changes = {'UP': 0, 'DOWN': 0, 'SAME': 0}
    for bd in betdata:
        for key in ['homeRankChange', 'awayRankChange']:
            v = bd.get(key)
            if v in rank_changes:
                rank_changes[v] += 1
    
    print(f"\nRank change distribution: UP={rank_changes['UP']}, DOWN={rank_changes['DOWN']}, SAME={rank_changes['SAME']}")
    
    # Cross-reference with outcomes
    matched_results = []
    for bd in betdata:
        season = bd.get('season')
        day = bd.get('matchday')
        home = bd.get('homeTeam')
        away = bd.get('awayTeam')
        if not all([season, day, home, away]):
            continue
        
        # Match to database
        for m in db_matches:
            if (m['season'] == season and m['day'] == day and 
                m['home'] == home and m['away'] == away and
                m['outcome'] in ('HOME', 'AWAY', 'DRAW')):
                matched_results.append({**bd, 'outcome': m['outcome'], 'h': m['h'], 'a': m['a']})
                break
    
    print(f"Matched {len(matched_results)} betdata entries to DB results")
    
    if len(matched_results) < 100:
        print("Too few matches - need more data")
        return None
    
    # Home rank change impact
    print(f"\n--- Home Rank Change → Home Win Rate ---")
    for chg in ['UP', 'DOWN', 'SAME']:
        group = [m for m in matched_results if m.get('homeRankChange') == chg]
        if group:
            hw = sum(1 for m in group if m['outcome'] == 'HOME')/len(group)*100
            print(f"  Home Rank {chg:>4}: n={len(group):>5} | Home Win: {hw:>5.1f}%")
    
    # Away rank change impact
    print(f"\n--- Away Rank Change → Away Win Rate ---")
    for chg in ['UP', 'DOWN', 'SAME']:
        group = [m for m in matched_results if m.get('awayRankChange') == chg]
        if group:
            aw = sum(1 for m in group if m['outcome'] == 'AWAY')/len(group)*100
            print(f"  Away Rank {chg:>4}: n={len(group):>5} | Away Win: {aw:>5.1f}%")
    
    # Top-ranked teams (rank 1-5) with rank change UP → do they dominate more?
    print(f"\n--- Top Teams (Rank 1-5): Rank Change → Win Rate ---")
    for chg in ['UP', 'DOWN', 'SAME']:
        home_group = [m for m in matched_results 
                     if m.get('homeRankChange') == chg and m.get('homeRank') is not None and m['homeRank'] <= 5]
        away_group = [m for m in matched_results
                     if m.get('awayRankChange') == chg and m.get('awayRank') is not None and m['awayRank'] <= 5]
        if home_group:
            hw = sum(1 for m in home_group if m['outcome'] == 'HOME')/len(home_group)*100
            print(f"  Home Top5 {chg:>4}: n={len(home_group):>4} | Win: {hw:>5.1f}%")
        if away_group:
            aw = sum(1 for m in away_group if m['outcome'] == 'AWAY')/len(away_group)*100
            print(f"  Away Top5 {chg:>4}: n={len(away_group):>4} | Win: {aw:>5.1f}%")
    
    # Low-ranked teams (rank 15-18) with rank change UP → value bet?
    print(f"\n--- Low Teams (Rank 15-18): Rank Change → Win/Draw Rate ---")
    for chg in ['UP', 'DOWN', 'SAME']:
        home_group = [m for m in matched_results
                     if m.get('homeRankChange') == chg and m.get('homeRank') is not None and m['homeRank'] >= 15]
        away_group = [m for m in matched_results
                     if m.get('awayRankChange') == chg and m.get('awayRank') is not None and m['awayRank'] >= 15]
        if home_group:
            hw = sum(1 for m in home_group if m['outcome'] == 'HOME')/len(home_group)*100
            dr = sum(1 for m in home_group if m['outcome'] == 'DRAW')/len(home_group)*100
            print(f"  Home Low {chg:>4}: n={len(home_group):>4} | Win: {hw:>5.1f}% | Draw: {dr:>5.1f}%")
        if away_group:
            aw = sum(1 for m in away_group if m['outcome'] == 'AWAY')/len(away_group)*100
            dr = sum(1 for m in away_group if m['outcome'] == 'DRAW')/len(away_group)*100
            print(f"  Away Low {chg:>4}: n={len(away_group):>4} | Win: {aw:>5.1f}% | Draw: {dr:>5.1f}%")
    
    # Value bet analysis: rank difference × odds
    # When low-ranked team shows "UP" momentum, odds might be inflated
    print(f"\n--- Potential Value Bets: Low rank (15-18) with UP momentum ---")
    for side in ['home', 'away']:
        up_teams = [m for m in matched_results 
                   if m.get(f'{side}RankChange') == 'UP' 
                   and m.get(f'{side}Rank') is not None 
                   and m[f'{side}Rank'] >= 15]
        if side == 'home':
            outcomes = [m for m in up_teams if m['outcome'] in ('HOME', 'DRAW')]
        else:
            outcomes = [m for m in up_teams if m['outcome'] in ('AWAY', 'DRAW')]
        print(f"  {side.title()} low-rank+UP: n={len(up_teams)}, favorable outcome: {len(outcomes)} ({len(outcomes)/len(up_teams)*100:.1f}%)" if up_teams else f"  {side.title()}: no data")
    
    return matched_results


# ────────────────────────────────────────────────────────────────
# 6. EXPLORE 4: Consecutive match patterns & streaks
# ────────────────────────────────────────────────────────────────
def explore_streaks(matches):
    print("\n\n=== EXPLORE 4: Consecutive Match Patterns & Streaks ===")
    
    # Group by season + team
    matches_by_season = defaultdict(list)
    for m in matches:
        matches_by_season[m['season']].append(m)
    
    # For each team's home games in each season, check for streaks
    home_streaks = defaultdict(list)  # team -> [win/draw/loss sequence]
    
    for season, season_matches in matches_by_season.items():
        season_matches.sort(key=lambda x: x['day'])
        team_games = defaultdict(list)
        for m in season_matches:
            team_games[m['home']].append(('HOME', m['day'], m['outcome']))
            team_games[m['away']].append(('AWAY', m['day'], m['outcome']))
        
        for team, games in team_games.items():
            games.sort(key=lambda x: x[1])
            outcomes = [g[2] for g in games]
            home_streaks[team].extend(outcomes)
    
    print(f"Tracking {len(home_streaks)} teams")
    
    # After 3 home wins → chance of draw
    def find_pattern(seq, pattern_len, target_after):
        """Count how often specific pattern leads to target"""
        count = 0
        total = 0
        for i in range(len(seq) - pattern_len):
            if all(seq[i+j] == target_after[j] for j in range(pattern_len)):
                total += 1
                if seq[i+pattern_len] == target_after[0]:
                    count += 1
        return count, total
    
    # Pattern 1: After 3 consecutive home wins → chance of draw
    three_wins = [seq for team, seq in home_streaks.items() if len(seq) >= 4]
    match_3w_draw = 0
    total_3w = 0
    for seq in three_wins:
        for i in range(len(seq) - 3):
            if seq[i] == 'HOME' and seq[i+1] == 'HOME' and seq[i+2] == 'HOME':
                total_3w += 1
                if seq[i+3] == 'DRAW':
                    match_3w_draw += 1
                # Check also: after 3 wins, home win or loss?
    
    if total_3w > 0:
        print(f"\n--- After 3 consecutive wins → next match ---")
        # Count all 3-win streaks
        after_3w_outcomes = Counter()
        for seq in three_wins:
            for i in range(len(seq) - 3):
                if seq[i] == 'HOME' and seq[i+1] == 'HOME' and seq[i+2] == 'HOME':
                    if i+3 < len(seq):
                        after_3w_outcomes[seq[i+3]] += 1
        print(f"Total 3-win streaks: {sum(after_3w_outcomes.values())}")
        for outcome, cnt in after_3w_outcomes.most_common():
            print(f"  Next match: {outcome:>5} → {cnt} ({cnt/sum(after_3w_outcomes.values())*100:.1f}%)")
    
    # After 2 consecutive draws → next outcome
    after_2d_outcomes = Counter()
    for seq in three_wins:
        for i in range(len(seq) - 2):
            if seq[i] == 'DRAW' and seq[i+1] == 'DRAW':
                if i+2 < len(seq):
                    after_2d_outcomes[seq[i+2]] += 1
    if after_2d_outcomes:
        total_2d = sum(after_2d_outcomes.values())
        print(f"\n--- After 2 consecutive draws → next match (n={total_2d}) ---")
        for outcome, cnt in after_2d_outcomes.most_common():
            print(f"  {outcome:>5}: {cnt} ({cnt/total_2d*100:.1f}%)")
    
    # After a big loss (3+ goal deficit)
    big_loss_outcomes = Counter()
    for m in matches:
        if m['h'] is not None and m['a'] is not None:
            if m['outcome'] == 'AWAY' and m['a'] - m['h'] >= 3:
                big_loss_outcomes['home'] += 1
            elif m['outcome'] == 'HOME' and m['h'] - m['a'] >= 3:
                big_loss_outcomes['away'] += 1
    
    print(f"\n--- Big Loss (3+ goal margin) occurrences ---")
    print(f"  Home lost by 3+: {big_loss_outcomes.get('home', 0)}")
    print(f"  Away lost by 3+: {big_loss_outcomes.get('away', 0)}")
    
    # Bounce back: after big loss, what happens next match for that team?
    # Build per-team match sequences
    team_match_seq = defaultdict(list)
    for season, season_matches in matches_by_season.items():
        season_matches.sort(key=lambda x: x['day'])
        for m in season_matches:
            team_match_seq[(season, m['home'])].append({
                'team': m['home'], 'side': 'home', 'day': m['day'],
                'outcome': m['outcome'], 'gf': m['h'], 'ga': m['a'],
                'opponent': m['away'], 'season': season
            })
            team_match_seq[(season, m['away'])].append({
                'team': m['away'], 'side': 'away', 'day': m['day'],
                'outcome': m['outcome'], 'gf': m['a'], 'ga': m['h'],
                'opponent': m['home'], 'season': season
            })
    
    # Find big losses, check next match
    big_loss_bounce = Counter()
    for key, seq in team_match_seq.items():
        seq.sort(key=lambda x: x['day'])
        for i, game in enumerate(seq):
            if game['ga'] is not None and game['gf'] is not None and game['ga'] - game['gf'] >= 3:
                if i + 1 < len(seq):
                    next_game = seq[i+1]
                    big_loss_bounce[next_game['outcome']] += 1
    
    if big_loss_bounce:
        total_bl = sum(big_loss_bounce.values())
        print(f"\n--- Bounce back after big loss (n={total_bl}) ---")
        for outcome, cnt in big_loss_bounce.most_common():
            print(f"  Next match: {outcome:>5} → {cnt} ({cnt/total_bl*100:.1f}%)")
    
    return {
        'after_3_wins': dict(after_3w_outcomes) if after_3w_outcomes else {},
        'after_2_draws': dict(after_2d_outcomes) if after_2d_outcomes else {},
        'big_loss_bounce': dict(big_loss_bounce) if big_loss_bounce else {},
    }


# ────────────────────────────────────────────────────────────────
# 7. EXPLORE 5: Seasonal position
# ────────────────────────────────────────────────────────────────
def explore_seasonal_position(matches):
    print("\n\n=== EXPLORE 5: Seasonal Position ===")
    
    # Group seasons by total matchdays
    season_days = defaultdict(set)
    for m in matches:
        season_days[m['season']].add(m['day'])
    
    season_max_day = {s: max(days) for s, days in season_days.items()}
    
    outcomes_by_day_phase = defaultdict(lambda: {'HOME': 0, 'AWAY': 0, 'DRAW': 0})
    
    for m in matches:
        max_day = season_max_day.get(m['season'], 30)
        if max_day <= 0:
            continue
        phase = m['day'] / max_day
        if phase <= 0.25:
            phase_label = 'Early (0-25%)'
        elif phase <= 0.50:
            phase_label = 'Mid-Early (25-50%)'
        elif phase <= 0.75:
            phase_label = 'Mid-Late (50-75%)'
        else:
            phase_label = 'Late (75-100%)'
        
        if m['outcome'] in outcomes_by_day_phase[phase_label]:
            outcomes_by_day_phase[phase_label][m['outcome']] += 1
    
    print(f"\n--- Outcome by Season Phase ---")
    print(f"{'Phase':<20} | {'Total':>6} | {'Home%':>7} | {'Draw%':>7} | {'Away%':>7}")
    for phase in ['Early (0-25%)', 'Mid-Early (25-50%)', 'Mid-Late (50-75%)', 'Late (75-100%)']:
        data = outcomes_by_day_phase[phase]
        total = sum(data.values())
        if total == 0:
            continue
        hp = data['HOME'] / total * 100
        dp = data['DRAW'] / total * 100
        ap = data['AWAY'] / total * 100
        print(f"{phase:<20} | {total:>6} | {hp:>6.1f}% | {dp:>6.1f}% | {ap:>6.1f}%")
    
    # Upsets: lower-ranked (based on odds) winning against odds
    # Use odds data from database or betdata
    odds_data = [m for m in matches if m.get('oh') and m.get('oa')]
    if odds_data:
        print(f"\n--- Upset rate by season phase (odds-based) ---")
        phase_odds = defaultdict(list)
        for m in odds_data:
            max_day = season_max_day.get(m['season'], 30)
            if max_day <= 0:
                continue
            phase = m['day'] / max_day
            if phase <= 0.25:
                lbl = 'Early'
            elif phase <= 0.50:
                lbl = 'Mid-Early'
            elif phase <= 0.75:
                lbl = 'Mid-Late'
            else:
                lbl = 'Late'
            
            try:
                oh = float(m['oh'])
                oa = float(m['oa'])
            except (ValueError, TypeError):
                continue
            
            # Favourite is the one with lower odds
            if oh < oa and m['outcome'] == 'AWAY':
                phase_odds[lbl].append('upset')
            elif oa < oh and m['outcome'] == 'HOME':
                phase_odds[lbl].append('upset')
            elif oh < oa and m['outcome'] == 'HOME':
                phase_odds[lbl].append('favorite_wins')
            elif oa < oh and m['outcome'] == 'AWAY':
                phase_odds[lbl].append('favorite_wins')
            else:
                phase_odds[lbl].append('draw')
        
        for lbl in ['Early', 'Mid-Early', 'Mid-Late', 'Late']:
            data = phase_odds[lbl]
            if not data:
                continue
            upsets = data.count('upset')
            fav_wins = data.count('favorite_wins')
            draws = data.count('draw')
            total = len(data)
            print(f"  {lbl:<15}: n={total:>5} | Favourite wins: {fav_wins/total*100:>5.1f}% | Upset: {upsets/total*100:>5.1f}% | Draw: {draws/total*100:>5.1f}%")
    
    # Early season vs late season goal scoring
    print(f"\n--- Goals per match by season phase ---")
    phase_goals = defaultdict(list)
    for m in matches:
        max_day = season_max_day.get(m['season'], 30)
        if max_day <= 0 or m.get('total') is None:
            continue
        phase = m['day'] / max_day
        if phase <= 0.25:
            lbl = 'Early'
        elif phase <= 0.50:
            lbl = 'Mid-Early'
        elif phase <= 0.75:
            lbl = 'Mid-Late'
        else:
            lbl = 'Late'
        phase_goals[lbl].append(m['total'])
    
    for lbl in ['Early', 'Mid-Early', 'Mid-Late', 'Late']:
        goals = phase_goals[lbl]
        if goals:
            avg = sum(goals)/len(goals)
            o25 = sum(1 for g in goals if g > 2.5)/len(goals)*100
            print(f"  {lbl:<15}: n={len(goals):>5} | Avg goals: {avg:.2f} | Over 2.5: {o25:.1f}%")


# ────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("TORIN — Pattern Recognition Analysis")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)
    
    # Load data
    print("\nLoading database...")
    db_matches = query_db()
    print(f"Loaded {len(db_matches)} matches from database")
    
    print("\nParsing betdata files...")
    betdata = parse_betdata_files()
    print(f"Parsed {len(betdata)} entries from betdata files")
    
    # All explorations
    explore_ht_lead_ft_outcome(db_matches)
    explore_first_goal(db_matches, betdata)
    matched = explore_rank_changes(betdata, db_matches)
    streak_results = explore_streaks(db_matches)
    explore_seasonal_position(db_matches)
    
    print("\n\n=== ANALYSIS COMPLETE ===")
    
    # Save results as JSON
    results = {
        'timestamp': datetime.now().isoformat(),
        'total_matches': len(db_matches),
        'total_betdata_entries': len(betdata),
    }
    
    os.makedirs(f"{DATA_DIR}/analysis", exist_ok=True)
    with open(f"{DATA_DIR}/analysis/torin-patterns.json", 'w') as f:
        json.dump(results, f, default=str, indent=2)
    
    print(f"Results saved to {DATA_DIR}/analysis/torin-patterns.json")


if __name__ == '__main__':
    main()
