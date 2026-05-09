#!/usr/bin/env python3
"""Hypothesis-driven forensic analysis of VFL betting data."""
import sqlite3
import json
import sys
from collections import defaultdict

DB = "/home/faith/Documents/Projects/vfl-data/databases/history.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

results = {}

# ---- Normalize team names ----
TEAM_ALIASES = {
    "MANCHESTER BLUE": "Manchester Blue",
    "Manchester Blue": "Manchester Blue",
    "MANCHESTER RED": "Manchester Red",
    "Manchester Red": "Manchester Red",
    "LIVERPOOL": "Liverpool",
    "Liverpool": "Liverpool",
    "CHELSEA": "Chelsea",
    "Chelsea": "Chelsea",
    "LONDON GUNS": "London Guns",
    "London Guns": "London Guns",
    "TOTTENHAM": "Tottenham",
    "Tottenham": "Tottenham",
    "ASTON VILLA": "Aston Villa",
    "Aston Villa": "Aston Villa",
    "WEST HAM": "West Ham",
    "West Ham": "West Ham",
    "EVERTON": "Everton",
    "Everton": "Everton",
    "WOLVERHAMPTON": "Wolverhampton",
    "Wolverhampton": "Wolverhampton",
    "BRIGHTON": "Brighton",
    "Brighton": "Brighton",
    "NEWCASTLE": "Newcastle",
    "Newcastle": "Newcastle",
    "LEEDS": "Leeds",
    "Leeds": "Leeds",
    "CRYSTAL PALACE": "Crystal Palace",
    "Crystal Palace": "Crystal Palace",
    "FULHAM": "Fulham",
    "Fulham": "Fulham",
    "BOURNEMOUTH": "Bournemouth",
    "Bournemouth": "Bournemouth",
}

TIER_1 = {"Manchester Blue", "Liverpool", "Manchester Red", "Chelsea"}
TIER_2 = {"London Guns", "Tottenham", "Aston Villa"}
TIER_3 = {"West Ham", "Everton", "Wolves" if False else "Wolverhampton", "Brighton"}
TIER_3 = {"West Ham", "Everton", "Wolverhampton", "Brighton"}
TIER_4 = {"Newcastle", "Leeds", "Crystal Palace", "Fulham", "Bournemouth"}

def norm_team(t):
    t = t.strip()
    return TEAM_ALIASES.get(t.upper(), t.title())

def outcome_map(out):
    out = out.strip().upper()
    if out in ('H', 'HOME'):
        return 'HOME'
    if out in ('A', 'AWAY'):
        return 'AWAY'
    if out in ('D', 'DRAW'):
        return 'DRAW'
    return None

# ============================================================
# H1: Win Quota — Teams have predictable win ceilings per season
# ============================================================
print("=" * 70)
print("H1: Win Quota Analysis")
print("=" * 70)

c.execute("""
    SELECT season, home, away, outcome FROM matches
    WHERE outcome IS NOT NULL AND outcome != ''
""")
rows = c.fetchall()

# Count wins per team per season
team_season_wins = defaultdict(lambda: defaultdict(int))
team_season_matches = defaultdict(lambda: defaultdict(int))

for row in rows:
    season = row['season']
    for team_col in ('home', 'away'):
        team = norm_team(row[team_col])
        outcome = outcome_map(row['outcome'])
        if outcome is None:
            continue
        is_home = (team_col == 'home')
        team_won = (outcome == 'HOME' and is_home) or (outcome == 'AWAY' and not is_home)
        team_season_matches[team][season] += 1
        if team_won:
            team_season_wins[team][season] += 1

# Compute avg wins per season per tier
tier_teams = {
    "Tier 1 (Man Blue, Liverpool, Man Red, Chelsea)": TIER_1,
    "Tier 2 (Ldn Guns, Tottenham, Aston Villa)": TIER_2,
    "Tier 3 (West Ham, Everton, Wolves, Brighton)": TIER_3,
    "Tier 4 (Newcastle, Leeds, C.Palace, Fulham, Bournemouth)": TIER_4,
}

h1_results = {}
for tier_name, teams in tier_teams.items():
    all_win_counts = []
    team_summaries = {}
    for team in sorted(teams):
        wins = list(team_season_wins.get(team, {}).values())
        if not wins:
            continue
        avg_wins = sum(wins) / len(wins)
        max_wins = max(wins)
        min_wins = min(wins)
        all_win_counts.extend(wins)
        team_summaries[team] = {
            "avg_wins": round(avg_wins, 2),
            "min_wins": min_wins,
            "max_wins": max_wins,
            "seasons": len(wins)
        }
    if all_win_counts:
        tier_avg = sum(all_win_counts) / len(all_win_counts)
        h1_results[tier_name] = {
            "avg_wins_per_team_per_season": round(tier_avg, 2),
            "teams": team_summaries
        }
        print(f"\n{tier_name}:")
        print(f"  Avg wins/season: {tier_avg:.2f}")
        for t, s in team_summaries.items():
            print(f"  {t}: avg={s['avg_wins']}, range={s['min_wins']}-{s['max_wins']} ({s['seasons']} seasons)")

results["H1"] = h1_results

# ============================================================
# H2: The Edges Are Real — Certain brackets beat the market
# ============================================================
print("\n" + "=" * 70)
print("H2: Edge Analysis by Odds Bracket")
print("=" * 70)

c.execute("""
    SELECT oh, od, oa, outcome FROM matches
    WHERE oh IS NOT NULL AND od IS NOT NULL AND oa IS NOT NULL
      AND outcome IS NOT NULL AND outcome != ''
""")
odds_rows = c.fetchall()

def vig_free_probs(oh, od, oa):
    """Remove vig to get fair probabilities."""
    imp_h = 1.0 / oh
    imp_d = 1.0 / od
    imp_a = 1.0 / oa
    total_imp = imp_h + imp_d + imp_a
    return imp_h / total_imp, imp_d / total_imp, imp_a / total_imp

brackets = {
    "Mod Dog (OH 4-5)": lambda r: 4 <= r['oh'] < 5,
    "Heavy Dog (OH >5)": lambda r: r['oh'] > 5,
    "Slight Dog (OH 3-4)": lambda r: 3 <= r['oh'] < 4,
}

for bracket_name, condition in brackets.items():
    matched = [r for r in odds_rows if condition(r)]
    if not matched:
        print(f"\n{bracket_name}: NO MATCHES")
        continue
    predictions = {"HOME": 0, "DRAW": 0, "AWAY": 0}
    actuals = {"HOME": 0, "DRAW": 0, "AWAY": 0}
    total = len(matched)
    for r in matched:
        outcome = outcome_map(r['outcome'])
        if outcome is None:
            continue
        actuals[outcome] += 1
        fp_h, fp_d, fp_a = vig_free_probs(r['oh'], r['od'], r['oa'])
        predictions["HOME"] += fp_h
        predictions["DRAW"] += fp_d
        predictions["AWAY"] += fp_a

    actual_rate = {k: v/total for k, v in actuals.items()}
    avg_pred_prob = {k: v/total for k, v in predictions.items()}

    print(f"\n{bracket_name} (n={total}):")
    for outcome in ["HOME", "DRAW", "AWAY"]:
        edge = actual_rate[outcome] - avg_pred_prob[outcome]
        sign = "+" if edge > 0 else ""
        print(f"  {outcome}: actual={actual_rate[outcome]:.4f}, market-implied={avg_pred_prob[outcome]:.4f}, edge={sign}{edge:.4f}")

results["H2"] = {}
for bracket_name, condition in brackets.items():
    matched = [r for r in odds_rows if condition(r)]
    if not matched:
        continue
    predictions = {"HOME": 0, "DRAW": 0, "AWAY": 0}
    actuals = {"HOME": 0, "DRAW": 0, "AWAY": 0}
    total = len(matched)
    for r in matched:
        outcome = outcome_map(r['outcome'])
        if outcome is None:
            continue
        actuals[outcome] += 1
        fp_h, fp_d, fp_a = vig_free_probs(r['oh'], r['od'], r['oa'])
        predictions["HOME"] += fp_h
        predictions["DRAW"] += fp_d
        predictions["AWAY"] += fp_a
    actual_rate = {k: v/total for k, v in actuals.items()}
    avg_pred_prob = {k: v/total for k, v in predictions.items()}
    results["H2"][bracket_name] = {
        "n": total,
        "actual_rate": {k: round(v, 4) for k, v in actual_rate.items()},
        "market_implied": {k: round(v, 4) for k, v in avg_pred_prob.items()},
        "edge": {k: round(actual_rate[k] - avg_pred_prob[k], 4) for k in actual_rate}
    }

# Also compute the AWAY edge for Mod Dog and DRAW edge for Heavy Dog more precisely
# Let me also break down by bracket more carefully:
print("\n\nDETAILED BRACKET BREAKDOWN:")

# Re-run with more specific brackets
detailed_brackets = {
    "OH 4-5 → AWAY": lambda r: 4 <= r['oh'] < 5,
    "OH >5 → DRAW": lambda r: r['oh'] > 5,
    "OH 3-4 → HOME": lambda r: 3 <= r['oh'] < 4,
}

for desc, cond in detailed_brackets.items():
    matched = [r for r in odds_rows if cond(r)]
    total = len(matched)
    if total == 0:
        continue
    outcomes = [outcome_map(r['outcome']) for r in matched]
    outcomes = [o for o in outcomes if o]
    n = len(outcomes)
    target = desc.split("→")[1].strip()
    target_count = outcomes.count(target)
    target_rate = target_count / n if n > 0 else 0
    print(f"\n{desc}: {n}/{total} valid matches")
    print(f"  {target} rate: {target_rate:.4f} ({target_count}/{n})")

# ============================================================
# H3: Draw Predictions
# ============================================================
print("\n" + "=" * 70)
print("H3: Draw Prediction Analysis")
print("=" * 70)

c.execute("""
    SELECT oh, od, oa, outcome FROM matches
    WHERE oh IS NOT NULL AND oh > 0
    AND od IS NOT NULL AND od > 0
    AND oa IS NOT NULL AND oa > 0
    AND outcome IS NOT NULL AND outcome != ''
""")
draw_rows = c.fetchall()
total_draw = len(draw_rows)

# What was predicted for draws?
draw_predictions = 0
draw_actuals = 0
draw_implied = 0
for r in draw_rows:
    outcome = outcome_map(r['outcome'])
    fp_h, fp_d, fp_a = vig_free_probs(r['oh'], r['od'], r['oa'])
    draw_implied += fp_d
    if outcome == 'DRAW':
        draw_actuals += 1

actual_draw_rate = draw_actuals / total_draw
avg_implied_draw = draw_implied / total_draw

print(f"\nTotal draw-eligible matches: {total_draw}")
print(f"Actual draw rate: {actual_draw_rate:.4f} ({draw_actuals}/{total_draw})")
print(f"Avg market-implied draw prob: {avg_implied_draw:.4f}")
print(f"Market edge on draws: {actual_draw_rate - avg_implied_draw:+.4f}")

# When do draws actually beat the market?
# Group by odds brackets
draw_brackets = [
    ("OD < 3.0", lambda r: r['od'] < 3.0),
    ("OD 3.0-3.5", lambda r: 3.0 <= r['od'] < 3.5),
    ("OD 3.5-4.0", lambda r: 3.5 <= r['od'] < 4.0),
    ("OD 4.0-5.0", lambda r: 4.0 <= r['od'] < 5.0),
    ("OD 5.0-7.0", lambda r: 5.0 <= r['od'] < 7.0),
    ("OD > 7.0", lambda r: r['od'] >= 7.0),
]

print("\nDraw performance by draw odds bracket:")
for bracket_name, condition in draw_brackets:
    matched = [r for r in draw_rows if condition(r)]
    if not matched:
        continue
    m = len(matched)
    actuals = sum(1 for r in matched if outcome_map(r['outcome']) == 'DRAW')
    implied = sum(vig_free_probs(r['oh'], r['od'], r['oa'])[1] for r in matched)
    a_rate = actuals / m
    i_rate = implied / m
    edge = a_rate - i_rate
    print(f"  {bracket_name} (n={m}): actual={a_rate:.4f}, implied={i_rate:.4f}, edge={edge:+.4f}")

results["H3"] = {
    "total_matches": total_draw,
    "actual_draw_rate": round(actual_draw_rate, 4),
    "avg_market_implied_draw": round(avg_implied_draw, 4),
    "market_edge_on_draw": round(actual_draw_rate - avg_implied_draw, 4)
}

# ============================================================
# H4: Simple Confidence Threshold
# ============================================================
print("\n" + "=" * 70)
print("H4: Confidence Threshold Analysis")
print("=" * 70)

# For each match, determine which outcome had highest implied prob
# Test various thresholds
c.execute("""
    SELECT oh, od, oa, outcome FROM matches
    WHERE oh IS NOT NULL AND outcome IS NOT NULL AND outcome != ''
    AND od IS NOT NULL AND oa IS NOT NULL
""")
conf_rows = c.fetchall()

thresholds = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]
for threshold in thresholds:
    bets = 0
    correct = 0
    for r in conf_rows:
        oh, od, oa = r['oh'], r['od'], r['oa']
        fp_h, fp_d, fp_a = vig_free_probs(oh, od, oa)
        max_prob = max(fp_h, fp_d, fp_a)
        if max_prob < threshold:
            continue
        bets += 1
        pred_idx = [fp_h, fp_d, fp_a].index(max_prob)
        outcomes = ['HOME', 'DRAW', 'AWAY']
        pred_outcome = outcomes[pred_idx]
        actual = outcome_map(r['outcome'])
        if pred_outcome == actual:
            correct += 1
    acc = correct / bets if bets > 0 else 0
    print(f"  Threshold >= {threshold:.0%}: bets={bets}, correct={correct}, accuracy={acc:.4f}")

# ROI calculation: assume 1 unit bet per pick at decimal odds
print("\n\nROI by threshold (1 unit bet, decimal odds):")
for threshold in [0.6, 0.65, 0.7, 0.75]:
    total_stake = 0
    total_return = 0
    for r in conf_rows:
        oh, od, oa = r['oh'], r['od'], r['oa']
        fp_h, fp_d, fp_a = vig_free_probs(oh, od, oa)
        max_prob = max(fp_h, fp_d, fp_a)
        if max_prob < threshold:
            continue
        pred_idx = [fp_h, fp_d, fp_a].index(max_prob)
        outcomes = ['HOME', 'DRAW', 'AWAY']
        pred_outcome = outcomes[pred_idx]
        actual = outcome_map(r['outcome'])
        odds = [oh, od, oa][pred_idx]
        total_stake += 1
        if pred_outcome == actual:
            total_return += odds
    if total_stake > 0:
        roi = (total_return - total_stake) / total_stake * 100
        print(f"  Threshold >= {threshold:.0%}: bets={int(total_stake)}, stake={total_stake:.0f}u, return={total_return:.2f}u, ROI={roi:+.2f}%")

results["H4"] = {}

# ============================================================
# H5: Team Performance Correlation — Prior Season Predictability
# ============================================================
print("\n" + "=" * 70)
print("H5: Season-to-Season Team Performance Correlation")
print("=" * 70)

c.execute("""
    SELECT season, home, away, outcome FROM matches
    WHERE outcome IS NOT NULL AND outcome != ''
""")
perf_rows = c.fetchall()

# Compute win% per team per season
team_season_pct = defaultdict(dict)
team_season_games = defaultdict(lambda: defaultdict(int))
team_season_wins_count = defaultdict(lambda: defaultdict(int))

for row in perf_rows:
    season = row['season']
    for team_col in ('home', 'away'):
        team = norm_team(row[team_col])
        outcome = outcome_map(row['outcome'])
        if outcome is None:
            continue
        is_home = (team_col == 'home')
        team_won = (outcome == 'HOME' and is_home) or (outcome == 'AWAY' and not is_home)
        team_season_games[team][season] += 1
        if team_won:
            team_season_wins_count[team][season] += 1

# Build sorted season lists per team
correlations = {}
for team in sorted(team_season_games.keys()):
    seasons = sorted(team_season_games[team].keys())
    if len(seasons) < 2:
        continue
    pairs = []
    for i in range(len(seasons) - 1):
        s1 = seasons[i]
        s2 = seasons[i+1]
        if s1 in team_season_wins_count[team] and s2 in team_season_wins_count[team]:
            g1 = team_season_games[team][s1]
            g2 = team_season_games[team][s2]
            if g1 > 0 and g2 > 0:
                pct1 = team_season_wins_count[team][s1] / g1 * 100
                pct2 = team_season_wins_count[team][s2] / g2 * 100
                pairs.append((pct1, pct2))
    if len(pairs) < 2:
        correlations[team] = {"pairs": len(pairs), "correlation": "insufficient data"}
        continue
    # Pearson correlation
    n = len(pairs)
    sum_x = sum(p[0] for p in pairs)
    sum_y = sum(p[1] for p in pairs)
    sum_xy = sum(p[0] * p[1] for p in pairs)
    sum_x2 = sum(p[0]**2 for p in pairs)
    sum_y2 = sum(p[1]**2 for p in pairs)
    num = n * sum_xy - sum_x * sum_y
    den = ((n * sum_x2 - sum_x**2) * (n * sum_y2 - sum_y**2))**0.5
    r = num / den if den > 0 else 0
    correlations[team] = {
        "pairs": n,
        "r": round(r, 4),
        "avg_prev_win_pct": round(sum_x / n, 2),
        "avg_next_win_pct": round(sum_y / n, 2)
    }
    print(f"  {team:20s}: r={r:+.4f}, pairs={n}, prev_avg={sum_x/n:.2f}%, next_avg={sum_y/n:.2f}%")

# Compute mean reversion: for teams that overperform (> their tier avg),
# do they regress?
print("\n\nMean Reversion Check:")
tiert_map = {}
for team in TIER_1: tiert_map[team] = "Tier 1"
for team in TIER_2: tiert_map[team] = "Tier 2"
for team in TIER_3: tiert_map[team] = "Tier 3"
for team in TIER_4: tiert_map[team] = "Tier 4"

tier_avg_wins = {}
for team in TIER_1:
    wins = list(team_season_wins.get(team, {}).values())
    if wins:
        tier_avg_wins.setdefault("Tier 1", []).extend(wins)
for team in TIER_2:
    wins = list(team_season_wins.get(team, {}).values())
    if wins:
        tier_avg_wins.setdefault("Tier 2", []).extend(wins)
for team in TIER_3:
    wins = list(team_season_wins.get(team, {}).values())
    if wins:
        tier_avg_wins.setdefault("Tier 3", []).extend(wins)
for team in TIER_4:
    wins = list(team_season_wins.get(team, {}).values())
    if wins:
        tier_avg_wins.setdefault("Tier 4", []).extend(wins)

tier_means = {k: round(sum(v)/len(v), 2) for k, v in tier_avg_wins.items()}
print(f"  Tier means: {tier_means}")

results["H5"] = {
    "correlations": correlations,
    "tier_mean_wins": tier_means
}

# ============================================================
# Summary stats for output
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

conn.close()

# Write results to JSON
with open("/home/faith/Documents/Projects/vfl-data/analysis/page-hypothesis.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nResults written to /home/faith/Documents/Projects/vfl-data/analysis/page-hypothesis.json")
