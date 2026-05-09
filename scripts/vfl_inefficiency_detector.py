#!/usr/bin/env python3
"""
VFL Market Inefficiency Detector — True Unsupervised Learning
============================================================

NOT predictor of outcomes. DETECTOR of market errors.

Framework:
  1. For each match: determine if the odds favorite was CORRECT or WRONG
  2. Cluster matches by conditions → find where market FAILS
  3. Validate clusters walk-forward: do they persist?
  4. Only bet where the edge is REAL (persistent across seasons)

The progressive improvement comes from FILTERING, not from better H/D/A guesses.
Each season, we learn which conditions to AVOID and which to EXPLOIT.
"""

import numpy as np
import sqlite3, json
from collections import defaultdict, Counter
from math import exp, log

np.random.seed(42)

# ============================================================
# DATA LOADING
# ============================================================

def load_all_data():
    all_matches = []
    
    def norm_team(t):
        if not t: return ''
        return t.strip().title()
    
    def outcome_int(o):
        o = str(o).upper().strip()
        if o in ('HOME', 'H', '1'): return 0
        if o in ('DRAW', 'D', 'X'): return 1
        if o in ('AWAY', 'A', '2'): return 2
        return None
    
    conn = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT season, day, home, away, oh, od, oa, outcome
        FROM matches 
        WHERE oh IS NOT NULL AND od IS NOT NULL AND oa IS NOT NULL
          AND outcome IS NOT NULL AND outcome != ''
          AND oh > 0 AND od > 0 AND oa > 0
        ORDER BY season, day
    """)
    for r in cur.fetchall():
        oi = outcome_int(r['outcome'])
        if oi is None: continue
        all_matches.append({
            'season': r['season'], 'md': r['day'],
            'home': norm_team(r['home']), 'away': norm_team(r['away']),
            'oh': float(r['oh']), 'od': float(r['od']), 'oa': float(r['oa']),
            'outcome': oi,
        })
    conn.close()
    
    conn2 = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/sovereign.db')
    conn2.row_factory = sqlite3.Row
    cur2 = conn2.cursor()
    cur2.execute("""
        SELECT season_id, match_day, home_team, away_team, odds_h, odds_d, odds_a, outcome
        FROM master_ledger 
        WHERE odds_h IS NOT NULL AND odds_d IS NOT NULL AND odds_a IS NOT NULL
          AND outcome IS NOT NULL AND outcome != ''
          AND odds_h > 0 AND odds_d > 0 AND odds_a > 0
    """)
    existing = set()
    for m in all_matches:
        existing.add((m['season'], m['md'], m['home'], m['away']))
    for r in cur2.fetchall():
        oi = outcome_int(r['outcome'])
        if oi is None: continue
        home = norm_team(r['home_team']); away = norm_team(r['away_team'])
        key = (r['season_id'], r['match_day'], home, away)
        if key not in existing:
            all_matches.append({
                'season': r['season_id'], 'md': r['match_day'],
                'home': home, 'away': away,
                'oh': float(r['odds_h']), 'od': float(r['odds_d']), 'oa': float(r['odds_a']),
                'outcome': oi,
            })
    conn2.close()
    
    return all_matches


# ============================================================
# FEATURE ENGINEERING — Match conditions
# ============================================================

def compute_match_features(oh, od, oa, md=15):
    """
    Compute features that describe the MATCH CONDITIONS.
    NOT for predicting outcomes — for clustering market efficiency.
    """
    # Vig-free implied probabilities
    inv_h, inv_d, inv_a = 1.0/oh, 1.0/od, 1.0/oa
    total_inv = inv_h + inv_d + inv_a
    p_h, p_d, p_a = inv_h/total_inv, inv_d/total_inv, inv_a/total_inv
    
    # Odds favorite
    min_odds = min(oh, od, oa)
    if min_odds == oh: fav = 0  # HOME fav
    elif min_odds == od: fav = 1  # DRAW fav
    else: fav = 2  # AWAY fav
    
    # Market confidence: how strong is the favorite?
    fav_prob = max(p_h, p_d, p_a)
    second_prob = sorted([p_h, p_d, p_a])[1]
    confidence_gap = fav_prob - second_prob
    
    # The odds favorite's implied probability
    fav_implied = [p_h, p_d, p_a][fav]
    
    # Draw attractiveness: how much does the market price draws?
    draw_attract = p_d / ((p_h + p_a) / 2)
    
    # Home edge
    home_edge = p_h - p_a
    
    return {
        'fav': fav,
        'fav_implied': fav_implied,
        'p_h': p_h, 'p_d': p_d, 'p_a': p_a,
        'confidence_gap': confidence_gap,
        'draw_attract': draw_attract,
        'home_edge': home_edge,
        'oh': oh, 'od': od, 'oa': oa,
        'odds_ratio_hd': oh/od,
        'odds_ratio_ha': oh/oa,
        'odds_ratio_da': od/oa,
    }


# ============================================================
# MARKET EFFICIENCY CLUSTERING
# ============================================================

def build_condition_signature(mf):
    """
    Create a discrete condition signature for clustering.
    Buckets continuous features into bins.
    """
    # Odds favorite type
    fav_map = {0: 'H_FAV', 1: 'D_FAV', 2: 'A_FAV'}
    fav_type = fav_map[mf['fav']]
    
    # Favorite strength
    fi = mf['fav_implied']
    if fi >= 0.65: strength = 'HEAVY'       # >65% win prob
    elif fi >= 0.55: strength = 'FAV'       # 55-65%
    elif fi >= 0.45: strength = 'SLIGHT'    # 45-55%
    elif fi >= 0.35: strength = 'TOSS'      # 35-45%
    else: strength = 'DOG'                  # <35%
    
    # Draw attract
    da = mf['draw_attract']
    if da >= 1.2: draw_z = 'HIGH_DRAW'
    elif da >= 0.9: draw_z = 'NORM_DRAW'
    else: draw_z = 'LOW_DRAW'
    
    # Confidence gap
    cg = mf['confidence_gap']
    if cg >= 0.20: cg_bucket = 'BIG_GAP'       # Clear favorite
    elif cg >= 0.10: cg_bucket = 'MED_GAP'
    else: cg_bucket = 'TIGHT'                   # Very close
    
    return f"{fav_type}|{strength}|{draw_z}|{cg_bucket}"


# ============================================================
# WALK-FORWARD INEFFICIENCY DETECTION
# ============================================================

print("=" * 85)
print("VFL MARKET INEFFICIENCY DETECTOR")
print("True Unsupervised Learning: Find where the market fails")
print("=" * 85)

all_matches = load_all_data()
print(f"\nLoaded {len(all_matches)} matches")

# Group by season
def season_sort(s):
    parts = str(s).replace('vf:season:', '').split('_')
    return int(parts[0])

season_matches = defaultdict(list)
for m in all_matches:
    season_matches[m['season']].append(m)
sorted_seasons = sorted([s for s in season_matches if len(season_matches[s]) >= 10], key=season_sort)
print(f"Seasons (≥10 matches): {len(sorted_seasons)}")

# ============================================================
# INEFFICIENCY TRACKER
# ============================================================

# Tracks for each condition signature: how often the market was wrong
inefficiency_db = defaultdict(lambda: {
    'total': 0, 'market_wrong': 0, 'market_right': 0,
    'seasons_seen': set(),
    'actual_outcomes': Counter(),
})

# Track which conditions we USE for betting
active_edges = {}  # signature -> edge info

def evaluate_market(match):
    """Is the odds favorite correct? Returns (fav, fav_correct, actual_outcome)."""
    mf = compute_match_features(match['oh'], match['od'], match['oa'], match['md'])
    fav = mf['fav']
    fav_correct = (fav == match['outcome'])
    return fav, fav_correct, match['outcome']

def inefficiency_rate(db_entry):
    """How often is the market wrong for this condition?"""
    if db_entry['total'] < 5:
        return 0.0
    return db_entry['market_wrong'] / db_entry['total']

def edge_confidence(db_entry):
    """
    How confident are we that this inefficiency is REAL (not noise)?
    Based on: sample size, consistency across seasons, effect size.
    """
    if db_entry['total'] < 10:
        return 0.0
    
    effect = db_entry['market_wrong'] / db_entry['total']
    # Baseline: market should be right ~50% of the time (depends on sport)
    # In VFL, odds favorite wins ~50.4% of the time
    baseline = 0.496  # Market wrong rate baseline
    lift = effect - baseline
    
    if lift <= 0:
        return 0.0
    
    # Season consistency
    n_seasons = len(db_entry['seasons_seen'])
    season_factor = min(1.0, n_seasons / 3)  # Need 3+ seasons for confidence
    
    # Sample size factor
    sample_factor = min(1.0, db_entry['total'] / 50)  # Need 50+ samples
    
    return lift * season_factor * sample_factor


print(f"\n{'='*85}")
print(f"WALK-FORWARD: MARKET EFFICIENCY ANALYSIS")
print(f"{'='*85}")

# Process first season (no prediction, just learn)
first_season = sorted_seasons[0]
for m in season_matches[first_season]:
    sig = build_condition_signature(compute_match_features(m['oh'], m['od'], m['oa'], m['md']))
    fav, fav_correct, actual = evaluate_market(m)
    inefficiency_db[sig]['total'] += 1
    inefficiency_db[sig]['seasons_seen'].add(m['season'])
    inefficiency_db[sig]['actual_outcomes'][actual] += 1
    if not fav_correct:
        inefficiency_db[sig]['market_wrong'] += 1
    else:
        inefficiency_db[sig]['market_right'] += 1

print(f"\nAfter season 1 ({first_season}): {len(inefficiency_db)} conditions tracked")

# Walk-forward: predict blind for each season
season_reports = []

for season_idx, season in enumerate(sorted_seasons[1:]):
    matches = season_matches[season]
    
    # Find active edges (conditions with persistent inefficiency)
    active_edges = {}
    for sig, db in inefficiency_db.items():
        conf = edge_confidence(db)
        if conf > 0:  # Any non-zero edge
            active_edges[sig] = {
                'confidence': conf,
                'inefficiency_rate': inefficiency_rate(db),
                'sample': db['total'],
                'seasons': len(db['seasons_seen']),
                'favored_outcome': db['actual_outcomes'].most_common(1)[0][0] if db['actual_outcomes'] else None,
            }
    
    # Make predictions using only active edges
    blind_predictions = []
    for m in matches:
        mf = compute_match_features(m['oh'], m['od'], m['oa'], m['md'])
        sig = build_condition_signature(mf)
        
        if sig in active_edges:
            edge = active_edges[sig]
            # Market is inefficient in this condition → bet AGAINST the favorite
            fav = mf['fav']
            
            # What does the actual outcome distribution look like for this condition?
            db = inefficiency_db[sig]
            outcome_counts = db['actual_outcomes']
            total = sum(outcome_counts.values())
            
            if total >= 5:
                # Pick the most common actual outcome (not the odds favorite)
                # This is learned from what ACTUALLY happens in this condition
                actual_best = outcome_counts.most_common(1)[0][0]
                
                if actual_best != fav:
                    # We have an edge: market favors X but reality favors Y
                    pred = actual_best
                    conf = min(edge['confidence'] * 100, 65)
                    betting = True
                else:
                    # The most common outcome IS the favorite — no edge
                    pred = fav  # Go with market
                    conf = 35
                    betting = False
            else:
                pred = fav
                conf = 33
                betting = False
        else:
            # No known edge — go with the market favorite
            pred = compute_match_features(m['oh'], m['od'], m['oa'], m['md'])['fav']
            conf = 33
            betting = False
        
        blind_predictions.append({
            'match': m,
            'pred': pred,
            'conf': conf,
            'betting': betting,
            'actual': m['outcome'],
            'correct': pred == m['outcome'],
            'signature': sig,
            'had_edge': sig in active_edges,
        })
    
    # After predicting blind, LEARN from actuals
    for m, bp in zip(matches, blind_predictions):
        sig = build_condition_signature(compute_match_features(m['oh'], m['od'], m['oa'], m['md']))
        fav, fav_correct, actual = evaluate_market(m)
        inefficiency_db[sig]['total'] += 1
        inefficiency_db[sig]['seasons_seen'].add(m['season'])
        inefficiency_db[sig]['actual_outcomes'][actual] += 1
        if not fav_correct:
            inefficiency_db[sig]['market_wrong'] += 1
        else:
            inefficiency_db[sig]['market_right'] += 1
    
    # Report for this season
    total = len(blind_predictions)
    correct = sum(1 for bp in blind_predictions if bp['correct'])
    edge_bets = [bp for bp in blind_predictions if bp['betting']]
    edge_correct = sum(1 for bp in edge_bets if bp['correct'])
    edge_total = len(edge_bets)
    flat_acc = correct / total * 100 if total else 0
    edge_acc = edge_correct / edge_total * 100 if edge_total else 0
    
    season_reports.append({
        'season': season,
        'total': total,
        'correct': correct,
        'accuracy': flat_acc,
        'edge_bets': edge_total,
        'edge_correct': edge_correct,
        'edge_accuracy': edge_acc,
        'active_edges': len(active_edges),
        'conditions_tracked': len(inefficiency_db),
    })
    
    # Print progress bar
    bar = '█' * int(edge_acc / 5) + '░' * max(0, 20 - int(edge_acc / 5)) if edge_total > 0 else '░' * 20
    progress = f"{season_idx+1}/{len(sorted_seasons)-1}"
    print(f"  [{progress:5s}] Season={str(season)[-16:]:16s} | All:{flat_acc:5.1f}% | Edges:{edge_acc:5.1f}% ({edge_correct}/{edge_total}) | Conds:{len(inefficiency_db):4d} | Active:{len(active_edges):3d} {bar}")


# ============================================================
# FINAL REPORT
# ============================================================
print(f"\n{'='*85}")
print(f"FINAL RESULTS — {len(season_reports)} seasons")
print(f"{'='*85}")

all_correct = sum(r['correct'] for r in season_reports)
all_total = sum(r['total'] for r in season_reports)
all_edge_correct = sum(r['edge_correct'] for r in season_reports)
all_edge_total = sum(r['edge_bets'] for r in season_reports)

overall_acc = all_correct / all_total * 100
edge_overall = all_edge_correct / all_edge_total * 100 if all_edge_total else 0

print(f"\n  Overall accuracy (all picks):  {all_correct}/{all_total} = {overall_acc:.2f}%")
print(f"  Edge bet accuracy:             {all_edge_correct}/{all_edge_total} = {edge_overall:.2f}%")
print(f"  Edge bet frequency:            {all_edge_total}/{all_total} = {all_edge_total/all_total*100:.1f}%")
print(f"  Conditions discovered:         {len(inefficiency_db)}")

# Progression
first_5 = np.mean([r['edge_accuracy'] for r in season_reports[:5] if r['edge_bets'] > 0] or [0])
last_5 = np.mean([r['edge_accuracy'] for r in season_reports[-5:] if r['edge_bets'] > 0] or [0])
print(f"  Edge acc first 5 seasons:      {first_5:.1f}%")
print(f"  Edge acc last 5 seasons:       {last_5:.1f}%")
print(f"  Edge improvement:              {last_5 - first_5:+.1f}pp")

# Best performing conditions
print(f"\n   Top market inefficiencies (conditions where market fails most):")
sorted_conds = sorted(inefficiency_db.items(), key=lambda x: -x[1]['market_wrong']/max(x[1]['total'], 1))
for sig, db in sorted_conds[:10]:
    ir = db['market_wrong'] / max(db['total'], 1) * 100
    n_seasons = len(db['seasons_seen'])
    most_common = db['actual_outcomes'].most_common(1)
    mc_outcome = ['HOME', 'DRAW', 'AWAY'][most_common[0][0]] if most_common else '?'
    print(f"    {sig:40s} | Market wrong {ir:5.1f}% | n={db['total']:3d} | {n_seasons:2d} seasons | Usually {mc_outcome}")

# Show which edges have the best lift
print(f"\n   Best persistent edges (highest confidence):")
best_edges = sorted(active_edges.items(), key=lambda x: -x[1]['confidence'])[:10]
for sig, edge in best_edges:
    print(f"    {sig:40s} | Conf: {edge['confidence']:.3f} | Wrong: {edge['inefficiency_rate']*100:.0f}% | n={edge['sample']} | {edge['seasons']}seasons")

# Wald filter validation: does it identify the same conditions?
print(f"\n   Wald filter cross-check:")
wald_conditions = [
    "H_FAV|SLIGHT|HIGH_DRAW|TIGHT",  # Moderate home fav with high draw odds
    "H_FAV|FAV|HIGH_DRAW|MED_GAP",   # Home fav with draw attraction
    "A_FAV|SLIGHT|HIGH_DRAW|TIGHT",  # Away slight fav with high draw
]
for wc in wald_conditions:
    if wc in inefficiency_db:
        db = inefficiency_db[wc]
        ir = db['market_wrong'] / max(db['total'], 1) * 100
        print(f"    ✅ {wc:45s} | Market wrong {ir:5.1f}% | n={db['total']:3d} | {len(db['seasons_seen']):2d} seasons")
    else:
        similar = [s for s in inefficiency_db if wc.split('|')[0] in s]
        if similar:
            print(f"    ⚠️ {wc:45s} | Not exact. Similar: {similar[0]}")
        else:
            print(f"    ❌ {wc:45s} | Not found in data")

# Save
with open('/tmp/market_inefficiency_results.json', 'w') as f:
    json.dump({
        'overall_accuracy': overall_acc,
        'edge_accuracy': edge_overall,
        'edge_total': all_edge_total,
        'total_matches': all_total,
        'season_reports': season_reports,
        'top_inefficiencies': {k: {'wrong_rate': v['market_wrong']/max(v['total'],1), 
                                    'total': v['total'], 
                                    'seasons': len(v['seasons_seen']),
                                    'most_common': int(v['actual_outcomes'].most_common(1)[0][0]) if v['actual_outcomes'] else None}
                               for k, v in sorted_conds[:20]},
    }, f, indent=2)

print(f"\nResults saved to /tmp/market_inefficiency_results.json")
