#!/usr/bin/env python3
"""
Gideon — Quantitative Analysis of VFL Betting Data (Final)
Strict numbers, proper methods, no look-ahead bias.
"""
import sqlite3, json, math, statistics
from collections import defaultdict

DB = "/home/faith/Documents/Projects/vfl-data/databases/history.db"
OUT = "/home/faith/Documents/Projects/vfl-data/analysis/gideon-quantitative.json"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = [dict(r) for r in conn.execute("""
    SELECT season, day, home, away, oh, od, oa, h, a, outcome
    FROM matches WHERE oh IS NOT NULL AND od IS NOT NULL AND oa IS NOT NULL
    AND outcome IN ('HOME','DRAW','AWAY')
""").fetchall()]
N = len(rows)

# ---------- helpers ----------
def margin(oh, od, oa):
    return 1/oh + 1/od + 1/oa - 1.0

def vfp(oh, od, oa):
    """vig-free probabilities"""
    m = margin(oh, od, oa)
    return (1/oh/(1+m), 1/od/(1+m), 1/oa/(1+m))

def oidx(o):
    return 0 if o == "HOME" else (1 if o == "DRAW" else 2)

def wilson_ci(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k / n
    d = 1 + z*z/n
    c = p + z*z/(2*n)
    m = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c-m)/d, (c+m)/d)

# ================================================================
# Q1: Kelly-optimal strategy - threshold approach
# For each threshold t (50% to 95%):
#   Bet on outcome with highest vig-free prob IF it >= t
#   Kelly stake sizing using empirical outcome frequency per odds bucket
# ================================================================
print("=== Q1: Kelly Threshold Analysis ===")
# Build odds-bucket empirical probabilities via *walk-forward*:
# For each season, use all PRIOR seasons' data to form empirical rates
seasons_ordered = sorted(set(m['season'] for m in rows))
season_idx = {s: i for i, s in enumerate(seasons_ordered)}

# Precompute bucket empirical rates from all data (we'll use walk-forward for Kelly)
def make_bucket_rates(matches):
    rates = {}
    bucket_data = defaultdict(lambda: {"n": 0, "wins": 0, "sum_odds": 0.0})
    for m in matches:
        for idx, odd in [(0, m['oh']), (1, m['od']), (2, m['oa'])]:
            b = round(odd * 20) / 20.0
            bucket_data[(idx, b)]["n"] += 1
            bucket_data[(idx, b)]["sum_odds"] += odd
            if oidx(m['outcome']) == idx:
                bucket_data[(idx, b)]["wins"] += 1
    for (idx, b), d in bucket_data.items():
        if d["n"] >= 10:
            rates[(idx, b)] = d["wins"] / d["n"]
    return rates

# Walk-forward Kelly simulation
def walkforward_kelly(rows, thresholds, initial_bankroll=10000.0):
    """Proper walk-forward: for each match, trained on all prior seasons."""
    results = {}
    for thresh_pct in thresholds:
        bankroll = initial_bankroll
        peak = initial_bankroll
        max_dd = 0.0
        total_bets = 0
        wins = 0
        profits = []
        
        # Group rows by season
        by_season = defaultdict(list)
        for m in rows:
            by_season[m['season']].append(m)
        
        prev_matches = []
        for season in seasons_ordered:
            current_matches = by_season[season]
            # Build empirical rates from ALL prior seasons
            emp_rates = make_bucket_rates(prev_matches)
            
            for m in current_matches:
                oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
                actual = oidx(outcome)
                probs = vfp(oh, od, oa)
                odds = [oh, od, oa]
                
                best_idx = max(range(3), key=lambda i: probs[i])
                best_prob = probs[best_idx]
                best_odd = odds[best_idx]
                
                if best_prob < thresh_pct:
                    continue
                
                # Get empirical win rate for this bucket
                bucket = round(best_odd * 20) / 20.0
                emp_p = emp_rates.get((best_idx, bucket), best_prob)
                
                # Kelly fraction using empirical p
                kelly = (emp_p * best_odd - 1.0) / (best_odd - 1.0)
                if kelly <= 0:
                    continue
                
                stake = kelly * bankroll
                if best_idx == actual:
                    profit = stake * (best_odd - 1.0)
                    wins += 1
                else:
                    profit = -stake
                
                bankroll += profit
                total_bets += 1
                profits.append(profit)
                if bankroll > peak:
                    peak = bankroll
                dd = (peak - bankroll) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
            
            prev_matches.extend(current_matches)
        
        tot_pnl = bankroll - initial_bankroll
        roi = tot_pnl / initial_bankroll * 100
        wr = wins / total_bets if total_bets else 0
        avg_r = statistics.mean(profits) if profits else 0
        std_r = statistics.stdev(profits) if len(profits) > 1 else 0
        sharpe = (avg_r / std_r) * math.sqrt(252) if std_r > 0 else 0
        
        results[str(int(thresh_pct*100))] = {
            "threshold_pct": round(thresh_pct * 100, 1),
            "total_bets": total_bets,
            "wins": wins,
            "losses": total_bets - wins,
            "win_rate": round(wr, 4),
            "final_bankroll": round(bankroll, 2),
            "total_profit": round(tot_pnl, 2),
            "roi_pct": round(roi, 2),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown_pct": round(max_dd * 100, 2),
        }
        if total_bets:
            print(f"  {thresh_pct*100:.0f}%: bets={total_bets:4d}  WR={wr:.3f}  ROI={roi:+.1f}%  Sharpe={sharpe:.3f}  P&L={tot_pnl:+.0f}  DD={max_dd*100:.1f}%")
        else:
            print(f"  {thresh_pct*100:.0f}%: bets=0")
    
    return results

# Run Kelly with empirical + vig-free probs (two approaches)
thresh_pcts = [i/100.0 for i in range(50, 96)]
kelly_results = walkforward_kelly(rows, thresh_pcts, 10000.0)

# Also pure vig-free Kelly (no empirical - what Kelly says using market's own probs)
def pure_kelly(rows, initial_bankroll=10000.0):
    """Kelly using vig-free probabilities as 'true' probabilities (should be ~0 edge)"""
    bankroll = initial_bankroll
    peak = initial_bankroll
    max_dd = 0.0
    total_bets = 0
    wins = 0
    profits = []
    
    for m in rows:
        oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
        actual = oidx(outcome)
        probs = vfp(oh, od, oa)
        odds = [oh, od, oa]
        
        for idx in range(3):
            if probs[idx] * odds[idx] > 1.0:
                kelly = (probs[idx] * odds[idx] - 1.0) / (odds[idx] - 1.0)
                if kelly > 0:
                    stake = kelly * bankroll
                    if idx == actual:
                        profit = stake * (odds[idx] - 1.0)
                        wins += 1
                    else:
                        profit = -stake
                    bankroll += profit
                    total_bets += 1
                    profits.append(profit)
                    if bankroll > peak:
                        peak = bankroll
                    dd = (peak - bankroll) / peak if peak > 0 else 0
                    if dd > max_dd:
                        max_dd = dd
    
    tot_pnl = bankroll - initial_bankroll
    roi = tot_pnl / initial_bankroll * 100
    wr = wins / total_bets if total_bets else 0
    avg_r = statistics.mean(profits) if profits else 0
    std_r = statistics.stdev(profits) if len(profits) > 1 else 0
    sharpe = (avg_r / std_r) * math.sqrt(252) if std_r > 0 else 0
    return {"total_bets": total_bets, "wins": wins, "win_rate": round(wr, 4),
            "final_bankroll": round(bankroll, 2), "total_profit": round(tot_pnl, 2),
            "roi_pct": round(roi, 2), "sharpe_ratio": round(sharpe, 4),
            "max_drawdown_pct": round(max_dd * 100, 2)}

pk = pure_kelly(rows, 10000.0)
print(f"Pure Kelly (any +EV bet): bets={pk['total_bets']}, WR={pk['win_rate']:.3f}, P&L={pk['total_profit']:.0f}")

# Find best
kelly_list = [v for v in kelly_results.values()]
best_sharpe_kelly = max(kelly_list, key=lambda r: r['sharpe_ratio'])
best_profit_kelly = max(kelly_list, key=lambda r: r['total_profit'])
best_wr_kelly = max(kelly_list, key=lambda r: r['win_rate'])

# ================================================================
# Q2: Stability Over Time
# ================================================================
print("\n=== Q2: Stability ===")
print(f"Total seasons in clean data: {len(seasons_ordered)}")

half = len(seasons_ordered) // 2
early_seasons = set(seasons_ordered[:half])
late_seasons = set(seasons_ordered[half:])
early_rows = [m for m in rows if m['season'] in early_seasons]
late_rows = [m for m in rows if m['season'] in late_seasons]

def split_analysis(matches, label):
    cnt = {"HOME": 0, "DRAW": 0, "AWAY": 0, "total": len(matches)}
    for m in matches:
        cnt[m['outcome']] += 1
    hwr = cnt["HOME"] / cnt["total"]
    avg_m = statistics.mean(margin(m['oh'], m['od'], m['oa']) for m in matches)
    return {
        "label": label, "match_count": cnt["total"],
        "outcome_rates": {k: round(v/cnt["total"], 4) for k, v in cnt.items() if k != "total"},
        "home_win_rate": round(hwr, 4), "avg_margin": round(avg_m, 4)
    }

# Also compute edges that would have been seen in each half
def compute_edges(matches):
    """For each odds bucket, what's the empirical edge?"""
    bucket_wins = defaultdict(lambda: {"n": 0, "wins": 0})
    for m in matches:
        for idx, odd in [(0, m['oh']), (1, m['od']), (2, m['oa'])]:
            b = round(odd * 20) / 20.0
            bucket_wins[(idx, b)]["n"] += 1
            if oidx(m['outcome']) == idx:
                bucket_wins[(idx, b)]["wins"] += 1
    edges = {}
    for (idx, b), d in bucket_wins.items():
        if d["n"] >= 10:
            emp = d["wins"] / d["n"]
            be = 1.0 / b if b > 0 else 0
            edges[f"{['HOME','DRAW','AWAY'][idx]}@{b:.2f}"] = {
                "n": d["n"], "empirical_p": round(emp, 4),
                "breakeven_p": round(be, 4), "edge": round(emp - be, 4)
            }
    return edges

q2 = {
    "season_count": len(seasons_ordered),
    "early": split_analysis(early_rows, "early_half_12_seasons"),
    "late": split_analysis(late_rows, "late_half_13_seasons"),
    "edges_early": compute_edges(early_rows),
    "edges_late": compute_edges(late_rows),
}

# Count positive vs negative edges in each half
def count_edge_dirs(edges_dict):
    pos = sum(1 for v in edges_dict.values() if v["edge"] > 0)
    neg = sum(1 for v in edges_dict.values() if v["edge"] < 0)
    return {"positive_edges": pos, "negative_edges": neg}

q2["edge_direction_counts"] = {
    "early": count_edge_dirs(q2["edges_early"]),
    "late": count_edge_dirs(q2["edges_late"]),
}

print(f"  Early: {q2['early']['match_count']} matches, home WR={q2['early']['home_win_rate']:.4f}, margin={q2['early']['avg_margin']:.4f}")
print(f"  Late:  {q2['late']['match_count']} matches, home WR={q2['late']['home_win_rate']:.4f}, margin={q2['late']['avg_margin']:.4f}")
print(f"  Edge dirs early: {q2['edge_direction_counts']['early']}")
print(f"  Edge dirs late:  {q2['edge_direction_counts']['late']}")

# ================================================================
# Q3: Calibration Curve
# ================================================================
print("\n=== Q3: Calibration ===")

# Proper calibration: pool all 3 outcomes as individual probability events
# For each match, each outcome has a predicted probability = vig-free prob
# We have 3*N observations: {predicted_prob_i, actual_i} where actual_i=1 if that outcome occurred
cal_bins = defaultdict(lambda: {"n": 0, "occurred": 0, "sum_pred": 0.0})
for m in rows:
    probs = vfp(m['oh'], m['od'], m['oa'])
    actual = oidx(m['outcome'])
    for idx in range(3):
        p = probs[idx]
        bk = min(19, int(p * 20))
        cal_bins[bk]["n"] += 1
        cal_bins[bk]["sum_pred"] += p
        if idx == actual:
            cal_bins[bk]["occurred"] += 1

calibration_pooled = []
total_abs_error = 0.0
n_obs = 0
for bk in sorted(cal_bins.keys()):
    d = cal_bins[bk]
    if d["n"] < 5:
        continue
    mid = (bk + 0.5) / 20.0
    freq = d["occurred"] / d["n"]
    err = freq - mid
    total_abs_error += abs(err) * d["n"]
    n_obs += d["n"]
    ci_low, ci_high = wilson_ci(d["occurred"], d["n"], 1.96)
    calibration_pooled.append({
        "bin_mid": round(mid, 3),
        "bin_range": f"{bk/20:.2f}-{(bk+1)/20:.2f}",
        "n_observations": d["n"],
        "predicted_prob": round(mid, 4),
        "actual_frequency": round(freq, 4),
        "error": round(err, 4),
        "ci_95": [round(ci_low, 4), round(ci_high, 4)]
    })

mae = total_abs_error / n_obs if n_obs else 0
print(f"  Pooled calibration: {len(calibration_pooled)} bins, MAE={mae:.4f}")

# Also calculate bias separately for: predicted 40-60%, 60-80%, 80%+
ranges = [(0.0, 0.4, "0-40%"), (0.4, 0.6, "40-60%"), (0.6, 0.8, "60-80%"), (0.8, 1.0, "80-100%")]
for lo, hi, label in ranges:
    subset = [c for c in calibration_pooled if lo <= c["predicted_prob"] < hi]
    if subset:
        avg_err = statistics.mean([c["error"] for c in subset])
        n = sum(c["n_observations"] for c in subset)
        print(f"  {label}: avg error={avg_err:.4f}, n={n}")

# ================================================================
# Q4: Correlation Analysis
# ================================================================
print("\n=== Q4: Correlations ===")

# 4a: Team home/away independence
team_stats = defaultdict(lambda: {"hn": 0, "hw": 0, "an": 0, "aw": 0})
for m in rows:
    team_stats[m['home'].upper()]["hn"] += 1
    if m['outcome'] == "HOME":
        team_stats[m['home'].upper()]["hw"] += 1
    team_stats[m['away'].upper()]["an"] += 1
    if m['outcome'] == "AWAY":
        team_stats[m['away'].upper()]["aw"] += 1

team_list = sorted([{
    "team": t, "home_n": d["hn"], "away_n": d["an"],
    "home_win_rate": round(d["hw"]/d["hn"], 4) if d["hn"] else 0,
    "away_win_rate": round(d["aw"]/d["an"], 4) if d["an"] else 0
} for t, d in team_stats.items()], key=lambda x: -x["home_n"])

valid = [t for t in team_list if t["home_n"] >= 20 and t["away_n"] >= 20]
if len(valid) >= 3:
    ha_corr = statistics.correlation([t["home_win_rate"] for t in valid],
                                      [t["away_win_rate"] for t in valid])
else:
    ha_corr = None

# 4b: Odds correlation
oh_list, oa_list = [m['oh'] for m in rows], [m['oa'] for m in rows]
oh_od_list, od_oa_list = [m['oh'] for m in rows], [m['oa'] for m in rows]
# Wait, let me fix these
oha_corr = statistics.correlation(oh_list, oa_list)
ohd_corr = statistics.correlation([m['oh'] for m in rows], [m['od'] for m in rows])
oda_corr = statistics.correlation([m['od'] for m in rows], [m['oa'] for m in rows])

# 4c: Season position
season_max_day = {s: max(m['day'] for m in rows if m['season'] == s) for s in seasons_ordered}
segments = defaultdict(lambda: {"HOME": 0, "DRAW": 0, "AWAY": 0, "n": 0})
for m in rows:
    mx = season_max_day.get(m['season'], 38)
    pos = m['day'] / mx if mx > 0 else 0
    seg = min(9, int(pos * 10))
    segments[seg][m['outcome']] += 1
    segments[seg]["n"] += 1

time_pattern = []
for seg in sorted(segments):
    d = segments[seg]
    time_pattern.append({
        "position_range": f"{seg*10}-{(seg+1)*10}%",
        "n": d["n"],
        "home": round(d["HOME"]/d["n"], 4),
        "draw": round(d["DRAW"]/d["n"], 4),
        "away": round(d["AWAY"]/d["n"], 4)
    })

print(f"  Home-Away odds correlation: {oha_corr:.4f}")
print(f"  Home-Draw odds correlation: {ohd_corr:.4f}")
print(f"  Draw-Away odds correlation: {oda_corr:.4f}")
print(f"  Teams HA WR correlation (n>=20): {ha_corr}")
print(f"  Time segments: {len(time_pattern)}")

# ================================================================
# Q5: Minimum Sample Size
# ================================================================
print("\n=== Q5: Sample Size ===")

team_ci = []
for t in team_list:
    n, k = t["home_n"], int(t["home_win_rate"] * t["home_n"])
    if n < 5:
        continue
    ci_low, ci_high = wilson_ci(k, n, 1.96)
    ci_low90, ci_high90 = wilson_ci(k, n, 1.645)
    team_ci.append({**t, "ci_95": [round(ci_low, 4), round(ci_high, 4)],
                    "ci_90": [round(ci_low90, 4), round(ci_high90, 4)],
                    "ci_95_width": round(ci_high - ci_low, 4)})

# CI width by sample size group
ci_width_groups = []
for lo, hi in [(5, 10), (11, 20), (21, 50), (51, 100), (101, 9999)]:
    sub = [t for t in team_ci if lo <= t["home_n"] <= hi]
    if sub:
        widths = [t["ci_95_width"] for t in sub]
        ci_width_groups.append({"n_range": f"{lo}-{hi}", "team_count": len(sub), "avg_ci_95_width": round(statistics.mean(widths), 4)})
        print(f"  n={lo}-{hi}: {len(sub)} teams, avg CI width={statistics.mean(widths):.3f}")

# Sample size needed for given precision
def min_n_for_precision(true_p, half_width, z=1.96):
    n = 4
    while n < 100000:
        se = math.sqrt(true_p * (1 - true_p) / n)
        if z * se <= half_width:
            return n
        n += 1
    return None

ss_recs = {}
for p in [0.35, 0.40, 0.45, 0.50]:
    for pw in [0.03, 0.05, 0.10]:
        ss_recs[f"p={p:.2f}_prec={pw:.2f}"] = min_n_for_precision(p, pw)

for k, v in ss_recs.items():
    print(f"  {k}: n={v}")

# ================================================================
# ASSEMBLE & WRITE
# ================================================================
output = {
    "metadata": {
        "analyzed_by": "Gideon - Quantitative Analyst, Trillions Empire",
        "total_clean_matches": N,
        "total_seasons": len(seasons_ordered),
        "total_teams": len(team_list),
        "method": "Vig-free probabilities from decimal odds. Walk-forward Kelly for Q1. Wilson 95% CI for proportions.",
        "date": "2026-05-07"
    },
    "question_1_kelly_thresholds": {
        "description": "For each confidence threshold 50-95%, bet on the outcome with highest vig-free probability using walk-forward Kelly (empirical win rate per odds bucket from prior seasons). Initial bankroll: $10,000.",
        "pure_kelly_reference": {
            "description": "Kelly betting on any outcome where vig-free prob × odds > 1 (market's own estimate). Should produce ~zero edge.",
            **pk
        },
        "threshold_results": kelly_results,
        "best_by_sharpe": best_sharpe_kelly,
        "best_by_profit": best_profit_kelly,
        "best_by_win_rate": best_wr_kelly
    },
    "question_2_stability": q2,
    "question_3_calibration": {
        "description": "Pooled calibration across all 3 outcomes. Each match contributes 3 observations (predicted prob vs actual occurrence). Bins 0-5%, 5-10%, ..., 95-100%.",
        "pooled_calibration_bins": calibration_pooled,
        "mean_absolute_error": round(mae, 4),
        "interpretation": "MAE measures avg deviation between predicted probability and actual frequency. Lower = better calibrated."
    },
    "question_4_correlations": {
        "team_home_away": {
            "description": "Pearson r between each team's home win rate and away win rate. Independent performance would give r ≈ 0; r > 0 means quality persists across venue.",
            "correlation": round(ha_corr, 4) if ha_corr is not None else None,
            "teams_analyzed": len(valid),
            "team_details": team_list
        },
        "odds_correlations": {
            "home_vs_away_odds": round(oha_corr, 4),
            "home_vs_draw_odds": round(ohd_corr, 4),
            "draw_vs_away_odds": round(oda_corr, 4),
            "n": N
        },
        "time_segment_pattern": {
            "description": "Outcome rates by normalized season position (0-10%, 10-20%, ..., 90-100%)",
            "segments": time_pattern
        }
    },
    "question_5_sample_size": {
        "description": "Confidence intervals for home win rates. CI width shrinks as sample size grows.",
        "team_ci_results": team_ci,
        "ci_width_by_sample_size": ci_width_groups,
        "sample_size_recommendations": ss_recs,
        "interpretation": "To estimate a ~45% win rate within ±5% at 95% confidence, need ~380 matches. For ±10%, need ~95 matches."
    }
}

with open(OUT, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n✓ Output: {OUT}")
print(f"  File size: {len(json.dumps(output, indent=2, default=str)):,} bytes")
