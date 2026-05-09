#!/usr/bin/env python3
"""
Gideon — Quantitative Analysis of VFL Betting Data v2
Corrected approach: empirical frequencies vs market-implied probabilities
"""
import sqlite3, json, math, statistics
from collections import defaultdict

DB_PATH = "/home/faith/Documents/Projects/vfl-data/databases/history.db"
OUT_PATH = "/home/faith/Documents/Projects/vfl-data/analysis/gideon-quantitative.json"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT season, day, home, away, oh, od, oa, h, a, outcome
    FROM matches
    WHERE oh IS NOT NULL AND od IS NOT NULL AND oa IS NOT NULL
      AND outcome IN ('HOME','DRAW','AWAY')
""").fetchall()

rows = [dict(r) for r in rows]
N = len(rows)
print(f"Total clean matches: {N}")

# Helpers
def margin(oh, od, oa):
    return 1.0/oh + 1.0/od + 1.0/oa - 1.0

def vig_free_probs(oh, od, oa):
    m = margin(oh, od, oa)
    return (1.0/oh/(1+m), 1.0/od/(1+m), 1.0/oa/(1+m))

def outcome_idx(o):
    return 0 if o == "HOME" else (1 if o == "DRAW" else 2)

# ================================================================
# Helper: break-even frequency required for a bet at given odds
# ================================================================
def breakeven_pct(odds):
    return 1.0 / odds

# ================================================================
# Q1: Kelly-optimal strategy
# Approach: For each distinct odds range, compute empirical win rate.
# Bet when empirical win rate > breakeven rate.
# ================================================================
print("\n=== Q1: Kelly Threshold Analysis ===")

# Build empirical probability curves by odds bucket
# For each of the 3 outcomes (HOME, DRAW, AWAY), group by odds range
odds_buckets = defaultdict(lambda: {"n": 0, "wins": 0, "total_odds": 0.0})

for m in rows:
    oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
    actual = outcome_idx(outcome)
    for idx, odd in [(0, oh), (1, od), (2, oa)]:
        bucket = round(odd * 20) / 20.0  # round to nearest 0.05
        odds_buckets[(idx, bucket)]["n"] += 1
        odds_buckets[(idx, bucket)]["total_odds"] += odd
        if idx == actual:
            odds_buckets[(idx, bucket)]["wins"] += 1

# Build empirical probability table
empirical_probs = {}
for (idx, bucket), d in odds_buckets.items():
    if d["n"] < 10:
        continue
    emp_p = d["wins"] / d["n"]
    avg_odds = d["total_odds"] / d["n"]
    be_p = 1.0 / avg_odds if avg_odds > 0 else 0
    edge = emp_p - be_p
    empirical_probs[(idx, bucket)] = {
        "n": d["n"],
        "wins": d["wins"],
        "empirical_p": emp_p,
        "avg_odds": round(avg_odds, 4),
        "breakeven_p": round(be_p, 4),
        "edge": round(edge, 4)
    }

print(f"Built {len(empirical_probs)} odds buckets with n>=10")
# Show some buckets
sorted_buckets = sorted(empirical_probs.items(), key=lambda x: -abs(x[1]["edge"]))
for (idx, bucket), d in sorted_buckets[:10]:
    label = ["HOME","DRAW","AWAY"][idx]
    print(f"  {label} @ {bucket}: n={d['n']}, emp={d['empirical_p']:.4f}, be={d['breakeven_p']:.4f}, edge={d['edge']:.4f}")

# Now simulate Kelly betting using these empirical probabilities
# For each match, look up the empirical win rate for each odds bucket
# and bet if empirical win rate > vig-free rate (or > breakeven)
def simulate_kelly_empirical(rows, empirical_probs, edge_threshold=0.0, initial_bankroll=10000.0):
    """Bet when empirical win rate > breakeven + edge_threshold"""
    bankroll = initial_bankroll
    peak = initial_bankroll
    max_dd = 0.0
    total_bets = 0
    wins = 0
    profits = []
    bankroll_hist = [initial_bankroll]

    for m in rows:
        oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
        actual = outcome_idx(outcome)
        odds_list = [(0, oh), (1, od), (2, oa)]

        best_edge = -999
        best_info = None
        bet_idx = None

        for idx, odd in odds_list:
            bucket = round(odd * 20) / 20.0
            if (idx, bucket) not in empirical_probs:
                continue
            info = empirical_probs[(idx, bucket)]
            edge = info["edge"]  # empirical - breakeven
            if edge > best_edge and edge >= edge_threshold:
                best_edge = edge
                best_info = info
                bet_idx = idx

        if best_info is not None and best_edge > 0:
            # Kelly fraction using empirical win rate
            odd = odds_list[bet_idx][1]
            emp_p = best_info["empirical_p"]
            kelly = (emp_p * odd - 1.0) / (odd - 1.0)
            if kelly > 0:
                stake = kelly * bankroll
                if bet_idx == actual:
                    profit = stake * (odd - 1.0)
                else:
                    profit = -stake
                bankroll += profit
                total_bets += 1
                profits.append(profit)
                if profit > 0:
                    wins += 1
                if bankroll > peak:
                    peak = bankroll
                dd = (peak - bankroll) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd

    total_profit = bankroll - initial_bankroll
    roi = total_profit / initial_bankroll * 100
    win_rate = wins / total_bets if total_bets > 0 else 0.0
    avg_ret = statistics.mean(profits) if profits else 0.0
    std_ret = statistics.stdev(profits) if len(profits) > 1 else 0.0
    sharpe = (avg_ret / std_ret) * math.sqrt(252) if std_ret > 0 else 0.0

    return {
        "total_bets": total_bets,
        "wins": wins,
        "losses": total_bets - wins,
        "win_rate": round(win_rate, 4),
        "final_bankroll": round(bankroll, 2),
        "total_profit": round(total_profit, 2),
        "roi_pct": round(roi, 2),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd * 100, 2),
    }

# Edge thresholds to test (edge = empirical win rate - breakeven probability)
edge_thresholds = [0.0, 0.02, 0.05, 0.08, 0.10, 0.12, 0.15]
q1_empirical = {}
for et in edge_thresholds:
    res = simulate_kelly_empirical(rows, empirical_probs, edge_threshold=et, initial_bankroll=10000.0)
    q1_empirical[f"edge_{et:.2f}"] = res
    print(f"  Edge >= {et:.0%}: bets={res['total_bets']}, WR={res['win_rate']:.3f}, ROI={res['roi_pct']:.1f}%, "
          f"Sharpe={res['sharpe_ratio']:.3f}, P&L={res['total_profit']:.0f}, DD={res['max_drawdown_pct']:.1f}%")

# Also do direct vig-free threshold betting (non-Kelly, flat stake)
def simulate_threshold_flat(rows, threshold_pct, stake=100.0):
    """Bet 1 unit when vig-free prob of most likely outcome >= threshold.
    No Kelly, just flat betting to compare."""
    total_bets = 0
    wins = 0
    profit = 0.0
    profits = []
    for m in rows:
        oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
        vfp = vig_free_probs(oh, od, oa)
        odds = [oh, od, oa]
        actual = outcome_idx(outcome)
        best_idx = max(range(3), key=lambda i: vfp[i])
        best_prob = vfp[best_idx]
        if best_prob >= threshold_pct:
            total_bets += 1
            if best_idx == actual:
                profit += stake * (odds[best_idx] - 1.0)
                wins += 1
                profits.append(stake * (odds[best_idx] - 1.0))
            else:
                profit -= stake
                profits.append(-stake)

    roi = (profit / (total_bets * stake)) * 100 if total_bets > 0 else 0
    win_rate = wins / total_bets if total_bets > 0 else 0.0
    avg_ret = statistics.mean(profits) if profits else 0.0
    std_ret = statistics.stdev(profits) if len(profits) > 1 else 0.0
    sharpe = (avg_ret / std_ret) * math.sqrt(252) if std_ret > 0 else 0.0

    return {
        "threshold_pct": round(threshold_pct * 100, 1),
        "total_bets": total_bets,
        "wins": wins,
        "losses": total_bets - wins,
        "win_rate": round(win_rate, 4),
        "total_profit": round(profit, 2),
        "roi_per_bet_pct": round(roi, 2),
        "sharpe_ratio": round(sharpe, 4) if sharpe else 0.0,
    }

q1_thresholds = {}
for t in [i/100.0 for i in range(50, 96)]:
    res = simulate_threshold_flat(rows, t, 100.0)
    q1_thresholds[str(int(t*100))] = res
    if res["total_bets"] > 0:
        print(f"  Threshold {t*100:.0f}%: bets={res['total_bets']}, WR={res['win_rate']:.3f}, ROI={res['roi_per_bet_pct']:.1f}%, P&L={res['total_profit']:.0f}")

# Best by various metrics among flat threshold results
q1_threshold_list = [v for v in q1_thresholds.values()]
best_sharpe_flat = max(q1_threshold_list, key=lambda r: r['sharpe_ratio']) if q1_threshold_list else None
best_profit_flat = max(q1_threshold_list, key=lambda r: r['total_profit']) if q1_threshold_list else None

# ================================================================
# Q2: Stability Over Time
# ================================================================
print("\n=== Q2: Stability Over Time ===")

# Sort seasons properly
season_list = sorted(set(m['season'] for m in rows))
print(f"Total distinct seasons: {len(season_list)}")

# Split into chronological halves
half = len(season_list) // 2
early_seasons = set(season_list[:half])
late_seasons = set(season_list[half:])
early_rows = [m for m in rows if m['season'] in early_seasons]
late_rows = [m for m in rows if m['season'] in late_seasons]
print(f"Early ({len(season_list[:half])} seasons): {len(early_rows)} matches")
print(f"Late ({len(season_list[half:])} seasons): {len(late_rows)} matches")

def analyze_season_split(matches_list, label):
    outcomes = {"HOME": 0, "DRAW": 0, "AWAY": 0}
    for m in matches_list:
        outcomes[m['outcome']] += 1
    total = len(matches_list)
    out_rates = {k: round(v/total, 4) for k, v in outcomes.items()}
    
    # Home win rate
    h_wr = outcomes["HOME"] / total
    
    # Average margin
    avg_m = statistics.mean(margin(m['oh'], m['od'], m['oa']) for m in matches_list)
    
    # Average odds
    avg_oh = statistics.mean(m['oh'] for m in matches_list)
    avg_od = statistics.mean(m['od'] for m in matches_list)
    avg_oa = statistics.mean(m['oa'] for m in matches_list)
    
    return {
        "label": label,
        "match_count": total,
        "outcome_rates": out_rates,
        "home_win_rate": round(h_wr, 4),
        "avg_margin": round(avg_m, 4),
        "avg_odds": {"home": round(avg_oh, 4), "draw": round(avg_od, 4), "away": round(avg_oa, 4)}
    }

q2_results = {
    "early_analysis": analyze_season_split(early_rows, "early_half"),
    "late_analysis": analyze_season_split(late_rows, "late_half"),
    "full_analysis": analyze_season_split(rows, "full_dataset")
}

# Threshold performance on each split
q2_threshold = {}
for label, split_rows in [("early", early_rows), ("late", late_rows), ("full", rows)]:
    q2_threshold[label] = {}
    for t in [0.50, 0.55, 0.60, 0.65, 0.70]:
        res = simulate_threshold_flat(split_rows, t, 100.0)
        q2_threshold[label][f"{int(t*100)}pct"] = res

# ================================================================
# Q3: Calibration Curve
# ================================================================
print("\n=== Q3: Calibration ===")

def wilson_ci(p, n, z=1.96):
    if n == 0:
        return (0, 0)
    denom = 1 + z*z/n
    centre = p/n + z*z/(2*n)
    margin = z * math.sqrt(p/n * (1-p/n) / n + z*z/(4*n*n))
    return ((centre - margin) / denom, (centre + margin) / denom)

# Calibration: For buckets of market-implied probability (vig-free),
# what fraction actually materializes?
# For HOME outcome: when market says HOME prob ~ P, how often does HOME win?
# We'll bin by vig-free prob of the actual outcome and see if freq matches.

# Method A: Calibration for each outcome separately
calibration_by_outcome = {}
for outcome_label, outcome_val, odds_key in [("HOME", "HOME", "oh"), ("DRAW", "DRAW", "od"), ("AWAY", "AWAY", "oa")]:
    bins = defaultdict(lambda: {"n": 0, "occurred": 0})
    for m in rows:
        oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
        vfp = vig_free_probs(oh, od, oa)
        idx = outcome_idx(outcome)
        prob_i = vfp[idx]
        bin_key = min(int(prob_i * 20), 19)
        bins[bin_key]["n"] += 1
        if outcome == outcome_val:
            bins[bin_key]["occurred"] += 1
    
    cal = []
    for bk in sorted(bins.keys()):
        d = bins[bk]
        mid = (bk + 0.5) / 20.0
        freq = d["occurred"] / d["n"]
        ci_low, ci_high = wilson_ci(d["occurred"], d["n"], 1.96)
        cal.append({
            "bin_mid": round(mid, 3),
            "bin_range": f"{bk/20:.2f}-{(bk+1)/20:.2f}",
            "n_matches": d["n"],
            "predicted_prob": round(mid, 4),
            "actual_frequency": round(freq, 4),
            "error": round(freq - mid, 4),
            "ci_95_lower": round(ci_low, 4),
            "ci_95_upper": round(ci_high, 4)
        })
    calibration_by_outcome[outcome_label] = cal

# Method B: Willingness to bet calibration
# For each match, bet on the outcome with highest vig-free prob IF it exceeds threshold.
# How often does this pay off?
threshold_calibration = []
for pct in [i/100.0 for i in range(35, 80)]:
    total = 0
    hits = 0
    for m in rows:
        oh, od, oa, outcome = m['oh'], m['od'], m['oa'], m['outcome']
        vfp = vig_free_probs(oh, od, oa)
        best_idx = max(range(3), key=lambda i: vfp[i])
        best_prob = vfp[best_idx]
        if best_prob >= pct:
            total += 1
            if outcome_idx(outcome) == best_idx:
                hits += 1
    if total >= 5:
        freq = hits / total
        threshold_calibration.append({
            "threshold": round(pct * 100, 1),
            "n_bets": total,
            "predicted_prob": round(pct, 4),
            "actual_win_rate": round(freq, 4),
            "error": round(freq - pct, 4)
        })

# ================================================================
# Q4: Correlation Analysis
# ================================================================
print("\n=== Q4: Correlations ===")

# 4a: Team home vs away independence
team_stats = defaultdict(lambda: {"home_n": 0, "home_wins": 0, "away_n": 0, "away_wins": 0})
for m in rows:
    team_stats[m['home']]["home_n"] += 1
    if m['outcome'] == "HOME":
        team_stats[m['home']]["home_wins"] += 1
    team_stats[m['away']]["away_n"] += 1
    if m['outcome'] == "AWAY":
        team_stats[m['away']]["away_wins"] += 1

team_list = []
for team, d in team_stats.items():
    h_wr = d['home_wins'] / d['home_n'] if d['home_n'] >= 10 else 0
    a_wr = d['away_wins'] / d['away_n'] if d['away_n'] >= 10 else 0
    team_list.append({
        "team": team,
        "home_n": d["home_n"],
        "away_n": d["away_n"],
        "home_win_rate": round(h_wr, 4),
        "away_win_rate": round(a_wr, 4)
    })

# Pearson correlation between home and away win rates (teams with n>=20 each)
valid_teams = [t for t in team_list if t["home_n"] >= 20 and t["away_n"] >= 20]
if len(valid_teams) >= 3:
    h_wrs_v = [t["home_win_rate"] for t in valid_teams]
    a_wrs_v = [t["away_win_rate"] for t in valid_teams]
    home_away_corr = statistics.correlation(h_wrs_v, a_wrs_v)
else:
    home_away_corr = None

# Also compute: if home/away were truly independent, correlation = ?
# Under independence, home win rate and away win rate would be negatively correlated
# (teams that are strong at home aren't necessarily strong away)

# 4b: HOME odds vs AWAY odds correlation
oh_list = [m['oh'] for m in rows]
oa_list = [m['oa'] for m in rows]
oh_oa_corr = statistics.correlation(oh_list, oa_list)

# 4c: Season position vs outcome
# Get max day per season
season_max_day = {}
for m in rows:
    if m['season'] not in season_max_day or m['day'] > season_max_day[m['season']]:
        season_max_day[m['season']] = m['day']

day_pattern = defaultdict(lambda: {"HOME": 0, "DRAW": 0, "AWAY": 0, "total": 0})
for m in rows:
    max_day = season_max_day.get(m['season'], 38)
    pos = (m['day'] / max_day) if max_day > 0 else 0
    seg = min(9, int(pos * 10))
    day_pattern[seg][m['outcome']] += 1
    day_pattern[seg]["total"] += 1

time_pattern = []
for seg in sorted(day_pattern.keys()):
    d = day_pattern[seg]
    t = d["total"]
    time_pattern.append({
        "segment": f"{seg*10}-{(seg+1)*10}%",
        "n": t,
        "home_rate": round(d["HOME"]/t, 4),
        "draw_rate": round(d["DRAW"]/t, 4),
        "away_rate": round(d["AWAY"]/t, 4)
    })

# ================================================================
# Q5: Minimum Sample Size
# ================================================================
print("\n=== Q5: Minimum Sample Size ===")

# For each team, compute home win rate with confidence intervals
team_wr_ci = []
for team, d in team_stats.items():
    n = d["home_n"]
    if n < 5:
        continue
    wr = d["home_wins"] / n
    ci_low, ci_high = wilson_ci(d["home_wins"], n, 1.96)
    ci_low_90, ci_high_90 = wilson_ci(d["home_wins"], n, 1.645)
    team_wr_ci.append({
        "team": team,
        "n_home_matches": n,
        "home_win_rate": round(wr, 4),
        "ci_95": [round(ci_low, 4), round(ci_high, 4)],
        "ci_90": [round(ci_low_90, 4), round(ci_high_90, 4)],
        "ci_95_width": round(ci_high - ci_low, 4)
    })

# Group by sample size to show CI width
n_groups = [(5, 10), (11, 20), (21, 50), (51, 100), (101, 200)]
ci_by_n = []
for lo, hi in n_groups:
    subset = [t for t in team_wr_ci if lo <= t["n_home_matches"] <= hi]
    if not subset:
        continue
    widths = [t["ci_95_width"] for t in subset]
    ci_by_n.append({
        "n_range": f"{lo}-{hi}",
        "team_count": len(subset),
        "avg_ci_95_width": round(statistics.mean(widths), 4),
        "min_ci_95_width": round(min(widths), 4),
        "max_ci_95_width": round(max(widths), 4)
    })

# Also do a Monte Carlo simulation: for a true win rate of 45%,
# how many matches needed for the observed rate to be within ±5%?
def sample_size_for_precision(target_p, precision, z=1.96):
    """Minimum n such that CI width <= 2*precision"""
    n = 5
    while n < 10000:
        se = math.sqrt(target_p * (1 - target_p) / n)
        width = 2 * z * se
        if width <= 2 * precision:
            return n
        n += 1
    return None

sample_size_recs = {}
for true_p in [0.35, 0.40, 0.45, 0.50]:
    for prec in [0.03, 0.05, 0.10]:
        key = f"p={true_p:.2f}_prec={prec:.2f}"
        n_req = sample_size_for_precision(true_p, prec)
        sample_size_recs[key] = n_req

# ================================================================
# ASSEMBLE OUTPUT
# ================================================================
output = {
    "metadata": {
        "analyzed_by": "Gideon - Quantitative Analyst",
        "total_clean_matches": N,
        "total_seasons": len(season_list),
        "date": "2026-05-07"
    },
    "question_1_kelly_strategy": {
        "description": "Analysis of betting strategies on VFL match data. Two approaches: (1) Empirical frequency method using odds-bucket historical win rates vs breakeven, (2) Direct vig-free probability threshold betting.",
        "empirical_edge_strategy": {
            "description": "For each odds bucket (rounded to 0.05), compute empirical win rate. Bet using Kelly when empirical win rate > breakeven + edge_threshold.",
            "results": q1_empirical,
            "odds_bucket_details": {f"{['HOME','DRAW','AWAY'][k]}@{v:.2f}": empirical_probs[(k,v)]
                                     for k,v in sorted(empirical_probs.keys(), key=lambda x: -empirical_probs[x]['edge'])[:20]}
        },
        "vig_free_threshold_strategy": {
            "description": "Flat bet ($100) on the most likely outcome when its vig-free probability exceeds threshold.",
            "results": q1_thresholds,
            "best_by_sharpe": best_sharpe_flat,
            "best_by_profit": best_profit_flat
        }
    },
    "question_2_stability": {
        "description": "Comparison of early half vs late half of seasons to test pattern stability",
        "season_count": len(season_list),
        "early_half_analysis": q2_results["early_analysis"],
        "late_half_analysis": q2_results["late_analysis"],
        "full_analysis": q2_results["full_analysis"],
        "threshold_performance_by_split": q2_threshold
    },
    "question_3_calibration": {
        "description": "Probability calibration: how well do market-implied (vig-free) probabilities predict actual outcomes?",
        "calibration_by_outcome": calibration_by_outcome,
        "threshold_confidence_calibration": threshold_calibration
    },
    "question_4_correlation": {
        "team_home_away_correlation": {
            "description": "Pearson correlation between teams' home win rate and away win rate (teams with >=20 home and away matches)",
            "correlation": round(home_away_corr, 4) if home_away_corr is not None else None,
            "teams_analyzed": len(valid_teams),
            "team_details": team_list
        },
        "odds_home_away_correlation": {
            "description": "Pearson correlation between decimal odds for HOME and AWAY across all matches",
            "correlation": round(oh_oa_corr, 4),
            "n_observations": len(oh_list)
        },
        "time_pattern": {
            "description": "Outcome distribution by normalized season position",
            "segments": time_pattern
        }
    },
    "question_5_sample_size": {
        "description": "Confidence intervals for team win rates at various sample sizes, with sample size recommendations",
        "team_win_rate_analysis": team_wr_ci,
        "ci_width_by_sample_size": ci_by_n,
        "sample_size_recommendations": {
            "description": "Minimum n required for a given precision at 95% confidence",
            "by_true_probability": sample_size_recs
        }
    }
}

with open(OUT_PATH, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nOutput written to {OUT_PATH}")
# Print summary stats
print(f"\n=== SUMMARY ===")
print(f"Total matches: {N}")
print(f"Seasons: {len(season_list)}")
print(f"Teams: {len(team_list)}")

# Calibration bias
for outcome in ["HOME", "DRAW", "AWAY"]:
    cal = calibration_by_outcome.get(outcome, [])
    if cal:
        avg_err = statistics.mean([c["error"] for c in cal])
        print(f"  {outcome} calibration avg error: {avg_err:.4f}")

# Key correlation
print(f"  Home odds vs Away odds correlation: {oh_oa_corr:.4f}")
print(f"  Teams home/away WR correlation: {home_away_corr}")
