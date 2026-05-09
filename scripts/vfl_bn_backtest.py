#!/usr/bin/env python3
"""
VFL Engine Backtest — Walk-Forward using Discovered BN Structure
=================================================================
Uses the engine structure we discovered:
  outcome ← fav_type, tightness

For each season:
  1. Compute P(outcome | fav_type, tightness) from ALL prior seasons only
  2. Predict current season blind
  3. Check actuals → learn → repeat

No pgmpy inference needed. Pure conditional probability from data.
"""

import numpy as np, pandas as pd, sqlite3, json
from collections import defaultdict, Counter

np.random.seed(42)

# ============================================================
# DATA LOADING
# ============================================================

def load_all():
    rows = []
    def nt(t): return t.strip().title() if t else ''
    def oc(o):
        o=str(o).upper().strip()
        return 0 if o in ('HOME','H','1') else 1 if o in ('DRAW','D','X') else 2 if o in ('AWAY','A','2') else None
    conn=sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')
    for r in conn.execute("SELECT season,day,home,away,oh,od,oa,outcome FROM matches WHERE oh>0 AND od>0 AND oa>0 AND outcome IS NOT NULL AND outcome!=''"):
        o=oc(r[7])
        if o is not None: rows.append({'season':r[0],'md':r[1],'home':nt(r[2]),'away':nt(r[3]),'oh':float(r[4]),'od':float(r[5]),'oa':float(r[6]),'outcome':o})
    conn.close()
    conn2=sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/sovereign.db')
    exist=set((m['season'],m['md'],m['home'],m['away']) for m in rows)
    for r in conn2.execute("SELECT season_id,match_day,home_team,away_team,odds_h,odds_d,odds_a,outcome FROM master_ledger WHERE odds_h>0 AND odds_d>0 AND odds_a>0 AND outcome IS NOT NULL AND outcome!=''"):
        o=oc(r[7])
        if o is not None and (r[0],r[1],nt(r[2]),nt(r[3])) not in exist:
            rows.append({'season':r[0],'md':r[1],'home':nt(r[2]),'away':nt(r[3]),'oh':float(r[4]),'od':float(r[5]),'oa':float(r[6]),'outcome':o})
    conn2.close()
    return rows

matches = load_all()
print(f"Loaded {len(matches)} matches")

# Sort by season
def season_key(s):
    parts = str(s).replace('vf:season:', '').split('_')
    return int(parts[0])

season_map = defaultdict(list)
for m in matches:
    season_map[m['season']].append(m)
sorted_seasons = sorted(season_map.keys(), key=season_key)
sorted_seasons = [s for s in sorted_seasons if len(season_map[s]) >= 8]
print(f"Seasons (≥8 matches): {len(sorted_seasons)}")

# ============================================================
# ENGINE STRUCTURE: Compute key features
# ============================================================

def get_fav_type(oh, od, oa):
    """0=HOME_FAV, 1=DRAW_FAV, 2=AWAY_FAV"""
    mo = min(oh, od, oa)
    return 0 if mo==oh else 1 if mo==od else 2

def get_tightness(oh, od, oa):
    """0=CLOSE (spread<3), 1=OPEN (spread>=3)"""
    spread = max(oh,od,oa)-min(oh,od,oa)
    return 0 if spread < 3.0 else 1

def get_fav_strength(oh, od, oa):
    """0=HEAVY, 1=CLEAR, 2=SLIGHT, 3=EVEN"""
    ti = 1/oh + 1/od + 1/oa
    fp = max(1/oh/ti, 1/od/ti, 1/oa/ti)
    if fp >= 0.60: return 0
    elif fp >= 0.50: return 1
    elif fp >= 0.40: return 2
    return 3

def get_draw_zone(oh, od, oa):
    """0=HIGH_D, 1=NORM_D, 2=LOW_D"""
    ti = 1/oh + 1/od + 1/oa
    ph, pd, pa = 1/oh/ti, 1/od/ti, 1/oa/ti
    dr = pd / ((ph+pa)/2)
    if dr >= 1.15: return 0
    elif dr >= 0.90: return 1
    return 2


# ============================================================
# WALK-FORWARD: Using Discovered Structure
# ============================================================

# The BN discovered: outcome ← fav_type, tightness
# So we maintain: P(outcome | fav_type, tightness)
# That's 3 fav_types × 2 tightness = 6 conditions × 3 outcomes = 18 probabilities

print(f"\n{'='*85}")
print(f"WALK-FORWARD BACKTEST — BN Structure: outcome ← fav_type, tightness")
print(f"{'='*85}")

# Store CPD evolution
cpd_history = []
results = []

for i, test_season in enumerate(sorted_seasons[1:], 1):
    # Training data: all prior seasons
    train_seasons = sorted_seasons[:i]  # includes current test season - wait, no
    # Actually: train on seasons BEFORE test_season
    train_seasons = sorted_seasons[:sorted_seasons.index(test_season)]
    
    train_matches = []
    for s in train_seasons:
        train_matches.extend(season_map[s])
    
    test_matches = season_map[test_season]
    
    if len(train_matches) < 20:
        continue
    
    # === LEARN CPD FROM TRAINING DATA ===
    # P(outcome | fav_type, tightness) = count(outcome, fav, tight) / count(fav, tight)
    cpd = np.zeros((3, 2, 3))  # [fav_type][tightness][outcome] = count
    counts = np.zeros((3, 2))  # [fav_type][tightness] = total
    
    for m in train_matches:
        fav = get_fav_type(m['oh'], m['od'], m['oa'])
        tight = get_tightness(m['oh'], m['od'], m['oa'])
        outcome = m['outcome']
        cpd[fav][tight][outcome] += 1
        counts[fav][tight] += 1
    
    # === PREDICT TEST SEASON BLIND ===
    correct = 0
    total = 0
    by_type = {'H': {'correct': 0, 'total': 0}, 'D': {'correct': 0, 'total': 0}, 'A': {'correct': 0, 'total': 0}}
    edge_bets = 0
    edge_correct = 0
    
    predictions = []
    
    for m in test_matches:
        fav = get_fav_type(m['oh'], m['od'], m['oa'])
        tight = get_tightness(m['oh'], m['od'], m['oa'])
        strength = get_fav_strength(m['oh'], m['od'], m['oa'])
        
        # Get CPD for this condition
        total_cond = counts[fav][tight]
        if total_cond >= 5:
            probs = cpd[fav][tight] / total_cond
            pred = np.argmax(probs)
            confidence = probs[pred]
        else:
            # Fallback: use global favorite win rate
            pred = 0  # Default to HOME
            confidence = 0.44  # Global home win rate
        
        outcome = m['outcome']
        actual_outcome = ['H', 'D', 'A'][outcome]
        pred_outcome = ['H', 'D', 'A'][pred]
        
        correct_flag = pred == outcome
        if correct_flag:
            correct += 1
            by_type[pred_outcome]['correct'] += 1
        by_type[pred_outcome]['total'] += 1
        
        total += 1
        
        # Track "edge bets" — where our predicted probability differs significantly from market
        ti = 1/m['oh'] + 1/m['od'] + 1/m['oa']
        market_probs = [1/m['oh']/ti, 1/m['od']/ti, 1/m['oa']/ti]
        market_fav = np.argmax(market_probs)
        
        # Edge = we disagree with market AND have high confidence
        if pred != market_fav and confidence > 0.30:
            edge_bets += 1
            if correct_flag:
                edge_correct += 1
    
    acc = correct/total*100 if total else 0
    edge_acc = edge_correct/edge_bets*100 if edge_bets else 0
    
    # Track learning progress
    results.append({
        'season_num': i,
        'test_season': str(test_season)[-20:],
        'train_size': len(train_matches),
        'test_size': total,
        'correct': correct,
        'accuracy': round(acc, 2),
        'edge_bets': edge_bets,
        'edge_correct': edge_correct,
        'edge_accuracy': round(edge_acc, 2),
        'h_acc': round(by_type['H']['correct']/max(by_type['H']['total'],1)*100, 1),
        'd_acc': round(by_type['D']['correct']/max(by_type['D']['total'],1)*100, 1),
        'a_acc': round(by_type['A']['correct']/max(by_type['A']['total'],1)*100, 1),
    })
    
    # Save CPD snapshot
    cpd_snapshot = {}
    fav_names = ['H_FAV', 'D_FAV', 'A_FAV']
    tight_names = ['CLOSE', 'OPEN']
    for f in range(3):
        for t in range(2):
            if counts[f][t] >= 5:
                cpd_snapshot[f"{fav_names[f]}_{tight_names[t]}"] = {
                    'n': int(counts[f][t]),
                    'H': round(float(cpd[f][t][0]/counts[f][t]), 3),
                    'D': round(float(cpd[f][t][1]/counts[f][t]), 3),
                    'A': round(float(cpd[f][t][2]/counts[f][t]), 3),
                }
    cpd_history.append(cpd_snapshot)
    
    bar = '█' * int(acc/4) + '░' * max(0, 25-int(acc/4))
    edge_mark = f"| Edges:{edge_correct}/{edge_bets}={edge_acc:.0f}%" if edge_bets else ""
    print(f"  Season {i:2d}/{len(sorted_seasons)-1} | Train:{len(train_matches):4d} | Test:{total:3d} | Acc:{acc:5.1f}% {bar} | H:{results[-1]['h_acc']:4.1f}% D:{results[-1]['d_acc']:4.1f}% A:{results[-1]['a_acc']:4.1f}% {edge_mark}")


# ============================================================
# REPORT
# ============================================================
print(f"\n{'='*85}")
print(f"FINAL RESULTS — {len(results)} seasons")
print(f"{'='*85}")

total_correct = sum(r['correct'] for r in results)
total_matches = sum(r['test_size'] for r in results)
overall = total_correct/total_matches*100

first_5 = np.mean([r['accuracy'] for r in results[:5]])
last_5 = np.mean([r['accuracy'] for r in results[-5:]])
first_season = results[0]['accuracy']
last_season = results[-1]['accuracy']

# Per-type accuracy
h_total = sum(r['h_acc']*r['test_size']/100 for r in results)
d_total = sum(r['d_acc']*r['test_size']/100 for r in results)
a_total = sum(r['a_acc']*r['test_size']/100 for r in results)

print(f"\n  Overall accuracy:           {total_correct}/{total_matches} = {overall:.2f}%")
print(f"  First season:               {first_season:.2f}%")
print(f"  Last season:                {last_season:.2f}%")
print(f"  Improvement (1st→last):     {last_season-first_season:+.2f}pp")
print(f"  First 5 avg:                {first_5:.2f}%")
print(f"  Last 5 avg:                 {last_5:.2f}%")
print(f"  Net progression:            {last_5-first_5:+.2f}pp")

# What's the final discovered CPD?
print(f"\n  FINAL DISCOVERED ENGINE PROBABILITIES (all data):")
print(f"  {'Condition':30s} {'n':5s} {'H':8s} {'D':8s} {'A':8s}")
print(f"  {'-'*55}")
if cpd_history:
    final_cpd = cpd_history[-1]
    for cond, data in sorted(final_cpd.items()):
        print(f"  {cond:30s} {data['n']:5d} {data['H']:7.1%} {data['D']:7.1%} {data['A']:7.1%}")

# Performance per season — show progression
print(f"\n  {'Season':8s} {'Acc':6s} {'H-Acc':6s} {'D-Acc':6s} {'A-Acc':6s} {'Edge-Acc':7s} {'Trend'}")
print(f"  {'-'*55}")
for i, r in enumerate(results):
    trend = ''
    if i >= 2:
        diff = r['accuracy'] - results[i-1]['accuracy']
        trend = f"⬆+{diff:.1f}" if diff > 0 else f"⬇{diff:.1f}" if diff < 0 else "→"
    print(f"  {r['season_num']:3d}/{len(sorted_seasons)-1:2d}  {r['accuracy']:5.1f}% {r['h_acc']:5.1f}% {r['d_acc']:5.1f}% {r['a_acc']:5.1f}% {r['edge_accuracy']:5.1f}%  {trend}")

# Edge analysis
total_edge = sum(r['edge_bets'] for r in results)
total_edge_correct = sum(r['edge_correct'] for r in results)
if total_edge:
    print(f"\n  Edge bets overall:           {total_edge_correct}/{total_edge} = {total_edge_correct/total_edge*100:.1f}%")
    print(f"  Edge frequency:              {total_edge}/{total_matches} = {total_edge/total_matches*100:.1f}%")

# Comparison with simple market baseline
market_correct = 0
for m in matches:
    ti = 1/m['oh'] + 1/m['od'] + 1/m['oa']
    market_probs = [1/m['oh']/ti, 1/m['od']/ti, 1/m['oa']/ti]
    market_fav = np.argmax(market_probs)
    if market_fav == m['outcome']:
        market_correct += 1
market_acc = market_correct/len(matches)*100
print(f"\n  Market favorite baseline:    {market_correct}/{len(matches)} = {market_acc:.2f}%")
print(f"  BN engine advantage:         {overall-market_acc:+.2f}pp")

# Save
with open('/tmp/bn_backtest_results.json', 'w') as f:
    json.dump({
        'overall_accuracy': overall,
        'seasons': results,
        'final_cpd': cpd_history[-1] if cpd_history else {},
        'market_baseline': market_acc,
    }, f, indent=2)
print(f"\nResults saved to /tmp/bn_backtest_results.json")
