#!/usr/bin/env python3
"""
VFL Walk-Forward v2 — with Wald Anti-Miss Filter Integration

Compares: 
  (A) Simple odds-bracket learning (baseline)
  (B) Odds-bracket + Wald anti-miss rules (corrected)

Each season predicted BLIND using only data from prior seasons.
"""
import sqlite3, json
from collections import defaultdict, Counter
import sys
sys.path.insert(0, '/home/faith/Documents/Projects/vfl-data/scripts')
from wald_filter import WaldFilter

def norm_team(t):
    if not t: return ''
    return t.strip().title()

def norm_outcome(o):
    o = str(o).upper().strip()
    if o in ('HOME', 'H', '1'): return 'H'
    if o in ('DRAW', 'D', 'X'): return 'D'
    if o in ('AWAY', 'A', '2'): return 'A'
    return '?'

# ========================
# Load ALL data
# ========================
all_matches = []

conn = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("""
    SELECT season, day, home, away, oh, od, oa, outcome, h, a
    FROM matches 
    WHERE oh IS NOT NULL AND od IS NOT NULL AND oa IS NOT NULL
      AND outcome IS NOT NULL AND outcome != ''
      AND oh > 0 AND od > 0 AND oa > 0
    ORDER BY season, day
""")
for r in cur.fetchall():
    outcome = norm_outcome(r['outcome'])
    if outcome == '?': continue
    all_matches.append({
        'season': r['season'],
        'md': r['day'],
        'home': norm_team(r['home']),
        'away': norm_team(r['away']),
        'odds_h': float(r['oh']),
        'odds_d': float(r['od']),
        'odds_a': float(r['oa']),
        'outcome': outcome,
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
for r in cur2.fetchall():
    outcome = norm_outcome(r['outcome'])
    if outcome == '?': continue
    dupe = False
    for m in all_matches:
        if m['season'] == r['season_id'] and m['md'] == r['match_day'] and m['home'] == norm_team(r['home_team']) and m['away'] == norm_team(r['away_team']):
            dupe = True
            break
    if not dupe:
        all_matches.append({
            'season': r['season_id'],
            'md': r['match_day'],
            'home': norm_team(r['home_team']),
            'away': norm_team(r['away_team']),
            'odds_h': float(r['odds_h']),
            'odds_d': float(r['odds_d']),
            'odds_a': float(r['odds_a']),
            'outcome': outcome,
        })
conn2.close()

# Group by season
def season_sort_key(s):
    parts = s.replace('vf:season:', '').split('_')
    return int(parts[0])

season_matches = defaultdict(list)
for m in all_matches:
    season_matches[m['season']].append(m)

sorted_seasons = sorted(season_matches.keys(), key=season_sort_key)
print(f"Total matches: {len(all_matches)}, Seasons: {len(sorted_seasons)}")

# ========================
# Walk-Forward Engine (Baseline)
# ========================
class WalkForwardBaseline:
    def __init__(self):
        self.odd_bracket_stats = defaultdict(lambda: {'H': 0, 'D': 0, 'A': 0, 'total': 0})
        self.total_trained = 0
    
    def get_bracket(self, oh, od, oa):
        min_odds = min(oh, od, oa)
        if min_odds == oh: fav_type = 'H_FAV'
        elif min_odds == od: fav_type = 'D_FAV'
        else: fav_type = 'A_FAV'
        if min_odds < 1.5: bracket = 'HEAVY'
        elif min_odds < 2.0: bracket = 'FAV'
        elif min_odds < 3.0: bracket = 'SLIGHT'
        else: bracket = 'LONG'
        return f"{fav_type}_{bracket}"
    
    def train(self, m, was_miss=False):
        bracket = self.get_bracket(m['odds_h'], m['odds_d'], m['odds_a'])
        self.odd_bracket_stats[bracket][m['outcome']] += 1
        self.odd_bracket_stats[bracket]['total'] += 1
        self.total_trained += 1
    
    def predict(self, oh, od, oa):
        bracket = self.get_bracket(oh, od, oa)
        data = self.odd_bracket_stats[bracket]
        if data['total'] >= 3:
            rates = [(k, v/data['total']) for k, v in data.items() if k != 'total']
            best = max(rates, key=lambda x: x[1])
            return best[0], round(best[1]*100, 1)
        return 'H', 33.3


# ========================
# WALK-FORWARD TEST
# ========================
print(f"\n{'='*70}")
print(f"WALK-FORWARD: BASELINE (Odds-Bracket Only)")
print(f"{'='*70}")

baseline = WalkForwardBaseline()
baseline_results = []
first_season = sorted_seasons[0]
for m in season_matches[first_season]:
    baseline.train(m)

for season in sorted_seasons[1:]:
    matches = season_matches[season]
    correct = 0
    total = 0
    for m in matches:
        pred, _ = baseline.predict(m['odds_h'], m['odds_d'], m['odds_a'])
        total += 1
        if pred == m['outcome']:
            correct += 1
            baseline.train(m, was_miss=False)
        else:
            baseline.train(m, was_miss=True)
    acc = correct/total*100 if total else 0
    baseline_results.append({'season': season, 'total': total, 'correct': correct, 'accuracy': acc})

# ========================
# WALK-FORWARD TEST (with Wald Filter)
# ========================
print(f"\n{'='*70}")
print(f"WALK-FORWARD: ODDS-BRACKET + WALD ANTI-MISS FILTER")
print(f"{'='*70}")

wald_learner = WalkForwardBaseline()
wald_filter = WaldFilter(verbose=False)
wald_results = []

for m in season_matches[first_season]:
    wald_learner.train(m)

for season in sorted_seasons[1:]:
    matches = season_matches[season]
    correct = 0
    total = 0
    wald_changed = 0
    wald_corrected_misses = 0
    wald_made_worse = 0
    
    for m in matches:
        pred_base, conf_base = wald_learner.predict(m['odds_h'], m['odds_d'], m['odds_a'])
        
        # Apply Wald filter
        adj_pred, adj_conf, warns = wald_filter.filter(
            m['home'], m['away'],
            m['odds_h'], m['odds_d'], m['odds_a'],
            pred_base, conf_base
        )
        
        total += 1
        
        wald_pred = adj_pred if warns else pred_base
        
        if wald_pred != pred_base:
            wald_changed += 1
        
        if wald_pred == m['outcome']:
            correct += 1
            wald_learner.train(m, was_miss=False)
            if pred_base != m['outcome']:
                wald_corrected_misses += 1
        else:
            wald_learner.train(m, was_miss=True)
            if pred_base == m['outcome']:
                wald_made_worse += 1
    
    acc = correct/total*100 if total else 0
    wald_results.append({
        'season': season, 'total': total, 'correct': correct, 'accuracy': acc,
        'changes': wald_changed, 'corrected': wald_corrected_misses, 'worsened': wald_made_worse
    })

# ========================
# COMPARISON REPORT
# ========================
print(f"\n{'='*90}")
print(f"COMPARISON: BASELINE vs WALD-ENHANCED")
print(f"{'='*90}")
print(f"{'SEASON':25s} | {'BASE':6s} | {'WALD':6s} | {'DIFF':6s} | {'CHANGES':7s} | {'CORRECTED':9s} | {'WORSENED':8s}")
print("-" * 90)

total_base_correct = 0
total_wald_correct = 0
total_matches = 0
total_corrected = 0
total_worsened = 0
wald_better = 0
baseline_better = 0

for i, (br, wr) in enumerate(zip(baseline_results, wald_results)):
    diff = wr['accuracy'] - br['accuracy']
    marker = '⬆' if diff > 0 else '⬇' if diff < 0 else '→'
    total_base_correct += br['correct']
    total_wald_correct += wr['correct']
    total_matches += br['total']
    total_corrected += wr['corrected']
    total_worsened += wr['worsened']
    if diff > 0: wald_better += 1
    elif diff < 0: baseline_better += 1
    
    bar = '█' * int(wr['accuracy']/4) + '░' * (25 - int(wr['accuracy']/4))
    print(f"{str(wr['season'])[-20:]:25s} | {br['accuracy']:5.1f}% | {wr['accuracy']:5.1f}% | {diff:+5.1f}% {marker} | {wr['changes']:3d}    | {wr['corrected']:3d}        | {wr['worsened']:3d}")

base_overall = total_base_correct/total_matches*100
wald_overall = total_wald_correct/total_matches*100

print(f"\n{'='*90}")
print(f"FINAL TOTALS")
print(f"{'='*90}")
print(f"  Baseline accuracy:      {total_base_correct}/{total_matches} = {base_overall:.1f}%")
print(f"  Wald-enhanced accuracy: {total_wald_correct}/{total_matches} = {wald_overall:.1f}%")
print(f"  Net improvement:        {wald_overall - base_overall:+.1f}pp")
print(f"  Wald filter changed:    {sum(r['changes'] for r in wald_results)} predictions")
print(f"  Misses corrected:       {total_corrected}")
print(f"  Correct flipped wrong:  {total_worsened}")
print(f"  Net saved:              {total_corrected - total_worsened}")
print(f"  Seasons Wald was better: {wald_better}/{len(wald_results)}")
print(f"  Seasons baseline better:  {baseline_better}/{len(wald_results)}")

# Trend: accuracy progression over time
print(f"\n{'='*90}")
print(f"LEARNING PROGRESSION (Wald-enhanced)")
print(f"{'='*90}")
first_5 = sum(r['accuracy'] for r in wald_results[:5]) / 5
mid_5 = sum(r['accuracy'] for r in wald_results[len(wald_results)//2-2:len(wald_results)//2+3]) / 5
last_5 = sum(r['accuracy'] for r in wald_results[-5:]) / 5
print(f"  First 5 seasons: {first_5:.1f}%")
print(f"  Middle 5 seasons: {mid_5:.1f}%")
print(f"  Last 5 seasons: {last_5:.1f}%")
print(f"  Improvement (first→last): {last_5 - first_5:+.1f}pp")
print(f"  First season: {wald_results[0]['accuracy']:.1f}%")
print(f"  Last season: {wald_results[-1]['accuracy']:.1f}%")
print(f"  Total improvement: {wald_results[-1]['accuracy'] - wald_results[0]['accuracy']:+.1f}pp")

# Save
with open('/tmp/walk_forward_v2_results.json', 'w') as f:
    json.dump({
        'baseline': {'overall': base_overall, 'seasons': baseline_results},
        'wald': {'overall': wald_overall, 'seasons': wald_results},
        'total_matches': total_matches,
        'net_improvement': wald_overall - base_overall,
    }, f, indent=2)

print(f"\nResults saved to /tmp/walk_forward_v2_results.json")
