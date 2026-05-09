#!/usr/bin/env python3
"""Cassandra — Draw Cascade Analysis (v2)
Uses ALL matches for draw-rate analysis; odds-subset for cross-tier questions.
"""

import sqlite3, json, math, os, statistics
from collections import defaultdict

DB = "/home/faith/Documents/Projects/vfl-data/databases/history.db"
OUT = "/home/faith/Documents/Projects/vfl-data/analysis/draw-cascade.json"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# ── Load ALL matches with outcomes (for general draw analysis) ──
all_rows = conn.execute("""
    SELECT season, day, home, away, oh, od, oa, outcome, h, a
    FROM matches
    WHERE outcome IS NOT NULL AND outcome != ''
    ORDER BY season, day
""").fetchall()

conn.close()

def norm_outcome(o):
    o = o.strip().upper()
    if o in ('HOME', 'H'): return 'H'
    if o in ('AWAY', 'A'): return 'A'
    return 'D'

def broad_tier(odds):
    if odds is None or odds <= 0: return None
    if odds <= 1.80: return 1
    if odds <= 2.50: return 2
    if odds <= 3.50: return 3
    return 4

# Process ALL matches for general draw analysis
all_matches = []
odds_matches = []  # subset with valid odds for cross-tier analysis

for r in all_rows:
    m = dict(r)
    m['_outcome'] = norm_outcome(m['outcome'])
    m['_draw'] = 1 if m['_outcome'] == 'D' else 0
    m['_has_odds'] = (m['oh'] and m['oh'] > 0 and m['od'] and m['od'] > 0 and m['oa'] and m['oa'] > 0)
    
    if m['_has_odds']:
        m['_home_tier'] = broad_tier(m['oh'])
        m['_away_tier'] = broad_tier(m['oa'])
        m['_cross_tier'] = 1 if (m['_home_tier'] is not None and m['_away_tier'] is not None 
                                 and m['_home_tier'] != m['_away_tier']) else 0
        odds_matches.append(m)
    
    all_matches.append(m)

N_ALL = len(all_matches)
N_ODDS = len(odds_matches)
print(f"All matches with outcomes: {N_ALL}")
print(f"Matches with odds (tier derivable): {N_ODDS}")

# ── Build matchday maps for BOTH datasets ──
def build_matchday_map(matches):
    md_map = defaultdict(list)
    for m in matches:
        md_map[(m['season'], m['day'])].append(m)
    return md_map

def build_season_mds(md_map):
    seasons = defaultdict(list)
    for (season, day), ms in md_map.items():
        seasons[season].append((day, ms))
    for s in seasons:
        seasons[s].sort(key=lambda x: x[0])
    return {s: sorted(v, key=lambda x: x[0]) for s, v in seasons.items()}

md_map_all = build_matchday_map(all_matches)
md_map_odds = build_matchday_map(odds_matches)
season_mds_all = build_season_mds(md_map_all)
season_mds_odds = build_season_mds(md_map_odds)

# ── Matchday metrics ──
def compute_md_metrics(md_map):
    metrics = {}
    for (season, day), ms in md_map.items():
        total = len(ms)
        draws = sum(1 for m in ms if m['_draw'])
        cross_tier = sum(1 for m in ms if m.get('_cross_tier', 0))
        cross_tier_draws = sum(1 for m in ms if m.get('_cross_tier', 0) and m['_draw'])
        metrics[(season, day)] = {
            'total': total, 'draws': draws,
            'draw_rate': draws / total if total > 0 else 0,
            'cross_tier_total': cross_tier,
            'cross_tier_draws': cross_tier_draws,
        }
    return metrics

md_metrics_all = compute_md_metrics(md_map_all)
md_metrics_odds = compute_md_metrics(md_map_odds)

# ── ANALYSIS 1: D-DAY -> D+1 draw rate (using ALL matches) ──
# For every matchday, check: what is the draw rate on the NEXT matchday?
# Then group by how many draws were in the current matchday.

next_draw_rates_by_curr_draws = defaultdict(list)  # curr_draws -> [next_md_draw_rate]
next_draw_counts_by_curr_draws = defaultdict(list)  # curr_draws -> [next_md_draw_count]

for s, mds in season_mds_all.items():
    for i, (day, ms) in enumerate(mds):
        if i + 1 >= len(mds): continue
        curr_metrics = md_metrics_all[(s, day)]
        next_day, _ = mds[i + 1]
        next_metrics = md_metrics_all[(s, next_day)]
        
        curr_draws = curr_metrics['draws']
        next_draw_rates_by_curr_draws[curr_draws].append(next_metrics['draw_rate'])

# Also track next matchday raw draw count
next_draw_count_by_curr_draws = defaultdict(list)
next_md_total_matches_by_curr_draws = defaultdict(list)
for s, mds in season_mds_all.items():
    for i, (day, ms) in enumerate(mds):
        if i + 1 >= len(mds): continue
        curr_metrics = md_metrics_all[(s, day)]
        next_day, _ = mds[i + 1]
        next_metrics = md_metrics_all[(s, next_day)]
        next_draw_count_by_curr_draws[curr_metrics['draws']].append(next_metrics['draws'])
        next_md_total_matches_by_curr_draws[curr_metrics['draws']].append(next_metrics['total'])

# ── ANALYSIS 2: Cross-tier draw → next MD draw rate (odds subset) ──
next_md_after_ct_draw = []
same_md_ct_draw_present = []
all_md_draw_rates_all = [md_metrics_all[k]['draw_rate'] for k in md_metrics_all]

for s, mds in season_mds_odds.items():
    for i, (day, ms) in enumerate(mds):
        metrics = md_metrics_odds[(s, day)]
        if metrics['cross_tier_draws'] > 0:
            same_md_ct_draw_present.append(metrics['draw_rate'])
            if i + 1 < len(mds):
                next_day, _ = mds[i + 1]
                next_metrics = md_metrics_odds[(s, next_day)]
                next_md_after_ct_draw.append(next_metrics['draw_rate'])

# ── ANALYSIS 3: Bracket analysis (0, 1, 2, 3, 4+ draws) → next MD ──
brackets = [
    (0, "no_draws"),
    (1, "one_draw"),
    (2, "two_draws"),
    (3, "three_draws"),
    (4, "four_plus_draws"),
]

bracket_results = {}
for threshold, label in brackets:
    if label == "four_plus_draws":
        rates = []
        draws = []
        counts = []
        for k, v in next_draw_rates_by_curr_draws.items():
            if k >= threshold:
                rates.extend(v)
        for k, v in next_draw_count_by_curr_draws.items():
            if k >= threshold:
                draws.extend(v)
        # count of matchdays with >= threshold draws
        for k in md_metrics_all.values():
            if k['draws'] >= threshold:
                counts.append(k['draws'])
    else:
        rates = next_draw_rates_by_curr_draws.get(threshold, [])
        draws = next_draw_count_by_curr_draws.get(threshold, [])
    
    bracket_results[label] = {
        "curr_draw_threshold": threshold,
        "n_occurrences": len(rates),
        "next_draw_rate": round(statistics.mean(rates), 4) if rates else 0,
        "next_avg_draw_count": round(statistics.mean(draws), 2) if draws else 0,
        "next_median_draw_rate": round(statistics.median(rates), 4) if rates else 0,
    }

# ── ANALYSIS 4: MatchDAY-level pattern (using ALL data) ──
# For each season, compute draw count per matchday
# Then test: when MD X has high draws (4+), does MD X+1 also have high draws?

high_draw_pairs = {'hh': 0, 'hl': 0, 'lh': 0, 'll': 0}
for s, mds in season_mds_all.items():
    for i, (day, ms) in enumerate(mds):
        if i + 1 >= len(mds): continue
        curr_high = md_metrics_all[(s, day)]['draws'] >= 4
        next_day, _ = mds[i + 1]
        next_high = md_metrics_all[(s, next_day)]['draws'] >= 4
        
        if curr_high and next_high: high_draw_pairs['hh'] += 1
        elif curr_high and not next_high: high_draw_pairs['hl'] += 1
        elif not curr_high and next_high: high_draw_pairs['lh'] += 1
        else: high_draw_pairs['ll'] += 1

# Chi-squared
n_pairs = sum(high_draw_pairs.values())
chi2 = 0
chi2_p = 1.0
if n_pairs > 0:
    r1 = high_draw_pairs['hh'] + high_draw_pairs['hl']
    r2 = high_draw_pairs['lh'] + high_draw_pairs['ll']
    c1 = high_draw_pairs['hh'] + high_draw_pairs['lh']
    c2 = high_draw_pairs['hl'] + high_draw_pairs['ll']
    for obs, row, col in [
        (high_draw_pairs['hh'], r1, c1),
        (high_draw_pairs['hl'], r1, c2),
        (high_draw_pairs['lh'], r2, c1),
        (high_draw_pairs['ll'], r2, c2),
    ]:
        exp = row * col / n_pairs
        if exp > 0:
            chi2 += (obs - exp) ** 2 / exp
    if chi2 > 0:
        chi2_p = 2 * (1 - 0.5 * (1 + math.erf(math.sqrt(chi2) / math.sqrt(2))))

# ── ANALYSIS 5: Season-level lag-1 autocorrelation (ALL data) ──
season_autocorrs = []
season_corrs_detail = []
for s, mds in season_mds_all.items():
    draw_counts = [md_metrics_all[(s, day)]['draws'] for day, _ in mds]
    if len(draw_counts) < 5: continue
    
    n = len(draw_counts)
    x = draw_counts[:n-1]
    y = draw_counts[1:]
    
    mean_x = statistics.mean(x)
    mean_y = statistics.mean(y)
    sd_x = statistics.stdev(x) if len(x) > 1 else 0
    sd_y = statistics.stdev(y) if len(y) > 1 else 0
    
    if sd_x > 0 and sd_y > 0:
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / (n - 1)
        corr = cov / (sd_x * sd_y)
        season_autocorrs.append(corr)
        season_corrs_detail.append({"season": s, "n_matchdays": n, "lag1_corr": round(corr, 4)})

avg_autocorr = statistics.mean(season_autocorrs) if season_autocorrs else 0
median_autocorr = statistics.median(season_autocorrs) if season_autocorrs else 0
n_pos = sum(1 for c in season_autocorrs if c > 0)
n_neg = sum(1 for c in season_autocorrs if c < 0)

# ── ANALYSIS 6: Run test — do draws cluster in consecutive matchdays? ──
# For each season, count consecutive matchdays where both have above-median draws
median_draws_all = statistics.median([md_metrics_all[k]['draws'] for k in md_metrics_all])
consecutive_above_runs = []
current_run = 0
run_lengths = []
for s, mds in season_mds_all.items():
    for day, _ in mds:
        above = md_metrics_all[(s, day)]['draws'] > median_draws_all
        if above:
            current_run += 1
        else:
            if current_run >= 2:
                run_lengths.append(current_run)
            current_run = 0
    if current_run >= 2:
        run_lengths.append(current_run)
        current_run = 0

# Expected run lengths under independence (binomial with p=0.5)
# Probability of run of length k: n * (0.5)^(k+1)
total_mds = sum(len(mds) for mds in season_mds_all.values())
expected_runs_2plus = total_mds * (0.5 ** 3)  # P(run >= 2 starting at position i) ≈ 0.5^3 per start
observed_runs_2plus = len(run_lengths)

# ── Helper: z-test ──
def z_test_proportions(p1, n1, p2, n2):
    if n1 == 0 or n2 == 0: return 0, 1.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    if se == 0: return 0, 1.0
    z = (p1 - p2) / se
    pval = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return z, pval

# ── Compute key stats ──
baseline_draw_rate = statistics.mean(all_md_draw_rates_all)
baseline_median = statistics.median(all_md_draw_rates_all)

# After cross-tier draw (odds subset)
ct_next_avg = statistics.mean(next_md_after_ct_draw) if next_md_after_ct_draw else 0
ct_same_avg = statistics.mean(same_md_ct_draw_present) if same_md_ct_draw_present else 0
diff_ct = ct_next_avg - baseline_draw_rate

# After 2+ draws (all data)
a2_rates = []
a0_rates = []
for k, v in next_draw_rates_by_curr_draws.items():
    if k >= 2: a2_rates.extend(v)
    if k == 0: a0_rates.extend(v)
a2_avg = statistics.mean(a2_rates) if a2_rates else 0
a0_avg = statistics.mean(a0_rates) if a0_rates else 0

# After 4+ draws
a4_rates = []
a4_draws = []
for k, v in next_draw_rates_by_curr_draws.items():
    if k >= 4: a4_rates.extend(v)
for k, v in next_draw_count_by_curr_draws.items():
    if k >= 4: a4_draws.extend(v)
a4_avg = statistics.mean(a4_rates) if a4_rates else 0

# Z-tests on full data
# Test: next MD after 2+ draws vs after 0 draws
a2_draws_total = sum(sum(v) for k, v in next_draw_count_by_curr_draws.items() if k >= 2)
a2_total_matches = sum(sum(v) for k, v in next_md_total_matches_by_curr_draws.items() if k >= 2)
a0_draws_total = sum(next_draw_count_by_curr_draws.get(0, []))
a0_total_matches = sum(next_md_total_matches_by_curr_draws.get(0, []))

z_2v0 = 0
p_2v0 = 1.0
if a2_total_matches > 0 and a0_total_matches > 0:
    z_2v0, p_2v0 = z_test_proportions(
        a2_draws_total / a2_total_matches, a2_total_matches,
        a0_draws_total / a0_total_matches, a0_total_matches
    )

# Test 4+ vs baseline
a4_draws_count_total = 0
a4_total_matches = 0
for s, mds in season_mds_all.items():
    for i, (day, ms) in enumerate(mds):
        if i + 1 >= len(mds): continue
        curr = md_metrics_all[(s, day)]
        if curr['draws'] >= 4:
            next_day, _ = mds[i + 1]
            nm = md_metrics_all[(s, next_day)]
            a4_draws_count_total += nm['draws']
            a4_total_matches += nm['total']

total_draws_all = sum(md_metrics_all[k]['draws'] for k in md_metrics_all)
total_matches_all = N_ALL

z_4vbl = 0
p_4vbl = 1.0
if a4_total_matches > 0:
    z_4vbl, p_4vbl = z_test_proportions(
        a4_draws_count_total / a4_total_matches, a4_total_matches,
        total_draws_all / total_matches_all, total_matches_all
    )

# ── Verdicts ──
if abs(avg_autocorr) > 0.1:
    autocorr_verdict = "MODERATE_CASCADE"
elif abs(avg_autocorr) > 0.04:
    autocorr_verdict = "WEAK_CASCADE"
else:
    autocorr_verdict = "NO_CASCADE"

if abs(diff_ct) < 0.01:
    ct_verdict = "NO_EFFECT"
elif diff_ct > 0.01:
    ct_verdict = "WEAK_POSITIVE" if diff_ct < 0.03 else "POSITIVE"
else:
    ct_verdict = "WEAK_NEGATIVE"

if p_2v0 < 0.05:
    cluster_2v0 = "SIGNIFICANT"
elif abs(a2_avg - a0_avg) < 0.01:
    cluster_2v0 = "NO_DIFFERENCE"
else:
    cluster_2v0 = "NOT_SIGNIFICANT"

if p_4vbl < 0.05:
    high_draw_verdict = "SIGNIFICANT_MOMENTUM"
elif abs(a4_avg - baseline_draw_rate) < 0.015:
    high_draw_verdict = "NO_MOMENTUM"
else:
    high_draw_verdict = "WEAK_MOMENTUM"

# Final verdict
evidence_for = 0
evidence_against = 0
if avg_autocorr > 0.04: evidence_for += 1
if diff_ct > 0.015: evidence_for += 1
if a2_avg > a0_avg + 0.01: evidence_for += 1
if a4_avg > baseline_draw_rate + 0.01: evidence_for += 1
if chi2_p < 0.10: evidence_for += 1

if evidence_for >= 3:
    final_verdict = "Draw cascade EXISTS — evidence of draw momentum across matchdays"
elif evidence_for >= 1:
    final_verdict = "Draw cascade is WEAK — some evidence but not conclusive across all tests"
else:
    final_verdict = "Draw cascade does NOT exist — draws are independent across matchdays"

# ── Build output ──
output = {
    "meta": {
        "total_matches": N_ALL,
        "matches_with_odds": N_ODDS,
        "total_seasons": len(season_mds_all),
        "total_matchdays": len(md_metrics_all),
        "tier_method": "Odds-based proxy: T1 (≤1.80), T2 (1.81-2.50), T3 (2.51-3.50), T4 (3.51+)",
        "median_matchday_draws": median_draws_all,
    },
    "baseline": {
        "draw_rate": round(baseline_draw_rate, 4),
        "draw_rate_pct": f"{baseline_draw_rate*100:.2f}%",
        "median_draw_rate": round(baseline_median, 4),
        "total_matchdays": len(all_md_draw_rates_all),
    },
    "after_cross_tier_draw": {
        "next_md_draw_rate": round(ct_next_avg, 4),
        "next_md_draw_rate_pct": f"{ct_next_avg*100:.2f}%",
        "baseline_draw_rate": round(baseline_draw_rate, 4),
        "diff": round(diff_ct, 4),
        "diff_pct": f"{diff_ct*100:+.2f}%",
        "same_md_draw_rate": round(ct_same_avg, 4),
        "sample_size": len(next_md_after_ct_draw),
        "note": "Cross-tier derived from odds subset (3,320 matches). Small sample limits statistical power.",
        "verdict": ct_verdict,
    },
    "after_draw_count": {
        "0_draws": bracket_results["no_draws"],
        "1_draw": bracket_results["one_draw"],
        "2_draws": bracket_results["two_draws"],
        "3_draws": bracket_results["three_draws"],
        "4_plus_draws": bracket_results["four_plus_draws"],
        "z_test_2plus_vs_0": {
            "z": round(z_2v0, 4),
            "p": round(p_2v0, 4),
            "verdict": "SIGNIFICANT" if p_2v0 < 0.05 else "NOT_SIGNIFICANT",
        },
        "note_2plus_vs_0": f"Next MD draw rate after 2+ draws: {a2_avg*100:.2f}% vs after 0 draws: {a0_avg*100:.2f}%",
    },
    "after_4plus_draws": {
        "next_draw_rate": round(a4_avg, 4),
        "next_draw_rate_pct": f"{a4_avg*100:.2f}%",
        "sample_size": len(a4_rates),
        "z_vs_baseline": round(z_4vbl, 4),
        "p_vs_baseline": round(p_4vbl, 4),
        "verdict": high_draw_verdict,
    },
    "season_autocorrelation": {
        "mean_lag1_corr": round(avg_autocorr, 4),
        "median_lag1_corr": round(median_autocorr, 4),
        "seasons_positive": n_pos,
        "seasons_negative": n_neg,
        "total_seasons_analyzed": len(season_autocorrs),
        "by_season": season_corrs_detail,
        "verdict": autocorr_verdict,
    },
    "chi_squared_test": {
        "description": "Does a high-draw matchday (4+ draws) predict a high-draw next matchday?",
        "contingency": {
            "curr_high_next_high": high_draw_pairs['hh'],
            "curr_high_next_low": high_draw_pairs['hl'],
            "curr_low_next_high": high_draw_pairs['lh'],
            "curr_low_next_low": high_draw_pairs['ll'],
        },
        "chi2": round(chi2, 4),
        "p_value": round(chi2_p, 4),
        "verdict": "SIGNIFICANT" if chi2_p < 0.05 else "NOT_SIGNIFICANT",
    },
    "run_analysis": {
        "description": "Do above-median-draw matchdays cluster in consecutive runs?",
        "median_matchday_draws": round(median_draws_all, 1),
        "observed_runs_of_2plus_consecutive_above_median": observed_runs_2plus,
        "expected_runs_under_independence": round(expected_runs_2plus, 1),
        "run_lengths": run_lengths,
        "verdict": "CLUSTERING_OBSERVED" if observed_runs_2plus > expected_runs_2plus * 1.2 else "RANDOM" if observed_runs_2plus < expected_runs_2plus * 0.8 else "AS_EXPECTED",
    },
    "verdict": final_verdict,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w') as f:
    json.dump(output, f, indent=2)

# ── Print summary ──
print(f"\n{'='*65}")
print(f"CASSANDRA — DRAW CASCADE ANALYSIS (FULL DATASET)")
print(f"{'='*65}")
print(f"All matches: {N_ALL} | With odds: {N_ODDS} | Seasons: {len(season_mds_all)} | MDs: {len(md_metrics_all)}")
print(f"Baseline draw rate: {baseline_draw_rate*100:.2f}% | Median MD draws: {median_draws_all:.1f}")
print()
print(f"── 1. After Cross-Tier Draw (odds subset) ──")
print(f"  Next MD: {ct_next_avg*100:.2f}% | Baseline: {baseline_draw_rate*100:.2f}% | Diff: {diff_ct*100:+.2f}%")
print(f"  n={len(next_md_after_ct_draw)} | Verdict: {ct_verdict}")
print()
print(f"── 2. Next MD Draw Rate by Current MD Draw Count ──")
for label in ["no_draws", "one_draw", "two_draws", "three_draws", "four_plus_draws"]:
    b = bracket_results[label]
    print(f"  {label}: next rate {b['next_draw_rate']*100:.2f}% (n={b['n_occurrences']})")
print(f"  z(2+ vs 0): {z_2v0:.3f}, p={p_2v0:.4f}")
print()
print(f"── 3. After 4+ Draws High-Draw MD ──")
print(f"  Next rate: {a4_avg*100:.2f}% | n={len(a4_rates)} | z={z_4vbl:.3f}, p={p_4vbl:.4f}")
print()
print(f"── 4. Season Lag-1 Autocorrelation ──")
print(f"  Mean: {avg_autocorr:.4f} | +:{n_pos} / -:{n_neg} / {len(season_autocorrs)}")
print(f"── 5. Chi² High-Draw → High-Draw ──")
print(f"  χ²={chi2:.3f}, p={chi2_p:.4f} | hh={high_draw_pairs['hh']}, hl={high_draw_pairs['hl']}, lh={high_draw_pairs['lh']}, ll={high_draw_pairs['ll']}")
print(f"── 6. Run Clustering ──")
print(f"  Observed runs≥2: {observed_runs_2plus} vs Expected: {expected_runs_2plus:.1f}")
print(f"  Run lengths: {run_lengths}")
print()
print(f"🏁 FINAL VERDICT: {final_verdict}")
print(f"\n✅ Written to {OUT}")
