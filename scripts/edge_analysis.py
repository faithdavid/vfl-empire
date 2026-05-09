#!/usr/bin/env python3
"""Cassandra — Statistical Edge Validation for VFL Betting Data"""
import sqlite3, json, math, os
from collections import defaultdict

DB = '/home/faith/Documents/Projects/vfl-data/databases/history.db'
OUT = '/home/faith/Documents/Projects/vfl-data/analysis/cassandra-edges.json'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# ── Load clean matches ──
rows = conn.execute("""
    SELECT * FROM matches
    WHERE oh > 1.0
      AND outcome IN ('HOME','AWAY','DRAW','H','A','D')
    ORDER BY season, day
""").fetchall()

print(f"Loaded {len(rows)} matches with clean odds")

# Normalize outcomes
def norm_outcome(r):
    o = r['outcome']
    if o in ('HOME', 'H'): return 'H'
    if o in ('AWAY', 'A'): return 'A'
    return 'D'

matches = []
for r in rows:
    m = dict(r)
    m['_outcome'] = norm_outcome(r)
    m['_home_win'] = 1 if m['_outcome'] == 'H' else 0
    m['_away_win'] = 1 if m['_outcome'] == 'A' else 0
    m['_draw'] = 1 if m['_outcome'] == 'D' else 0
    # Implied probabilities from odds (no margin removal — raw comparison)
    m['_imp_home'] = 1.0 / m['oh'] if m['oh'] else 0
    m['_imp_draw'] = 1.0 / m['od'] if m['od'] else 0
    m['_imp_away'] = 1.0 / m['oa'] if m['oa'] else 0
    # Parse half_time
    ht = m['half_time'] or ''
    if ':' in ht:
        parts = ht.split(':')
        try:
            m['_ht_h'] = int(parts[0])
            m['_ht_a'] = int(parts[1])
            m['_ht_diff'] = m['_ht_h'] - m['_ht_a']
        except:
            m['_ht_h'] = m['_ht_a'] = m['_ht_diff'] = None
    else:
        m['_ht_h'] = m['_ht_a'] = m['_ht_diff'] = None
    
    # Parse first_goal
    fg = (m['first_goal'] or '').strip().lower()
    if fg in ('home', 'h'):
        m['_fg'] = 'home'
    elif fg in ('away', 'a'):
        m['_fg'] = 'away'
    elif fg in ('none', '--', ''):
        m['_fg'] = 'none'
    else:
        m['_fg'] = 'none'
    
    matches.append(m)

N = len(matches)
print(f"Processed {N} matches")

# ── Helper: binomial CI ──
def binomial_ci(success, n, z=1.96):
    if n == 0: return (0, 0)
    p = success / n
    se = math.sqrt(p * (1 - p) / n)
    lo = max(0, p - z * se)
    hi = min(1, p + z * se)
    return (lo, hi)

# ── Helper: odds bracket ──
def bracket(odds):
    if odds is None or odds <= 0: return None
    if odds <= 1.20: return "1.01-1.20"
    if odds <= 1.40: return "1.21-1.40"
    if odds <= 1.60: return "1.41-1.60"
    if odds <= 1.80: return "1.61-1.80"
    if odds <= 2.00: return "1.81-2.00"
    if odds <= 2.25: return "2.01-2.25"
    if odds <= 2.50: return "2.26-2.50"
    if odds <= 2.75: return "2.51-2.75"
    if odds <= 3.00: return "2.76-3.00"
    if odds <= 3.50: return "3.01-3.50"
    if odds <= 4.00: return "3.51-4.00"
    if odds <= 5.00: return "4.01-5.00"
    if odds <= 6.50: return "5.01-6.50"
    if odds <= 10.00: return "6.51-10.00"
    return "10.01+"

results = {}

# ═══════════════════════════════════════════════════════
# Q1: What pre-match edge is statistically significant?
# ═══════════════════════════════════════════════════════
print("\n─── Q1: Pre-match edge analysis ───")

q1_brackets_home = defaultdict(lambda: {'n': 0, 'wins': 0, 'total_imp': 0.0})
q1_brackets_away = defaultdict(lambda: {'n': 0, 'wins': 0, 'total_imp': 0.0})
q1_brackets_draw = defaultdict(lambda: {'n': 0, 'wins': 0, 'total_imp': 0.0})

for m in matches:
    b = bracket(m['oh'])
    if b:
        q1_brackets_home[b]['n'] += 1
        q1_brackets_home[b]['wins'] += m['_home_win']
        q1_brackets_home[b]['total_imp'] += m['_imp_home']
    
    b = bracket(m['oa'])
    if b:
        q1_brackets_away[b]['n'] += 1
        q1_brackets_away[b]['wins'] += m['_away_win']
        q1_brackets_away[b]['total_imp'] += m['_imp_away']
    
    b = bracket(m['od'])
    if b:
        q1_brackets_draw[b]['n'] += 1
        q1_brackets_draw[b]['wins'] += m['_draw']
        q1_brackets_draw[b]['total_imp'] += m['_imp_draw']

q1_results = {'home': {}, 'away': {}, 'draw': {}}
significant_edges = []

for label, data in [('home', q1_brackets_home), ('away', q1_brackets_away), ('draw', q1_brackets_draw)]:
    for b in sorted(data.keys()):
        d = data[b]
        n = d['n']
        if n < 10: continue
        actual_rate = d['wins'] / n
        implied_rate = d['total_imp'] / n
        ci_lo, ci_hi = binomial_ci(d['wins'], n)
        is_sig = ci_lo > implied_rate
        verdict = "SIGNIFICANT" if is_sig else "NOT SIGNIFICANT"
        
        q1_results[label][b] = {
            "n": n,
            "wins": d['wins'],
            "actual_rate": round(actual_rate, 4),
            "implied_rate": round(implied_rate, 4),
            "ci_lo": round(ci_lo, 4),
            "ci_hi": round(ci_hi, 4),
            "verdict": verdict
        }
        if is_sig:
            significant_edges.append(f"{label} {b}: {d['wins']}/{n} = {actual_rate:.3f} vs implied {implied_rate:.3f}, CI [{ci_lo:.3f}, {ci_hi:.3f}]")

results['q1'] = {
    "description": "Pre-match edge by odds bracket — actual win rate vs market-implied, with binomial 95% CI",
    "total_matches": N,
    "significant_edges": significant_edges,
    "breakdown": q1_results
}

print(f"  Significant edges found: {len(significant_edges)}")
for e in significant_edges:
    print(f"    {e}")

# ═══════════════════════════════════════════════════════
# Q2: Does win quota predict individual match outcomes?
# ═══════════════════════════════════════════════════════
print("\n─── Q2: Win quota regression analysis ───")

# Build team-season stats: expected wins vs actual wins up to each match day
# For each team-season, track cumulative expectations and actual wins
# Then for each match, see if home team above/below pace predicts outcome

from collections import defaultdict

# First pass: compute team-season cumulative stats
team_season_matches = defaultdict(list)
for m in matches:
    key = (m['season'], m['home'])
    team_season_matches[key].append(m)
    key = (m['season'], m['away'])
    team_season_matches[key].append(m)

# Sort each team's matches by day
for k in team_season_matches:
    team_season_matches[k].sort(key=lambda x: x['day'])

# For each team-season, compute running stats
team_running = {}  # (season, team) -> {day: {exp_wins, actual_wins, matches_played}}
for (season, team), ms in team_season_matches.items():
    running = {}
    exp_wins = 0.0
    actual_wins = 0
    played = 0
    for m in ms:
        day = m['day']
        played += 1
        if m['home'] == team:
            exp_wins += m['_imp_home']
            if m['_home_win']: actual_wins += 1
        else:
            exp_wins += m['_imp_away']
            if m['_away_win']: actual_wins += 1
        running[day] = {'exp_wins': exp_wins, 'actual_wins': actual_wins, 'played': played}
    team_running[(season, team)] = running

# Now tag each match: is home team above/below pace BEFORE this match?
above_pace_results = {'early': [], 'mid': [], 'late': []}

for m in matches:
    day = m['day']
    home_key = (m['season'], m['home'])
    away_key = (m['season'], m['away'])
    
    # Get home team's stats BEFORE this match day
    # Find the running stats at the most recent day < current day
    home_exp_before = 0.0
    home_act_before = 0
    home_played_before = 0
    
    if home_key in team_running:
        tr = team_running[home_key]
        for d in sorted(tr.keys()):
            if d < day:
                home_exp_before = tr[d]['exp_wins']
                home_act_before = tr[d]['actual_wins']
                home_played_before = tr[d]['played']
    
    # Away team before this match
    away_exp_before = 0.0
    away_act_before = 0
    away_played_before = 0
    
    if away_key in team_running:
        tr = team_running[away_key]
        for d in sorted(tr.keys()):
            if d < day:
                away_exp_before = tr[d]['exp_wins']
                away_act_before = tr[d]['actual_wins']
                away_played_before = tr[d]['played']
    
    # Determine pace
    home_above = False
    if home_played_before >= 3:  # Need at least 3 matches for meaningful pace
        home_above = home_act_before > home_exp_before
    
    # Match phase
    if day <= 10:
        phase = 'early'
    elif day <= 20:
        phase = 'mid'
    else:
        phase = 'late'
    
    # For regression: does home_above predict home_win?
    above_pace_results[phase].append({
        'home_above': home_above,
        'home_win': m['_home_win'],
        'home_exp_before': home_exp_before,
        'home_act_before': home_act_before,
        'home_played': home_played_before,
        'draw': m['_draw'],
        'away_win': m['_away_win']
    })

q2_results = {}
for phase in ['early', 'mid', 'late']:
    data = above_pace_results[phase]
    above = [d for d in data if d['home_above'] and d['home_played'] >= 3]
    below = [d for d in data if not d['home_above'] and d['home_played'] >= 3]
    
    above_n = len(above)
    below_n = len(below)
    above_wins = sum(d['home_win'] for d in above)
    below_wins = sum(d['home_win'] for d in below)
    
    above_rate = above_wins / above_n if above_n > 0 else 0
    below_rate = below_wins / below_n if below_n > 0 else 0
    
    above_ci = binomial_ci(above_wins, above_n) if above_n >= 10 else (0, 0)
    below_ci = binomial_ci(below_wins, below_n) if below_n >= 10 else (0, 0)
    
    # Regression hypothesis: teams above pace should regress (win LESS)
    # So above_pace win rate should be LOWER than below_pace win rate
    regression_predicted = above_rate < below_rate
    
    # Statistical test: two-proportion z-test
    p1 = above_rate
    p2 = below_rate
    if above_n > 0 and below_n > 0:
        p_pool = (above_wins + below_wins) / (above_n + below_n)
        se = math.sqrt(p_pool * (1 - p_pool) * (1/above_n + 1/below_n))
        if se > 0:
            z_stat = (p1 - p2) / se
        else:
            z_stat = 0
    else:
        z_stat = 0
    
    verdict = "NOT SIGNIFICANT"
    if above_n >= 30 and below_n >= 30:
        if regression_predicted:
            verdict = "SIGNIFICANT (regression observed)" if abs(z_stat) > 1.96 else "WEAK (direction correct, not stat sig)"
    
    q2_results[phase] = {
        "above_pace": {
            "n": above_n,
            "home_wins": above_wins,
            "win_rate": round(above_rate, 4),
            "ci": [round(above_ci[0], 4), round(above_ci[1], 4)]
        },
        "below_pace": {
            "n": below_n,
            "home_wins": below_wins,
            "win_rate": round(below_rate, 4),
            "ci": [round(below_ci[0], 4), round(below_ci[1], 4)]
        },
        "regression_observed": regression_predicted,
        "z_statistic": round(z_stat, 4),
        "verdict": verdict
    }
    print(f"  {phase} (MD {'1-10' if phase == 'early' else '11-20' if phase == 'mid' else '21-30'}): above={above_n}, below={below_n}, above_rate={above_rate:.3f}, below_rate={below_rate:.3f}, z={z_stat:.3f}, {verdict}")

results['q2'] = {
    "description": "Win quota regression — does a team above/below expected win pace predict next outcome?",
    "total_matches_analyzed": sum(len(d) for d in above_pace_results.values()),
    "phases": q2_results
}

# ═══════════════════════════════════════════════════════
# Q3: What's the real value of HT lead signal?
# ═══════════════════════════════════════════════════════
print("\n─── Q3: Half-time lead signal analysis ───")

ht_outcomes = defaultdict(lambda: {'total': 0, 'home_win': 0, 'draw': 0, 'away_win': 0, 'home_goals': 0, 'away_goals': 0})

for m in matches:
    diff = m['_ht_diff']
    if diff is None: continue
    ht_outcomes[diff]['total'] += 1
    ht_outcomes[diff]['home_win'] += m['_home_win']
    ht_outcomes[diff]['draw'] += m['_draw']
    ht_outcomes[diff]['away_win'] += m['_away_win']
    ht_outcomes[diff]['home_goals'] += (m['h'] or 0)
    ht_outcomes[diff]['away_goals'] += (m['a'] or 0)

q3_results = {}
for diff in sorted(ht_outcomes.keys()):
    d = ht_outcomes[diff]
    n = d['total']
    if n < 5: continue
    hw_rate = d['home_win'] / n
    d_rate = d['draw'] / n
    aw_rate = d['away_win'] / n
    
    ci = binomial_ci(d['home_win'], n) if diff > 0 else binomial_ci(d['away_win'], n) if diff < 0 else binomial_ci(d['draw'], n)
    
    # HT lead reliability: e.g., if HT +1, what % become FT home wins?
    if diff > 0:
        signal_strength = f"{hw_rate:.1%} home win from HT +{diff}"
        reliable = hw_rate > 0.60
    elif diff < 0:
        signal_strength = f"{aw_rate:.1%} away win from HT {diff}"
        reliable = aw_rate > 0.60
    else:
        signal_strength = f"{hw_rate:.1%} home / {d_rate:.1%} draw / {aw_rate:.1%} away from HT draw"
        reliable = d_rate > 0.30  # draws are relevant from HT draw
    
    q3_results[f"HT_{diff:+d}"] = {
        "n": n,
        "home_win_pct": round(hw_rate, 4),
        "draw_pct": round(d_rate, 4),
        "away_win_pct": round(aw_rate, 4),
        "avg_ft_home_goals": round(d['home_goals'] / n, 2),
        "avg_ft_away_goals": round(d['away_goals'] / n, 2),
        "ht_diff": diff,
        "ci": [round(ci[0], 4), round(ci[1], 4)],
        "reliable_signal": reliable,
        "note": signal_strength
    }
    print(f"  HT {diff:+d}: n={n}, HW={hw_rate:.3f}, D={d_rate:.3f}, AW={aw_rate:.3f}, reliable={reliable}")

results['q3'] = {
    "description": "Half-time lead signal — FT outcome distribution by HT score differential",
    "total_matches_with_ht": sum(d['total'] for d in ht_outcomes.values()),
    "ht_differentials": q3_results
}

# ═══════════════════════════════════════════════════════
# Q4: First goal = lock?
# ═══════════════════════════════════════════════════════
print("\n─── Q4: First goal analysis ───")

# Overall first goal → win rate
fg_outcomes = defaultdict(lambda: {'n': 0, 'home_win': 0, 'draw': 0, 'away_win': 0})

for m in matches:
    fg = m['_fg']
    if fg == 'none': continue
    fg_outcomes[fg]['n'] += 1
    fg_outcomes[fg]['home_win'] += m['_home_win']
    fg_outcomes[fg]['draw'] += m['_draw']
    fg_outcomes[fg]['away_win'] += m['_away_win']

q4_overall = {}
for fg in ['home', 'away']:
    d = fg_outcomes[fg]
    n = d['n']
    if n == 0: continue
    win_rate = d['home_win'] / n if fg == 'home' else d['away_win'] / n
    draw_rate = d['draw'] / n
    ci = binomial_ci(d['home_win'] if fg == 'home' else d['away_win'], n)
    q4_overall[fg] = {
        "n": n,
        "home_win_pct": round(d['home_win'] / n, 4),
        "draw_pct": round(d['draw'] / n, 4),
        "away_win_pct": round(d['away_win'] / n, 4),
        "team_scoring_first_win_rate": round(win_rate, 4),
        "ci": [round(ci[0], 4), round(ci[1], 4)]
    }
    print(f"  First goal {fg}: n={n}, win_rate={win_rate:.3f}, CI [{ci[0]:.3f}, {ci[1]:.3f}]")

# First goal × odds bracket (does first goal matter more for underdogs?)
fg_bracket = defaultdict(lambda: {'n': 0, 'fg_home_wins': 0, 'fg_away_wins': 0, 'fg_home_n': 0, 'fg_away_n': 0})

for m in matches:
    fg = m['_fg']
    if fg == 'none': continue
    b_home = bracket(m['oh'])
    if b_home:
        key = ('home_odds', b_home)
        fg_bracket[key]['n'] += 1
        if fg == 'home':
            fg_bracket[key]['fg_home_n'] += 1
            fg_bracket[key]['fg_home_wins'] += m['_home_win']
        elif fg == 'away':
            fg_bracket[key]['fg_away_n'] += 1
            fg_bracket[key]['fg_away_wins'] += m['_away_win']

q4_bracket = {}
for key in sorted(fg_bracket.keys()):
    d = fg_bracket[key]
    _, b = key
    
    home_fg_rate = d['fg_home_wins'] / d['fg_home_n'] if d['fg_home_n'] >= 10 else None
    away_fg_rate = d['fg_away_wins'] / d['fg_away_n'] if d['fg_away_n'] >= 10 else None
    
    # Underdog effect: when underdog (higher odds) scores first, do they win more?
    entry = {"n": d['n'], "bracket": b}
    
    if home_fg_rate is not None:
        ci = binomial_ci(d['fg_home_wins'], d['fg_home_n'])
        entry["home_scores_first"] = {
            "n": d['fg_home_n'],
            "home_win_rate": round(home_fg_rate, 4),
            "ci": [round(ci[0], 4), round(ci[1], 4)]
        }
    
    if away_fg_rate is not None:
        ci = binomial_ci(d['fg_away_wins'], d['fg_away_n'])
        entry["away_scores_first"] = {
            "n": d['fg_away_n'],
            "away_win_rate": round(away_fg_rate, 4),
            "ci": [round(ci[0], 4), round(ci[1], 4)]
        }
    
    if entry:
        q4_bracket[str(key)] = entry

results['q4'] = {
    "description": "First goal analysis — FT win rate when home/away scores first, by odds bracket",
    "overall": q4_overall,
    "by_bracket": q4_bracket
}

# ═══════════════════════════════════════════════════════
# Q5: Bracket × Tier interaction
# ═══════════════════════════════════════════════════════
print("\n─── Q5: Bracket × Tier interaction ───")

# No tier data in database. Derive proxy tiers from odds brackets.
# Home odds bracket serves as proxy for team strength tier.
# "Tier" of home = odds bracket, "tier" of away = odds bracket
# Then cross-tabulate: for each home_tier × away_tier, actual win rate vs implied

tier_cross = defaultdict(lambda: {'n': 0, 'home_wins': 0, 'draws': 0, 'away_wins': 0, 'total_imp_home': 0.0, 'total_imp_draw': 0.0, 'total_imp_away': 0.0})

# Broad tier groups for clarity
def broad_tier(odds):
    if odds is None or odds <= 0: return None
    if odds <= 1.80: return "T1-Favorite"
    if odds <= 2.50: return "T2-Moderate"
    if odds <= 3.50: return "T3-Underdog"
    return "T4-Longshot"

for m in matches:
    ht = broad_tier(m['oh'])
    at = broad_tier(m['oa'])
    if ht is None or at is None: continue
    
    key = f"{ht}_vs_{at}"
    tier_cross[key]['n'] += 1
    tier_cross[key]['home_wins'] += m['_home_win']
    tier_cross[key]['draws'] += m['_draw']
    tier_cross[key]['away_wins'] += m['_away_win']
    tier_cross[key]['total_imp_home'] += m['_imp_home']
    tier_cross[key]['total_imp_draw'] += m['_imp_draw']
    tier_cross[key]['total_imp_away'] += m['_imp_away']

q5_results = {}
for key in sorted(tier_cross.keys()):
    d = tier_cross[key]
    n = d['n']
    if n < 10: continue
    
    actual_home = d['home_wins'] / n
    actual_draw = d['draws'] / n
    actual_away = d['away_wins'] / n
    imp_home = d['total_imp_home'] / n
    imp_draw = d['total_imp_draw'] / n
    imp_away = d['total_imp_away'] / n
    
    ci_home = binomial_ci(d['home_wins'], n)
    ci_away = binomial_ci(d['away_wins'], n)
    
    # Market wrong if actual outside CI of implied? 
    # More precisely: if actual significantly differs from implied
    market_wrong_home = ci_home[0] > imp_home or ci_home[1] < imp_home
    market_wrong_away = ci_away[0] > imp_away or ci_away[1] < imp_away
    
    wrong_notes = []
    if ci_home[0] > imp_home:
        wrong_notes.append(f"HOME edge: actual {actual_home:.3f} >> implied {imp_home:.3f}")
    if ci_home[1] < imp_home:
        wrong_notes.append(f"HOME overvalued: actual {actual_home:.3f} << implied {imp_home:.3f}")
    if ci_away[0] > imp_away:
        wrong_notes.append(f"AWAY edge: actual {actual_away:.3f} >> implied {imp_away:.3f}")
    if ci_away[1] < imp_away:
        wrong_notes.append(f"AWAY overvalued: actual {actual_away:.3f} << implied {imp_away:.3f}")
    
    q5_results[key] = {
        "n": n,
        "actual": {
            "home_win": round(actual_home, 4),
            "draw": round(actual_draw, 4),
            "away_win": round(actual_away, 4)
        },
        "implied": {
            "home_win": round(imp_home, 4),
            "draw": round(imp_draw, 4),
            "away_win": round(imp_away, 4)
        },
        "ci_home": [round(ci_home[0], 4), round(ci_home[1], 4)],
        "ci_away": [round(ci_away[0], 4), round(ci_away[1], 4)],
        "market_mispriced": len(wrong_notes) > 0,
        "notes": wrong_notes
    }
    
    if wrong_notes:
        print(f"  {key} (n={n}): MISMATCH — {'; '.join(wrong_notes)}")

results['q5'] = {
    "description": "Bracket × Tier interaction — actual vs implied win rates by tier matchup (proxy: odds-based tiers)",
    "tier_method": "Odds-based proxy tiers: T1-Favorite (≤1.80), T2-Moderate (1.81-2.50), T3-Underdog (2.51-3.50), T4-Longshot (3.51+)",
    "note": "No explicit tier/league data in DB; tiers derived from pre-match odds brackets",
    "cross_tabulation": q5_results
}

# ═══════════════════════════════════════════════════════
# Executive summary
# ═══════════════════════════════════════════════════════
results['executive_summary'] = {
    "total_matches": N,
    "matches_with_ht_data": sum(1 for m in matches if m['_ht_diff'] is not None),
    "matches_with_fg_data": sum(1 for m in matches if m['_fg'] != 'none'),
    "q1_significant_edges": len(significant_edges),
    "q2_regression_found": any(
        q2_results[p].get('verdict', '').startswith('SIGNIFICANT') 
        for p in q2_results
    ),
    "q3_ht_signals_reliable": sum(
        1 for k, v in q3_results.items() if v.get('reliable_signal')
    ),
    "q4_first_goal_lock": q4_overall.get('home', {}).get('team_scoring_first_win_rate', 0) > 0.65,
    "q5_mispriced_tiers": sum(
        1 for k, v in q5_results.items() if v.get('market_mispriced')
    )
}

# ── Write output ──
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n✅ Results written to {OUT}")
print(f"   {N} matches analyzed")
print(f"   Q1: {len(significant_edges)} significant edges")
print(f"   Q3: {sum(1 for k,v in q3_results.items() if v.get('reliable_signal'))} reliable HT signals")
print(f"   Q4: Home scores first → win {q4_overall.get('home', {}).get('team_scoring_first_win_rate', 0):.1%}")
print(f"   Q5: {sum(1 for k,v in q5_results.items() if v.get('market_mispriced'))} mispriced tier matchups")
