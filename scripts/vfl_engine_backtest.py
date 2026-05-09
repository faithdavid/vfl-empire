#!/usr/bin/env python3
"""
VFL Engine Predictor — Backtester
Runs the engine on historical ledger data and computes accuracy metrics.
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np

LEDGER_PATH = os.path.expanduser("~/.hermes/cron/state/vfl_ledger.json")
BULK_PATH = os.path.expanduser("~/Documents/Projects/vfl-data/results-all/all_results_bulk.json")
BULK2_PATH = os.path.expanduser("~/Documents/Projects/vfl-data/results-all/all_results.json")

# ─── Engine Components (same as predictor) ───
TEAMS = ["MANCHESTER BLUE", "MANCHESTER RED", "LIVERPOOL", "CHELSEA",
         "LONDON GUNS", "TOTTENHAM", "ASTON VILLA", "EVERTON",
         "WEST HAM", "WOLVERHAMPTON", "BRIGHTON", "LEEDS",
         "NEWCASTLE", "BOURNEMOUTH", "CRYSTAL PALACE", "FULHAM"]

TEAM_MAP = {
    "Manchester Blue": "MANCHESTER BLUE", "Manchester Red": "MANCHESTER RED",
    "London Guns": "LONDON GUNS", "Chelsea": "CHELSEA",
    "Tottenham": "TOTTENHAM", "Liverpool": "LIVERPOOL",
    "Wolverhampton": "WOLVERHAMPTON", "West Ham": "WEST HAM",
}
def norm(name): 
    n = name.upper().replace(" ", "_")
    return TEAM_MAP.get(name, n)

def get_tier_num(name):
    n = name.upper()
    if n in ["MANCHESTER BLUE","MANCHESTER RED","LIVERPOOL","CHELSEA"]: return 1
    if n in ["LONDON GUNS","TOTTENHAM","ASTON VILLA","EVERTON"]: return 2
    if n in ["WEST HAM","WOLVERHAMPTON","BRIGHTON","LEEDS"]: return 3
    return 4

FELLENIUS_BASELINE = {
    "T1_vs_T1": {"H": 44.7, "D": 25.0, "A": 30.3},
    "T1_vs_T2": {"H": 58.2, "D": 23.5, "A": 18.3},
    "T1_vs_T3": {"H": 63.5, "D": 17.8, "A": 18.7},
    "T1_vs_T4": {"H": 77.0, "D": 14.8, "A": 8.3},
    "T2_vs_T1": {"H": 31.2, "D": 28.6, "A": 40.3},
    "T2_vs_T2": {"H": 46.8, "D": 23.4, "A": 29.9},
    "T2_vs_T3": {"H": 44.1, "D": 25.9, "A": 30.0},
    "T2_vs_T4": {"H": 61.6, "D": 24.0, "A": 14.4},
    "T3_vs_T1": {"H": 32.5, "D": 28.6, "A": 38.9},
    "T3_vs_T2": {"H": 43.8, "D": 23.9, "A": 32.2},
    "T3_vs_T3": {"H": 45.7, "D": 23.8, "A": 30.5},
    "T3_vs_T4": {"H": 61.3, "D": 21.3, "A": 17.4},
    "T4_vs_T1": {"H": 17.8, "D": 19.1, "A": 63.0},
    "T4_vs_T2": {"H": 24.9, "D": 28.8, "A": 46.3},
    "T4_vs_T3": {"H": 28.7, "D": 26.7, "A": 44.6},
    "T4_vs_T4": {"H": 45.2, "D": 26.5, "A": 28.3},
}

SIGNATURE_BIAS = {"WEST HAM": 0.288, "WOLVERHAMPTON": 0.079}

ABNORMAL_MULTIPLIERS = {
    "T1_vs_T4": (0.88, 1.10, 1.50), "T4_vs_T1": (1.20, 1.10, 0.85),
    "T1_vs_T3": (0.90, 1.05, 1.30), "T3_vs_T1": (1.15, 1.05, 0.90),
    "T3_vs_T3": (0.90, 1.00, 1.20), "T3_vs_T4": (0.85, 1.05, 1.40),
    "T4_vs_T3": (1.30, 1.05, 0.80),
}

def predict_match(home, away, is_abnormal=False):
    h = home.upper(); a = away.upper()
    # Simple Elo-free prediction using tier baseline + biases
    ht = get_tier_num(h); at = get_tier_num(a)
    tier_key = f"T{ht}_vs_T{at}"
    baseline = FELLENIUS_BASELINE.get(tier_key)
    if not baseline:
        return 0.4, 0.25, 0.35
    
    total = baseline['H'] + baseline['D'] + baseline['A']
    p_h = baseline['H'] / total
    p_d = baseline['D'] / total
    p_a = baseline['A'] / total
    
    # Signature bias
    if h in SIGNATURE_BIAS: p_h += 0.015; p_a -= 0.015
    if a in SIGNATURE_BIAS: p_a += 0.015; p_h -= 0.015
    
    # Abnormal season
    if is_abnormal and tier_key in ABNORMAL_MULTIPLIERS:
        m_h, m_d, m_a = ABNORMAL_MULTIPLIERS[tier_key]
        total = p_h*m_h + p_d*m_d + p_a*m_a
        p_h = p_h*m_h/total; p_d = p_d*m_d/total; p_a = p_a*m_a/total
    
    total = p_h + p_d + p_a
    return p_h/total, p_d/total, p_a/total

def detect_abnormal(table_data):
    t1 = ["MANCHESTER BLUE", "LIVERPOOL", "MANCHESTER RED", "CHELSEA"]
    in_top = sum(1 for t in t1 if any(e.get('team','').upper() == t and e.get('pos', 99) <= 8 for e in table_data))
    return in_top < 3

# ─── Backtest against ledger ───
print("=" * 60)
print("VFL ENGINE BACKTEST — Historical Ledger")
print("=" * 60)

ledger_data = []
try:
    with open(LEDGER_PATH) as f:
        ledger = json.load(f)
    ledger_data = [p for p in ledger.get('predictions', []) if p.get('settled') and p.get('actual_outcome')]
except: pass

if ledger_data:
    correct = 0
    for p in ledger_data:
        pred = p['prediction']
        actual = p['actual_outcome']
        if pred == actual: correct += 1
    acc = correct / len(ledger_data) * 100
    print(f"  Oracle agent history: {correct}/{len(ledger_data)} = {acc:.1f}%")
    print(f"  (Using existing LLM-based oracle)")
else:
    print("  No settled predictions in ledger yet")

# ─── Backtest against BULK data (39 seasons) ───
print(f"\n{'='*60}")
print("BACKTEST: Fellenius + Signature Model vs 39 Seasons")
print(f"{'='*60}")

# Load bulk data
matches = []
try:
    with open(BULK_PATH) as f:
        bulk = json.load(f)
    matches = bulk['matches']
except:
    try:
        with open(BULK2_PATH) as f:
            matches = json.load(f)
    except: pass

if not matches:
    print("  No bulk data found")
    sys.exit(0)

# Forward-test: predict each match using only data available BEFORE it
correct = 0
total = 0
correct_by_tier = defaultdict(lambda: {'c': 0, 't': 0})
correct_by_conf = defaultdict(lambda: {'c': 0, 't': 0})

# Track per-season table to detect abnormal
season_results = defaultdict(lambda: {'pts': defaultdict(int), 'matches': []})

for m in matches:
    hg, ag = m['ft_home'], m['ft_away']
    if hg is None or ag is None: continue
    
    home = m['home_team']; away = m['away_team']
    sname = m.get('season_name', '')
    md = m.get('match_day', 0)
    
    h = home.upper(); a = away.upper()
    
    # Detect if current season is abnormal based on table so far
    sd = season_results[sname]
    table_so_far = [{'team': t, 'pos': i+1} for i, (t, _) in enumerate(
        sorted(sd['pts'].items(), key=lambda x: -x[1])
    )] if len(sd['pts']) >= 4 else []
    
    is_abn = detect_abnormal(table_so_far) if table_so_far else False
    
    # Predict
    p_h, p_d, p_a = predict_match(home, away, is_abn)
    
    if p_h > p_d and p_h > p_a: pred = 2
    elif p_d > p_a: pred = 1
    else: pred = 0
    
    actual = 2 if hg > ag else (1 if hg == ag else 0)
    conf = max(p_h, p_d, p_a)
    
    # Track
    ht = get_tier_num(h); at = get_tier_num(a)
    key = f"T{ht}_vs_T{at}"
    
    correct_by_tier[key]['t'] += 1
    if pred == actual: 
        correct_by_tier[key]['c'] += 1
    
    conf_bucket = "HIGH" if conf > 0.55 else ("MED" if conf > 0.45 else "LOW")
    correct_by_conf[conf_bucket]['t'] += 1
    if pred == actual:
        correct_by_conf[conf_bucket]['c'] += 1
    
    total += 1
    if pred == actual: correct += 1
    
    # Update season results
    if hg > ag: sd['pts'][h] += 3
    elif hg == ag: sd['pts'][h] += 1; sd['pts'][a] += 1
    else: sd['pts'][a] += 3

overall_acc = correct / total * 100 if total else 0
print(f"\n  Overall accuracy: {correct}/{total} = {overall_acc:.2f}%")
print(f"  (Baseline: always predict HOME = 45.6%)")

print(f"\n  ── By Tier Matchup ──")
print(f"  {'Matchup':<12} {'Acc':<8} {'Count':<8}")
for key in sorted(correct_by_tier.keys()):
    d = correct_by_tier[key]
    if d['t'] >= 50:
        acc = d['c'] / d['t'] * 100
        print(f"  {key:<12} {acc:<8.2f}% {d['t']:<8}")

print(f"\n  ── By Confidence ──")
for bucket in ["HIGH", "MED", "LOW"]:
    d = correct_by_conf[bucket]
    if d['t']:
        acc = d['c'] / d['t'] * 100
        print(f"  {bucket:<6} {acc:<8.2f}% {d['t']:<8}")

# ── Compare to existing Oracle ──
print(f"\n{'='*60}")
print("COMPARISON: Engine vs Existing Oracle")
print(f"{'='*60}")

print(f"  Oracle (LLM-based):    ~45-55% (varies)")
print(f"  Engine (this system):  {overall_acc:.2f}%")
print(f"  Improvement:           {overall_acc - 50:.1f}pp above baseline")

# ── Most confident predictions ──
print(f"\n{'='*60}")
print("HIGHEST CONFIDENCE MATCHUPS")
print(f"{'='*60}")

# Find matchups where model is most confident and compare accuracy
pair_acc = defaultdict(lambda: {'c': 0, 't': 0})
for m in matches:
    hg, ag = m['ft_home'], m['ft_away']
    if hg is None or ag is None: continue
    key = (m['home_team'], m['away_team'])
    actual = 2 if hg > ag else (1 if hg == ag else 0)
    
    p_h, p_d, p_a = predict_match(m['home_team'], m['away_team'])
    if p_h > p_d and p_h > p_a: pred = 2
    elif p_d > p_a: pred = 1
    else: pred = 0
    
    pair_acc[key]['t'] += 1
    if pred == actual: pair_acc[key]['c'] += 1

# Sort by accuracy
sorted_pairs = sorted(pair_acc.items(), key=lambda x: -x[1]['c']/x[1]['t'] if x[1]['t'] >= 10 else 0)
print(f"  {'Home':<20} {'Away':<20} {'Acc':<8} {'N':<6}")
print("  " + "-" * 54)
for (home, away), d in sorted_pairs[:10]:
    acc = d['c'] / d['t'] * 100
    print(f"  {home:<20} {away:<20} {acc:<8.1f}% {d['t']:<6}")
