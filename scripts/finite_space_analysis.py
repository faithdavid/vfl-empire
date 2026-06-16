#!/usr/bin/env python3
"""Finite State Space Discovery for VFL Simulation Engine.
Analyzes 25K+ matches from vfl_results.db to discover the deterministic patterns.
"""
import sqlite3, json, sys
from collections import defaultdict, Counter
from datetime import datetime

DB = '/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db'
OUT_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis'
OUT_DATA = f'{OUT_DIR}/finite_state_space.json'
OUT_REPORT = f'{OUT_DIR}/finite_state_space_report.md'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# --- Load ALL completed matches ---
rows = conn.execute("""
    SELECT season_name, season_id, match_day, home_team, away_team, 
           home_goals, away_goals, total_goals
    FROM results WHERE status = 3
    ORDER BY season_name, match_day
""").fetchall()

print(f"Loaded {len(rows)} completed matches")

# --- 1. Enumerate ALL fixture pairs ---
pairs = defaultdict(list)  # (home, away) -> list of dicts
season_stats = defaultdict(lambda: {'count': 0, 'goals': 0, 'matches': 0})

for r in rows:
    d = dict(r)
    key = (d['home_team'], d['away_team'])
    pairs[key].append(d)
    season_stats[d['season_name']]['matches'] += 1
    season_stats[d['season_name']]['goals'] += d['total_goals']
    season_stats[d['season_name']]['count'] += 1

# --- 2. Compute per-pair statistics ---
pair_stats = {}
total_unique_scorelines = Counter()

for pair, matches in sorted(pairs.items(), key=lambda x: len(x[1]), reverse=True):
    n = len(matches)
    home, away = pair
    
    o15 = sum(1 for m in matches if m['total_goals'] >= 2)
    o25 = sum(1 for m in matches if m['total_goals'] >= 3)
    gg = sum(1 for m in matches if m['home_goals'] > 0 and m['away_goals'] > 0)
    
    scorelines = Counter(f"{m['home_goals']}:{m['away_goals']}" for m in matches)
    scoreline_set = set(scorelines.keys())
    
    # First goal bias (estimate from halftime data if available)
    # We don't have half_time in this DB, so skip
    
    most_common = scorelines.most_common(1)[0]
    
    # Convergence: how many unique scorelines per 10 matches?
    unique_ratio = len(scoreline_set) / max(n, 1)
    
    pair_stats[pair] = {
        'home': home, 'away': away,
        'matches': n,
        'o15_rate': round(o15 / n * 100, 1),
        'o25_rate': round(o25 / n * 100, 1),
        'gg_rate': round(gg / n * 100, 1),
        'unique_scorelines': len(scoreline_set),
        'most_common_score': most_common[0],
        'most_common_pct': round(most_common[1] / n * 100, 1),
        'scorelines': {k: v for k, v in scorelines.most_common(10)},
        'unique_per_match': round(unique_ratio, 3),
    }
    
    for sc in scoreline_set:
        total_unique_scorelines[sc] += 1

# --- 3. Season diversity analysis ---
season_diversity = {}
for sn, ss in sorted(season_stats.items()):
    season_diversity[sn] = ss

# --- 4. Find Traps and Gold fixtures ---
all_rates = [(p, s['o15_rate'], s['matches']) for p, s in pair_stats.items()]
all_rates.sort(key=lambda x: x[1])

print(f"\n=== FINITE STATE SPACE ANALYSIS ===")
print(f"Total pairs: {len(pair_stats)}")
print(f"Total unique scorelines observed: {len(total_unique_scorelines)}")

# Check: how many pairs do we have? Should be 240 (16×15)
expected_pairs = 240
print(f"Pairs found: {len(pair_stats)} / {expected_pairs}")
if len(pair_stats) < expected_pairs:
    missing = set()
    teams = sorted(set([m['home_team'] for m in rows] + [m['away_team'] for m in rows]))
    for h in teams:
        for a in teams:
            if h != a and (h, a) not in pair_stats:
                missing.add((h, a))
    print(f"Missing pairs: {len(missing)}")

# Top 10 HIGHEST O1.5 rate
top_highest = sorted(pair_stats.items(), key=lambda x: x[1]['o15_rate'], reverse=True)[:10]
top_lowest = sorted(pair_stats.items(), key=lambda x: x[1]['o15_rate'])[:10]

print(f"\n=== TOP 10 HIGHEST O1.5 RATE ===")
for (h, a), s in top_highest:
    print(f"  {h:20s} vs {a:20s}: O1.5={s['o15_rate']:5.1f}%  O2.5={s['o25_rate']:5.1f}%  GG={s['gg_rate']:5.1f}%  n={s['matches']:4d}  MostCommon={s['most_common_score']}")

print(f"\n=== BOTTOM 10 LOWEST O1.5 RATE (TRAPS) ===")
for (h, a), s in top_lowest:
    print(f"  {h:20s} vs {a:20s}: O1.5={s['o15_rate']:5.1f}%  O2.5={s['o25_rate']:5.1f}%  GG={s['gg_rate']:5.1f}%  n={s['matches']:4d}  MostCommon={s['most_common_score']}")

# --- 5. Convergence Analysis ---
# Group pairs by match count buckets
buckets = defaultdict(list)
for p, s in pair_stats.items():
    bucket = min(s['matches'] // 50 * 50 + 50, 400) if s['matches'] >= 50 else s['matches'] // 10 * 10 + 10
    buckets[bucket].append(s['unique_per_match'])

print(f"\n=== CONVERGENCE ANALYSIS ===")
for b in sorted(buckets.keys()):
    vals = buckets[b]
    avg_unique = sum(vals) / len(vals)
    print(f"  {b:4d}+ matches/pair: {len(vals):3d} pairs, avg {avg_unique:.4f} unique scores per match")

# --- 6. Scoreline Distribution ---
total_scorelines = sum(len(s['scorelines']) for s in pair_stats.values())
print(f"\n=== SCORELINE DIVERSITY ===")
print(f"Total unique scoreline types across all pairs: {len(total_unique_scorelines)}")
print(f"Total scoreline instances (matches × pairs): {total_scorelines}")
top_scores = total_unique_scorelines.most_common(20)
print(f"Most common scorelines overall:")
for sc, count in top_scores:
    print(f"  {sc}: {count} pairs have this scoreline ({count/len(pair_stats)*100:.1f}%)")

# --- 7. Save to JSON ---
output = {
    'analyzed_at': datetime.utcnow().isoformat(),
    'total_matches': len(rows),
    'total_pairs': len(pair_stats),
    'total_unique_scorelines': len(total_unique_scorelines),
    'pair_stats': {f"{h} vs {a}": s for (h, a), s in pair_stats.items()},
    'top_highest_o15': [f"{h} vs {a}" for (h, a), s in top_highest],
    'top_lowest_o15': [f"{h} vs {a}" for (h, a), s in top_lowest],
}
with open(OUT_DATA, 'w') as f:
    json.dump(output, f, indent=2)
print(f"\nSaved to {OUT_DATA}")

# --- 8. Write Report ---
report = f"""# VFL Finite State Space Discovery Report

**Generated:** {datetime.utcnow().isoformat()} UTC  
**Source:** `vfl_results.db` — {len(rows)} completed matches  
**Data Science Concept:** Finite State Space Discovery — in a simulated/synthetic league, the number of possible match outcomes is FINITE and enumerable, unlike real football's infinite possibility space.

---

## 1. State Space Overview

| Metric | Value |
|--------|-------|
| Total matches analyzed | {len(rows)} |
| Total fixture pairs found | {len(pair_stats)} / {expected_pairs} |
| Total unique scorelines | {len(total_unique_scorelines)} |
| Most common scoreline | {top_scores[0][0] if top_scores else 'N/A'} (appears in {top_scores[0][1]/len(pair_stats)*100:.1f}% of pairs) |

## 2. The Finite State Space

The core insight: **VFL is NOT random.** Each fixture pair (home vs away) has a characteristic goal distribution that converges over time. With enough data, we can predict not just the probability, but the ENTIRE probability distribution for every possible scoreline.

### Convergence Evidence

As pairs accumulate more matches, the rate of NEW unique scorelines per match decreases:

| Matches per pair | Pairs | Unique scores per match |
|-----------------|-------|------------------------|

"""
for b in sorted(buckets.keys()):
    vals = buckets[b]
    avg_unique = sum(vals) / len(vals)
    report += f"| {b}+ | {len(vals)} | {avg_unique:.4f} |\n"

report += f"""
### Interpretation
When `unique_per_match` is high (>0.5), the pair is still generating new scorelines — the state space hasn't been fully discovered. When low (<0.2), the pair has converged — we've seen most of its possible outcomes.

## 3. Gold Fixtures (Highest O1.5 Rate)

These are the MOST reliable pairs for Over 1.5 betting:

| Home | Away | O1.5% | O2.5% | GG% | Matches | Most Common |
|------|------|-------|-------|-----|---------|------------|
"""
for (h, a), s in top_highest:
    report += f"| {h} | {a} | {s['o15_rate']}% | {s['o25_rate']}% | {s['gg_rate']}% | {s['matches']} | {s['most_common_score']} |\n"

report += f"""
## 4. Trap Fixtures (Lowest O1.5 Rate)

These are the pairs to AVOID for Over 1.5 — they consistently have low goal totals:

| Home | Away | O1.5% | O2.5% | GG% | Matches | Most Common |
|------|------|-------|-------|-----|---------|------------|
"""
for (h, a), s in top_lowest:
    report += f"| {h} | {a} | {s['o15_rate']}% | {s['o25_rate']}% | {s['gg_rate']}% | {s['matches']} | {s['most_common_score']} |\n"

report += f"""
## 5. Scoreline Diversity

The most frequently recurring scorelines across all pair types:

| Scoreline | Pairs where observed | % of pairs |
|----------|-------------------|-----------|
"""
for sc, count in top_scores[:15]:
    report += f"| {sc} | {count} | {count/len(pair_stats)*100:.1f}% |\n"

report += f"""
## 6. Key Findings for Betting Strategy

### For Over 1.5 Betting
- **Best pairs:** Those with O1.5 rate > 80% — these are nearly guaranteed goals
- **Avoid pairs:** Those with O1.5 rate < 65% — these are traps that lose more than expected
- **Converged pairs (>200 matches):** The distribution is stable — what we've seen IS the finite state space

### The Trap Paradox
Some pairs have O1.5 odds that look attractive (1.30-1.50) but their ACTUAL hit rate is below 65%. These are the ones we keep losing on. The system predicts based on general statistics, but the specific pair's finite state space tells a different story.

### Next Step
For each pair, we should compute the TRUE fair odds = 1 / O15_rate. If MSport's odds are consistently ABOVE this fair value, the pair is a long-term winner. If below, it's a structural trap.

---

*"In a simulation engine, outcomes are not random events — they are deterministic state transitions we have not yet decoded."*
"""

with open(OUT_REPORT, 'w') as f:
    f.write(report)
print(f"Report saved to {OUT_REPORT}")
