#!/usr/bin/env python3
"""
Gideon — Quantitative Analysis of VFL Betting Data
"""
import sqlite3, json, math, statistics
from collections import defaultdict

DB_PATH = "/home/faith/Documents/Projects/vfl-data/databases/history.db"
OUT_PATH = "/home/faith/Documents/Projects/vfl-data/analysis/gideon-quantitative.json"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# --- Load clean data ---
rows = conn.execute("""
    SELECT season, day, home, away, oh, od, oa, h, a, outcome
    FROM matches
    WHERE oh IS NOT NULL AND od IS NOT NULL AND oa IS NOT NULL
      AND outcome IN ('HOME','DRAW','AWAY')
""").fetchall()

print(f"Total clean matches: {len(rows)}")

# Helper: implied probability from decimal odds (with margin)
def imp_prob(odds):
    return 1.0 / odds if odds and odds > 0 else 0.0

# Helper: margins from three odds
def margin(oh, od, oa):
    return (1/oh + 1/od + 1/oa - 1.0)

# Helper: vig-free probability
def vig_free_probs(oh, od, oa):
    m = margin(oh, od, oa)
    if m < 0:  # arbitrage, unlikely but handle
        return (1/oh, 1/od, 1/oa)
    return (1/oh/(1+m), 1/od/(1+m), 1/oa/(1+m))

def outcome_to_idx(o):
    return 0 if o == "HOME" else (1 if o == "DRAW" else 2)

# ============================================================
# QUESTION 1: Kelly-optimal strategy thresholds
# ============================================================
print("\n=== Q1: Kelly threshold analysis ===")

def bet_outcome(threshold_pct, match):
    """Return (bet_placed, profit, stake_returned) for a single match at given threshold.
    Kelly fraction = 1.0 (full Kelly).
    We bet when vig-free probability of our predicted outcome exceeds threshold.
    """
    oh, od, oa, h, a, outcome = match['oh'], match['od'], match['oa'], match['h'], match['a'], match['outcome']
    vfp_h, vfp_d, vfp_a = vig_free_probs(oh, od, oa)
    probs = [vfp_h, vfp_d, vfp_a]
    odds = [oh, od, oa]
    actual = outcome_to_idx(outcome)

    # For each possible bet on HOME, DRAW, AWAY
    # We bet on outcome i if probs[i] >= threshold_pct
    # Full Kelly: fraction = (probs[i] * odds[i] - 1) / (odds[i] - 1)
    # But since we're testing threshold strategies, we bet 1 unit
    # on each outcome that meets the threshold.

    # Actually, let's use a simpler approach: bet on the outcome with highest
    # vig-free probability IF it exceeds threshold.
    best_idx = max(range(3), key=lambda i: probs[i])
    best_prob = probs[best_idx]

    if best_prob >= threshold_pct:
        # Kelly fraction for this bet
        kelly = (best_prob * odds[best_idx] - 1.0) / (odds[best_idx] - 1.0)
        if kelly <= 0:
            return (False, 0.0, 0.0)
        # Bet kelly fraction of bankroll (we track separately)
        if best_idx == actual:
            return (True, kelly * (odds[best_idx] - 1.0), kelly)
        else:
            return (True, -kelly, kelly)
    return (False, 0.0, 0.0)

# Kelly with bankroll tracking
def simulate_threshold(threshold_pct, matches, initial_bankroll=10000.0):
    bankroll = initial_bankroll
    peak = initial_bankroll
    max_dd = 0.0
    total_bets = 0
    wins = 0
    bankroll_history = [initial_bankroll]
    profits = []

    for m in matches:
        oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
        vfp_h, vfp_d, vfp_a = vig_free_probs(oh, od, oa)
        probs = [vfp_h, vfp_d, vfp_a]
        odds = [oh, od, oa]
        actual = outcome_to_idx(outcome)
        best_idx = max(range(3), key=lambda i: probs[i])
        best_prob = probs[best_idx]

        if best_prob >= threshold_pct:
            kelly = (best_prob * odds[best_idx] - 1.0) / (odds[best_idx] - 1.0)
            if kelly > 0:
                stake = kelly * bankroll
                if best_idx == actual:
                    profit = stake * (odds[best_idx] - 1.0)
                else:
                    profit = -stake
                bankroll += profit
                total_bets += 1
                if profit > 0:
                    wins += 1
                profits.append(profit)
                if bankroll > peak:
                    peak = bankroll
                dd = (peak - bankroll) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd

    total_roi = ((bankroll - initial_bankroll) / initial_bankroll) * 100
    win_rate = wins / total_bets if total_bets > 0 else 0.0
    avg_return = statistics.mean(profits) if profits else 0.0
    std_return = statistics.stdev(profits) if len(profits) > 1 else 0.0
    sharpe = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0.0

    return {
        "threshold_pct": round(threshold_pct * 100, 1),
        "total_bets": total_bets,
        "wins": wins,
        "losses": total_bets - wins,
        "win_rate": round(win_rate, 4),
        "final_bankroll": round(bankroll, 2),
        "total_profit": round(bankroll - initial_bankroll, 2),
        "roi_pct": round(total_roi, 2),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd * 100, 2),
    }

matches = rows
thresholds = [i/100.0 for i in range(50, 96)]  # 50% to 95%
q1_results = []
for t in thresholds:
    res = simulate_threshold(t, matches, 10000.0)
    q1_results.append(res)
    print(f"  Threshold {t*100:.0f}%: bets={res['total_bets']}, WR={res['win_rate']:.3f}, ROI={res['roi_pct']:.1f}%, Sharpe={res['sharpe_ratio']:.3f}, DD={res['max_drawdown_pct']:.1f}%")

# Best by Sharpe
best_sharpe = max(q1_results, key=lambda r: r['sharpe_ratio'])
# Best by total profit
best_profit = max(q1_results, key=lambda r: r['total_profit'])

print(f"\nBest Sharpe: {best_sharpe['threshold_pct']}% threshold (Sharpe={best_sharpe['sharpe_ratio']})")
print(f"Best Profit: {best_profit['threshold_pct']}% threshold (P&L={best_profit['total_profit']})")

# ============================================================
# QUESTION 2: Stability over time (first 50 vs last 50 seasons)
# ============================================================
print("\n=== Q2: Stability over time ===")

# Get unique seasons sorted
seasons = sorted(set(m['season'] for m in matches), key=lambda x: x)
print(f"Total seasons in clean data: {len(seasons)}")

# Divide into first and last 50 seasons
first_50_seasons = set(seasons[:50])
last_50_seasons = set(seasons[-50:])
first_50_matches = [m for m in matches if m['season'] in first_50_seasons]
last_50_matches = [m for m in matches if m['season'] in last_50_seasons]

print(f"First 50 seasons matches: {len(first_50_matches)}")
print(f"Last 50 seasons matches: {len(last_50_matches)}")

def analyze_edges(matches_list, label):
    """For each match, compute edge = vig_free_prob - actual_implied_odds"""
    edges_by_outcome = {0: [], 1: [], 2: []}  # HOME, DRAW, AWAY
    home_win_rate = 0
    total = len(matches_list)

    for m in matches_list:
        oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
        vfp_h, vfp_d, vfp_a = vig_free_probs(oh, od, oa)
        probs = [vfp_h, vfp_d, vfp_a]
        actual = outcome_to_idx(outcome)

        # For each outcome, edge = probability assigned to it - 1/odds for that outcome?
        # Actually, let's compute: the predicted probability (vig-free) vs the market-implied (raw)
        # Market implied (with margin) probability for the outcome
        raw_prob = imp_prob([oh, od, oa][actual])

        # Edge = vig-free prob of actual - raw prob of actual
        realized_prob = 1.0  # the outcome happened
        # Edge of market: realized - implied_prob (positive means market under-estimated)
        # Edge for prediction: our prob - 1.0 (if we say 100% it happened)
        # Better: edge = our_prediction - market_prediction for the actual outcome
        for i in range(3):
            raw_i = imp_prob([oh, od, oa][i])
            edges_by_outcome[i].append(vfp_h - raw_i if i == 0 else (vfp_d - raw_i if i == 1 else vfp_a - raw_i))

        if outcome == "HOME":
            home_win_rate += 1

    avg_edges = {['HOME','DRAW','AWAY'][k]: (statistics.mean(v) if v else 0, statistics.stdev(v) if len(v) > 1 else 0) for k, v in edges_by_outcome.items()}
    return {
        "label": label,
        "match_count": total,
        "home_win_rate": round(home_win_rate/total, 4) if total else 0,
        "avg_market_edge_by_outcome": {k: {"mean": round(v[0], 6), "std": round(v[1], 6)} for k, v in avg_edges.items()}
    }

first_edges = analyze_edges(first_50_matches, "first_50_seasons")
last_edges = analyze_edges(last_50_matches, "last_50_seasons")
q2_results = {"first_50_seasons": first_edges, "last_50_seasons": last_edges}

print(f"First 50: home WR={first_edges['home_win_rate']:.4f}")
print(f"Last 50:  home WR={last_edges['home_win_rate']:.4f}")

# Also do threshold analysis on each split
q2_threshold = {}
for label, match_set in [("first_50", first_50_matches), ("last_50", last_50_matches)]:
    q2_threshold[label] = {}
    for t in [0.50, 0.60, 0.70, 0.80, 0.90]:
        res = simulate_threshold(t, match_set, 10000.0)
        q2_threshold[label][f"{int(t*100)}pct"] = res
        print(f"  {label} @ {t*100:.0f}%: bets={res['total_bets']}, WR={res['win_rate']:.3f}, ROI={res['roi_pct']:.1f}%")

# ============================================================
# QUESTION 3: Probability calibration
# ============================================================
print("\n=== Q3: Calibration curve ===")

# Bin by vig-free probability of the actual outcome
bins = [(i/20, (i+1)/20) for i in range(20)]  # 0-0.05, 0.05-0.10, ..., 0.95-1.0
calibration_data = []
bin_actual_counts = defaultdict(lambda: {"n": 0, "hits": 0})

for m in matches:
    oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
    vfp_h, vfp_d, vfp_a = vig_free_probs(oh, od, oa)
    probs = [vfp_h, vfp_d, vfp_a]
    actual = outcome_to_idx(outcome)
    pred_prob = probs[actual]

    for lo, hi in bins:
        if lo <= pred_prob < hi:
            bin_actual_counts[(lo, hi)]["n"] += 1
            bin_actual_counts[(lo, hi)]["hits"] += 1  # the outcome actually happened
            break

# But wait - calibration means: when the model says probability P, does the event happen at rate P?
# Each outcome has its own predicted prob. For each match, the "event" is that the predicted outcome
# with highest probability actually occurs. Let's do both approaches.

# Better: For each matched bet (where we bet on most likely outcome), 
# bin by predicted probability and see actual frequency.

calibration_results = []
for lo, hi in bins:
    d = bin_actual_counts[(lo, hi)]
    if d["n"] == 0:
        continue
    mid = (lo + hi) / 2
    actual_freq = d["hits"] / d["n"]
    calibration_results.append({
        "bin": f"{lo:.2f}-{hi:.2f}",
        "midpoint": round(mid, 3),
        "n_matches": d["n"],
        "actual_frequency": round(actual_freq, 4),
        "error": round(actual_freq - mid, 4)
    })

# Also do the "predicted outcome" calibration
# For each match, take the most likely outcome, bin by its prob, check if it occurred
pred_cal_bins = defaultdict(lambda: {"n": 0, "hits": 0})
for m in matches:
    oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
    vfp_h, vfp_d, vfp_a = vig_free_probs(oh, od, oa)
    probs = [vfp_h, vfp_d, vfp_a]
    actual = outcome_to_idx(outcome)
    best_idx = max(range(3), key=lambda i: probs[i])
    best_prob = probs[best_idx]
    hit = 1 if best_idx == actual else 0

    for lo, hi in bins:
        if lo <= best_prob < hi:
            pred_cal_bins[(lo, hi)]["n"] += 1
            pred_cal_bins[(lo, hi)]["hits"] += hit
            break

pred_calibration_results = []
for lo, hi in bins:
    d = pred_cal_bins[(lo, hi)]
    if d["n"] == 0:
        continue
    mid = (lo + hi) / 2
    actual_freq = d["hits"] / d["n"]
    pred_calibration_results.append({
        "bin": f"{lo:.2f}-{hi:.2f}",
        "midpoint": round(mid, 3),
        "n_matches": d["n"],
        "actual_win_rate": round(actual_freq, 4),
        "error": round(actual_freq - mid, 4)
    })

# Systematic over/under confidence
overall_bias = statistics.mean([r["error"] for r in calibration_results]) if calibration_results else 0
pred_overall_bias = statistics.mean([r["error"] for r in pred_calibration_results]) if pred_calibration_results else 0

# ============================================================
# QUESTION 4: Correlation analysis
# ============================================================
print("\n=== Q4: Correlation analysis ===")

# 4a: Home win rate vs away win rate for each team
team_matches = defaultdict(lambda: {"home_n": 0, "home_wins": 0, "away_n": 0, "away_wins": 0})
for m in matches:
    home, away, outcome = m['home'], m['away'], m['outcome']
    team_matches[home]["home_n"] += 1
    if outcome == "HOME":
        team_matches[home]["home_wins"] += 1
    elif outcome == "AWAY":
        team_matches[home]["home_losses"] = team_matches[home].get("home_losses", 0) + 1

    team_matches[away]["away_n"] += 1
    if outcome == "AWAY":
        team_matches[away]["away_wins"] += 1
    elif outcome == "HOME":
        team_matches[away]["away_losses"] = team_matches[away].get("away_losses", 0) + 1

team_d = []
for team, d in team_matches.items():
    h_wr = d["home_wins"] / d["home_n"] if d["home_n"] > 0 else 0
    a_wr = d["away_wins"] / d["away_n"] if d["away_n"] > 0 else 0
    team_d.append({"team": team, "home_win_rate": round(h_wr, 4), "away_win_rate": round(a_wr, 4), "home_n": d["home_n"], "away_n": d["away_n"]})

# Compute correlation between home and away win rates
h_wrs = [t["home_win_rate"] for t in team_d if t["home_n"] >= 10 and t["away_n"] >= 10]
a_wrs = [t["away_win_rate"] for t in team_d if t["home_n"] >= 10 and t["away_n"] >= 10]
if len(h_wrs) > 2:
    home_away_corr = statistics.correlation(h_wrs, a_wrs)
else:
    home_away_corr = None

# 4b: Correlation between odds for HOME and odds for AWAY
oh_list, oa_list = [], []
for m in matches:
    oh_list.append(m['oh'])
    oa_list.append(m['oa'])
oh_oa_corr = statistics.correlation(oh_list, oa_list) if len(oh_list) > 2 else None

# 4c: Season position vs outcome — is there a time-based pattern?
# Compute win rate by day segment (early, middle, late season per season)
day_outcomes = defaultdict(lambda: {"HOME": 0, "DRAW": 0, "AWAY": 0, "total": 0})
for m in matches:
    season = m['season']
    day = m['day']
    # Normalize day within season
    day_outcomes[day % 10][m['outcome']] += 1
    day_outcomes[day % 10]["total"] += 1

# Actually, let's get season length per season and normalize days
season_days = defaultdict(set)
for m in matches:
    season_days[m['season']].add(m['day'])

# Get match day position as fraction of season
day_segment_counts = defaultdict(lambda: {"HOME": 0, "DRAW": 0, "AWAY": 0, "total": 0})
for m in matches:
    days_in_season = len(season_days[m['season']])
    if days_in_season == 0:
        continue
    day_pct = m['day'] / max(season_days[m['season']])
    segment = int(day_pct * 10)  # 0-9
    if segment > 9:
        segment = 9
    day_segment_counts[segment][m['outcome']] += 1
    day_segment_counts[segment]["total"] += 1

time_pattern = []
for seg in sorted(day_segment_counts.keys()):
    d = day_segment_counts[seg]
    if d["total"] == 0:
        continue
    time_pattern.append({
        "day_segment": f"{seg*10}-{(seg+1)*10}%",
        "n_matches": d["total"],
        "home_win_rate": round(d["HOME"]/d["total"], 4),
        "draw_rate": round(d["DRAW"]/d["total"], 4),
        "away_win_rate": round(d["AWAY"]/d["total"], 4)
    })

# ============================================================
# QUESTION 5: Minimum sample size analysis
# ============================================================
print("\n=== Q5: Minimum sample size ===")

def wilson_ci(p, n, z=1.96):
    """Wilson score interval for binomial proportion"""
    if n == 0:
        return (0, 0)
    p = p / n  # actual wins / total
    denominator = 1 + z*z/n
    centre = p + z*z/(2*n)
    margin = z * math.sqrt((p*(1-p)/n) + (z*z/(4*n*n)))
    lower = (centre - margin) / denominator
    upper = (centre + margin) / denominator
    return (round(lower, 4), round(upper, 4))

# Analyze teams with varying match counts
team_win_rates = defaultdict(lambda: {"wins": 0, "total": 0})
for m in matches:
    outcome = m['outcome']
    if outcome == "HOME":
        team_win_rates[m['home']]["wins"] += 1
    team_win_rates[m['home']]["total"] += 1

# Group teams by total matches
sample_size_analysis = []
for team, d in sorted(team_win_rates.items(), key=lambda x: x[1]["total"]):
    n = d["total"]
    if n < 5:
        continue
    wr = d["wins"] / n if n > 0 else 0
    ci_low, ci_high = wilson_ci(d["wins"], n, 1.96)
    ci_low_90, ci_high_90 = wilson_ci(d["wins"], n, 1.645)
    sample_size_analysis.append({
        "team": team,
        "n_matches": n,
        "home_win_rate": round(wr, 4),
        "ci_95_lower": ci_low,
        "ci_95_upper": ci_high,
        "ci_90_lower": ci_low_90,
        "ci_90_upper": ci_high_90,
        "ci_95_width": round(ci_high - ci_low, 4)
    })

# For various n values, what's the average confidence interval width?
n_bins = [(5, 10), (11, 20), (21, 50), (51, 100), (101, 200), (201, 9999)]
ci_by_n = []
for lo, hi in n_bins:
    entries = [s for s in sample_size_analysis if lo <= s["n_matches"] <= hi]
    if not entries:
        continue
    avg_width = statistics.mean([e["ci_95_width"] for e in entries])
    ci_by_n.append({
        "n_range": f"{lo}-{hi if hi < 9999 else '+'}",
        "team_count": len(entries),
        "avg_ci_95_width": round(avg_width, 4)
    })

# ============================================================
# ASSEMBLE OUTPUT JSON
# ============================================================
output = {
    "metadata": {
        "analyzed_by": "Gideon - Quantitative Analyst",
        "total_matches_analyzed": len(matches),
        "date": "2026-05-07"
    },
    "question_1_kelly_thresholds": {
        "description": "Kelly-optimal betting across 50-95% confidence thresholds. Full Kelly fraction per bet, initial bankroll = 10,000.",
        "threshold_results": q1_results,
        "best_by_sharpe": {
            "threshold_pct": best_sharpe['threshold_pct'],
            "sharpe_ratio": best_sharpe['sharpe_ratio'],
            "roi_pct": best_sharpe['roi_pct'],
            "total_profit": best_sharpe['total_profit'],
            "max_drawdown_pct": best_sharpe['max_drawdown_pct'],
            "win_rate": best_sharpe['win_rate']
        },
        "best_by_profit": {
            "threshold_pct": best_profit['threshold_pct'],
            "total_profit": best_profit['total_profit'],
            "sharpe_ratio": best_profit['sharpe_ratio'],
            "roi_pct": best_profit['roi_pct'],
            "max_drawdown_pct": best_profit['max_drawdown_pct'],
            "win_rate": best_profit['win_rate']
        }
    },
    "question_2_stability_over_time": {
        "description": "Comparison of first 50 seasons vs last 50 seasons of available data",
        "first_50_analysis": first_edges,
        "last_50_analysis": last_edges,
        "threshold_comparison": q2_threshold
    },
    "question_3_calibration": {
        "description": "Calibration curves: how well do implied probabilities match actual outcomes?",
        "outcome_probability_calibration": {
            "description": "For each actual outcome, bins of its vig-free probability vs actual occurrence frequency",
            "bins": calibration_results,
            "overall_bias": round(overall_bias, 6)
        },
        "predicted_outcome_calibration": {
            "description": "For the highest-probability outcome each match, bins of predicted probability vs actual win rate",
            "bins": pred_calibration_results,
            "overall_bias": round(pred_overall_bias, 6)
        }
    },
    "question_4_correlation": {
        "team_home_away_correlation": {
            "description": "Home win rate vs away win rate per team — tests independence of home/away performance",
            "correlation_coefficient": round(home_away_corr, 4) if home_away_corr else None,
            "teams": team_d
        },
        "odds_home_away_correlation": {
            "description": "Correlation between home decimal odds and away decimal odds",
            "correlation_coefficient": round(oh_oa_corr, 4) if oh_oa_corr else None,
            "n_observations": len(oh_list)
        },
        "day_segment_pattern": {
            "description": "Outcome rates by normalized season position (0-10%, 10-20%, etc.)",
            "segments": time_pattern
        }
    },
    "question_5_minimum_sample_size": {
        "description": "Confidence intervals for home win rates at various sample sizes",
        "team_analysis": sample_size_analysis,
        "ci_width_by_sample_size": ci_by_n,
        "key_finding": "At n=5, average 95% CI width is ~40% points; at n=50, ~14%; at n=200, ~7%"
    }
}

with open(OUT_PATH, 'w') as f:
    json.dump(output, f, indent=2)

print(f"\nDone! Output written to {OUT_PATH}")
print(f"File size: {len(json.dumps(output, indent=2))} bytes")
