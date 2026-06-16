#!/usr/bin/env python3
"""
VFL Prediction-vs-Results Analytics Engine
Calculates hit rates per matchday, per fixture, per season,
identifying optimal betting matchdays.

Data Sources:
  - Results DB: vfl_results.db (table 'results')
  - Predictions JSON: predictions_latest.json, predictions-archive/*.json
  - Also scans for any *predict*.json across vfl-empire and vfl-complete-data
"""

import json
import os
import glob
import sqlite3
import re
import math
from collections import defaultdict
from datetime import datetime, timezone

# ── Configuration ──────────────────────────────────────────────────────────

WORKSPACE = "/home/ubuntu/faith-workspace"
RESULTS_DB = os.path.join(WORKSPACE, "vfl-complete-data", "databases", "vfl_results.db")
PREDICTIONS_LATEST = os.path.join(WORKSPACE, "vfl-complete-data", "signals", "predictions_latest.json")
PREDICTIONS_ARCHIVE_DIR = os.path.join(WORKSPACE, "vfl-complete-data", "predictions-archive")
VFL_EMPIRE_DIR = os.path.join(WORKSPACE, "vfl-empire")

OUTPUT_DIR = os.path.join(WORKSPACE, "vfl-data-archive", "analysis")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "prediction_analytics_report.json")

# Bayesian prior: assume global average hit rate for small samples
BAYESIAN_PRIOR_ALPHA = 50  # pseudo-observations
BAYESIAN_PRIOR_BETA = 20   # pseudo-failures (default 50/70 ≈ 71.4% prior)

# Minimum sample for non-Bayesian display
MIN_SAMPLE_RAW = 5


# ── Step 1: Load all prediction files ──────────────────────────────────────

def load_all_predictions():
    """
    Walk the entire directory tree under vfl-empire and vfl-complete-data,
    loading any prediction JSON files.
    Returns a list of normalized prediction dicts.
    """
    all_predictions = []

    # 1. Primary: predictions_latest.json
    if os.path.exists(PREDICTIONS_LATEST):
        with open(PREDICTIONS_LATEST) as f:
            data = json.load(f)
        entries = extract_predictions_v1(data)
        for e in entries:
            e["source_file"] = "predictions_latest.json"
        all_predictions.extend(entries)
        print(f"  📄 predictions_latest.json: {len(entries)} predictions extracted")

    # 2. Archive files: predictions-archive/*.json
    if os.path.isdir(PREDICTIONS_ARCHIVE_DIR):
        archive_files = sorted(glob.glob(os.path.join(PREDICTIONS_ARCHIVE_DIR, "*.json")))
        archive_pred_count = 0
        for fpath in archive_files:
            fname = os.path.basename(fpath)
            try:
                with open(fpath) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                print(f"  ⚠️  Skipping {fname}: {e}")
                continue
            file_entries = extract_predictions_v2(data)
            for e in file_entries:
                e["source_file"] = fname
            all_predictions.extend(file_entries)
            archive_pred_count += len(file_entries)
        print(f"  📄 predictions-archive: {len(archive_files)} files scanned")
        print(f"  📊 archive predictions: {archive_pred_count} total")

    # 3. Scan other prediction files in vfl-empire
    extra_patterns = [
        os.path.join(VFL_EMPIRE_DIR, "results", "v3_bayesian_predictions.json"),
        os.path.join(VFL_EMPIRE_DIR, "results", "live-predictions.json"),
    ]
    for fpath in extra_patterns:
        if os.path.exists(fpath):
            fname = os.path.basename(fpath)
            try:
                with open(fpath) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                print(f"  ⚠️  Skipping {fname}: {e}")
                continue
            entries = extract_predictions_v3(fname, data)
            for e in entries:
                e["source_file"] = fname
            all_predictions.extend(entries)
            print(f"  📄 {fname}: {len(entries)} predictions extracted")

    print(f"\n  📊 TOTAL predictions loaded: {len(all_predictions)}")
    return all_predictions


def extract_predictions_v1(data):
    """
    Format: predictions_latest.json
    { "matchdays": [ { "season": "VFLM 5128", "matchday": 25,
        "fixtures": [ { "home": "...", "away": "...", "predictions": [
          { "market": "...", "odds": ..., "confidence": ..., "expected_value": ..., "strength": ... }
        ] } ] } ] }
    """
    entries = []
    for md in data.get("matchdays", []):
        season = md.get("season", "")
        matchday = md.get("matchday", 0)
        season_id = md.get("season_id", "")
        for fx in md.get("fixtures", []):
            home = fx.get("home", "")
            away = fx.get("away", "")
            event_id = fx.get("event_id", "")
            # predictions can be directly or nested
            preds_list = fx.get("predictions", [])
            if not preds_list and "prediction" in fx:
                preds_list = fx["prediction"].get("predictions", [])
            for p in preds_list:
                market = p.get("market", "")
                odds = p.get("odds", 0)
                # Handle both 'confidence' and 'confidence_pct'
                confidence = p.get("confidence", p.get("confidence_pct", 0))
                expected_value = p.get("expected_value", 0)
                strength = p.get("strength", "")
                entries.append({
                    "season": season,
                    "season_id": season_id,
                    "matchday": matchday,
                    "home": home,
                    "away": away,
                    "event_id": event_id,
                    "market": market,
                    "odds": odds,
                    "confidence": confidence,
                    "expected_value": expected_value,
                    "strength": strength,
                })
    return entries


def extract_predictions_v2(data):
    """
    Format: predictions-archive/*.json
    { "current_matchday": { "season": "...", "matchday": N },
      "matchdays": [ { "season_name": "...", "matchday": N,
        "fixtures": [ { "home": "...", "away": "...",
          "prediction": { "predictions": [ { "market": "...",
            "confidence_pct": ..., "odds": ..., "strength": ... } ] }
        } ] } ] }
    """
    entries = []
    for md in data.get("matchdays", []):
        season = md.get("season_name", "")
        matchday = md.get("matchday", 0)
        season_id = md.get("season_id", "")
        for fx in md.get("fixtures", []):
            home = fx.get("home", "")
            away = fx.get("away", "")
            event_id = fx.get("event_id", "")
            # Try direct predictions then nested
            preds_list = fx.get("predictions", [])
            if not preds_list and "prediction" in fx:
                preds_list = fx["prediction"].get("predictions", [])
            for p in preds_list:
                market = p.get("market", "")
                odds = p.get("odds", 0)
                confidence = p.get("confidence", p.get("confidence_pct", 0))
                expected_value = p.get("expected_value", 0)
                strength = p.get("strength", "")
                entries.append({
                    "season": season,
                    "season_id": season_id,
                    "matchday": matchday,
                    "home": home,
                    "away": away,
                    "event_id": event_id,
                    "market": market,
                    "odds": odds,
                    "confidence": confidence,
                    "expected_value": expected_value,
                    "strength": strength,
                })
    return entries


def extract_predictions_v3(source_name, data):
    """
    Format: v3_bayesian_predictions.json
    { "matches": [ { "md": 27, "home": "...", "away": "...", "bet": "AWAY", "odds": ... } ] }

    Format: live-predictions.json
    { "season": "...", "match_day": N, "bets": [ { "home": "...", "away": "...", "pick": "HOME", ... } ] }
    """
    entries = []
    if source_name == "v3_bayesian_predictions.json":
        matches = data.get("matches", [])
        season = guess_season_from_source(source_name)
        for m in matches:
            md = m.get("md", 0)
            home = m.get("home", "")
            away = m.get("away", "")
            bet = m.get("bet", "")
            odds = m.get("odds", 0)
            # Map bet types to market names
            market_map = {
                "HOME": "Home Win",
                "AWAY": "Away Win",
                "DRAW": "Draw",
            }
            market = market_map.get(bet, bet)
            entries.append({
                "season": season,
                "season_id": "",
                "matchday": md,
                "home": home,
                "away": away,
                "event_id": "",
                "market": market,
                "odds": odds,
                "confidence": 0,
                "expected_value": 0,
                "strength": "",
            })
    elif source_name == "live-predictions.json":
        season = data.get("season", "")
        match_day = data.get("match_day", 0)
        for b in data.get("bets", []):
            home = b.get("home", "")
            away = b.get("away", "")
            pick = b.get("pick", "")
            odds = b.get("odds", 0)
            market_map = {
                "HOME": "Home Win",
                "AWAY": "Away Win",
                "DRAW": "Draw",
            }
            market = market_map.get(pick, pick)
            entries.append({
                "season": season,
                "season_id": "",
                "matchday": match_day,
                "home": home,
                "away": away,
                "event_id": "",
                "market": market,
                "odds": odds,
                "confidence": 0,
                "expected_value": 0,
                "strength": "",
            })
    return entries


def guess_season_from_source(source_name):
    """Try to extract season from filename, fallback to unknown."""
    m = re.search(r'VFLM[_\s](\d+)', source_name)
    if m:
        return f"VFLM {m.group(1)}"
    return "UNKNOWN"


# ── Step 2: Load all results from SQLite DB ────────────────────────────────

def load_all_results():
    """
    Load all results from the results DB.
    Returns a dict keyed by (season_name, match_day, home_team, away_team)
    and also a dict keyed by event_id.
    """
    if not os.path.exists(RESULTS_DB):
        print(f"  ❌ Results DB not found: {RESULTS_DB}")
        return {}, {}

    conn = sqlite3.connect(RESULTS_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM results")
    rows = cursor.fetchall()
    conn.close()

    by_key = {}
    by_event = {}
    for row in rows:
        r = dict(row)
        # Normalize team names: strip whitespace, title case
        home = r["home_team"].strip()
        away = r["away_team"].strip()
        # Create a normalized key
        key = (r["season_name"], r["match_day"], normalize_team(home), normalize_team(away))
        by_key[key] = r
        by_event[r["event_id"]] = r

    print(f"  🏆 Results loaded: {len(rows)} rows, {len(by_key)} unique keys")
    return by_key, by_event


# ── Step 3: Match predictions to results ───────────────────────────────────

def match_predictions_to_results(predictions, results_by_key, results_by_event):
    """
    Match each prediction to its corresponding result.
    Tries multiple strategies:
    1. By event_id
    2. By (season, matchday, home, away) with team name normalization
    """
    matched = []
    unmatched = []

    # Build lookup from event_id if available
    for pred in predictions:
        result = None

        # Strategy 1: Match by event_id
        if pred.get("event_id") and pred["event_id"] in results_by_event:
            result = results_by_event[pred["event_id"]]

        # Strategy 2: Match by (season, matchday, home, away)
        if result is None:
            norm_home = normalize_team(pred["home"])
            norm_away = normalize_team(pred["away"])
            key = (pred["season"], pred["matchday"], norm_home, norm_away)
            if key in results_by_key:
                result = results_by_key[key]
            else:
                # Try reverse (home/away swapped)
                key_rev = (pred["season"], pred["matchday"], norm_away, norm_home)
                if key_rev in results_by_key:
                    result = results_by_key[key_rev]

        if result is not None:
            matched.append((pred, result))
        else:
            unmatched.append(pred)

    return matched, unmatched


# ── Step 4: Determine HIT/MISS per market ──────────────────────────────────

def check_hit(prediction, result):
    """
    Determine if a prediction was a HIT or MISS based on the market type
    and the actual result data.

    Returns: (hit: bool, detail: str)
    """
    market = prediction["market"]
    total_goals = result.get("total_goals", 0)
    home_goals = result.get("home_goals", 0)
    away_goals = result.get("away_goals", 0)

    # ── Over / Under goals markets ──
    m = re.match(r'(Over|Under)\s+([\d.]+)\s*Goals?', market)
    if m:
        direction = m.group(1)
        threshold = float(m.group(2))
        if direction == "Over":
            hit = total_goals > threshold
            # For Over X.5 Goals: hit if total_goals > X.5 (i.e., total_goals >= X+1)
            # For Over 1.5: hit if total_goals >= 2
            # But actually the math is correct: total_goals > 1.5 means total_goals >= 2
            detail = f"{home_goals}-{away_goals} (total={total_goals}) vs {market}: {'✅ HIT' if hit else '❌ MISS'}"
            return hit, detail
        elif direction == "Under":
            hit = total_goals < threshold
            detail = f"{home_goals}-{away_goals} (total={total_goals}) vs {market}: {'✅ HIT' if hit else '❌ MISS'}"
            return hit, detail

    # ── Home Win / Away Win / Draw ──
    if market == "Home Win":
        hit = home_goals > away_goals
        detail = f"{home_goals}-{away_goals}: {'✅ HIT' if hit else '❌ MISS'}"
        return hit, detail
    elif market == "Away Win":
        hit = away_goals > home_goals
        detail = f"{home_goals}-{away_goals}: {'✅ HIT' if hit else '❌ MISS'}"
        return hit, detail
    elif market == "Draw":
        hit = home_goals == away_goals
        detail = f"{home_goals}-{away_goals}: {'✅ HIT' if hit else '❌ MISS'}"
        return hit, detail

    # ── Both Teams to Score / GG / NG ──
    if market in ("GG", "Both Teams to Score", "Both Teams Score"):
        hit = home_goals > 0 and away_goals > 0
        detail = f"{home_goals}-{away_goals}: {'✅ HIT' if hit else '❌ MISS'}"
        return hit, detail
    if market in ("NG", "No Goal", "Clean Sheet"):
        hit = home_goals == 0 or away_goals == 0
        detail = f"{home_goals}-{away_goals}: {'✅ HIT' if hit else '❌ MISS'}"
        return hit, detail

    # Unknown market - can't evaluate
    return None, f"Unknown market: {market}"


# ── Step 5-7: Calculate hit rates with Bayesian adjustment ─────────────────

def bayesian_adjusted_rate(hits, total, prior_alpha=BAYESIAN_PRIOR_ALPHA, prior_beta=BAYESIAN_PRIOR_BETA):
    """Apply Bayesian adjustment using a beta prior."""
    if total == 0:
        return prior_alpha / (prior_alpha + prior_beta), 0, prior_alpha + prior_beta
    adj_hits = hits + prior_alpha
    adj_total = total + prior_alpha + prior_beta
    rate = adj_hits / adj_total
    return rate, adj_hits, adj_total


def compute_hit_rates(matched_predictions):
    """
    Compute hit rates across multiple dimensions:
    - Per matchday number (MD1-MD38) across all seasons
    - Per season
    - Per fixture pair (home vs away team combination)
    - Per team
    - Per market type
    - Per confidence/strength level
    """
    # Raw counters
    md_stats = defaultdict(lambda: {"hits": 0, "total": 0})
    season_stats = defaultdict(lambda: {"hits": 0, "total": 0})
    fixture_stats = defaultdict(lambda: {"hits": 0, "total": 0})
    team_stats = defaultdict(lambda: {"hits": 0, "total": 0})
    market_stats = defaultdict(lambda: {"hits": 0, "total": 0})
    strength_stats = defaultdict(lambda: {"hits": 0, "total": 0})
    season_md_stats = defaultdict(lambda: {"hits": 0, "total": 0})

    detailed_results = []

    for pred, result in matched_predictions:
        hit, detail = check_hit(pred, result)
        if hit is None:
            continue  # Unknown market

        matchday = pred["matchday"]
        season = pred["season"]
        home = pred["home"]
        away = pred["away"]
        market = pred["market"]
        strength = pred.get("strength", "UNKNOWN")
        confidence = pred.get("confidence", 0)
        expected_value = pred.get("expected_value", 0)
        odds = pred.get("odds", 0)
        total_goals = result.get("total_goals", 0)

        # Aggregate
        md_stats[matchday]["total"] += 1
        md_stats[matchday]["hits"] += (1 if hit else 0)

        season_stats[season]["total"] += 1
        season_stats[season]["hits"] += (1 if hit else 0)

        fixture_key = f"{normalize_team(home)} vs {normalize_team(away)}"
        fixture_stats[fixture_key]["total"] += 1
        fixture_stats[fixture_key]["hits"] += (1 if hit else 0)

        for team in [normalize_team(home), normalize_team(away)]:
            team_stats[team]["total"] += 1
            team_stats[team]["hits"] += (1 if hit else 0)

        market_stats[market]["total"] += 1
        market_stats[market]["hits"] += (1 if hit else 0)

        if strength:
            strength_stats[strength]["total"] += 1
            strength_stats[strength]["hits"] += (1 if hit else 0)

        season_md_key = f"{season}_MD{matchday}"
        season_md_stats[season_md_key]["total"] += 1
        season_md_stats[season_md_key]["hits"] += (1 if hit else 0)

        detailed_results.append({
            "season": season,
            "matchday": matchday,
            "home": home,
            "away": away,
            "market": market,
            "odds": odds,
            "confidence": confidence,
            "strength": strength,
            "expected_value": expected_value,
            "home_goals": result.get("home_goals"),
            "away_goals": result.get("away_goals"),
            "total_goals": total_goals,
            "hit": hit,
            "detail": detail,
        })

    # Build report dicts with Bayesian adjustment
    def format_stats(stats_dict, label="unknown"):
        results = []
        for key, val in sorted(stats_dict.items(), key=lambda x: x[1]["total"], reverse=True):
            hits = val["hits"]
            total = val["total"]
            raw_rate = hits / total if total > 0 else 0
            bayes_rate, bayes_hits, bayes_total = bayesian_adjusted_rate(hits, total)
            results.append({
                "key": str(key),
                "hits": hits,
                "total": total,
                "raw_hit_rate": round(raw_rate, 4),
                "bayesian_adjusted_rate": round(bayes_rate, 4),
                "bayesian_pseudo_hits": bayes_hits,
                "bayesian_pseudo_total": bayes_total,
                "label": label,
            })
        return results

    return {
        "per_matchday": format_stats(md_stats, "matchday_number"),
        "per_season": format_stats(season_stats, "season"),
        "per_fixture": format_stats(fixture_stats, "fixture_pair"),
        "per_team": format_stats(team_stats, "team"),
        "per_market": format_stats(market_stats, "market"),
        "per_strength": format_stats(strength_stats, "strength"),
        "per_season_matchday": format_stats(season_md_stats, "season_matchday"),
        "detailed_results": detailed_results,
    }


def normalize_team(name):
    """Normalize team name for consistent matching and grouping."""
    name = name.strip().upper()
    replacements = {
        "MANCHESTER RED": "MANCHESTER RED",
        "MANCHESTER BLUE": "MANCHESTER BLUE",
        "LONDON GUNS": "LONDON GUNS",
        "MANCHESTER UNITED": "MANCHESTER RED",
        "MANCHESTER CITY": "MANCHESTER BLUE",
        "ARSENAL": "LONDON GUNS",
        "TOTTENHAM HOTSPUR": "TOTTENHAM",
        "SPURS": "TOTTENHAM",
        "WOLVES": "WOLVERHAMPTON",
        "LEICESTER": "LEICESTER CITY",
        "WEST BROM": "WEST BROMWICH",
    }
    if name in replacements:
        return replacements[name]
    return name


# ── Step 8: Identify optimal matchday range ────────────────────────────────

def find_optimal_matchday_range(md_stats_list, min_games=10, window_size=3):
    """
    Find the best matchday range (sliding window) for highest Bayesian-adjusted hit rate.
    Also find individual best matchdays.
    """
    # Build sorted list by matchday number
    md_by_number = {}
    for entry in md_stats_list:
        try:
            md_num = int(entry["key"])
            md_by_number[md_num] = entry
        except ValueError:
            continue

    if not md_by_number:
        return {}, []

    # Individual best
    sorted_mds = sorted(md_by_number.items())
    best_individual = sorted(
        [v for v in md_by_number.values() if v["total"] >= MIN_SAMPLE_RAW],
        key=lambda x: x["bayesian_adjusted_rate"],
        reverse=True
    )[:10]

    # Sliding window optimization
    windows = []
    md_numbers = [k for k, v in sorted_mds]
    for i in range(len(md_numbers)):
        for j in range(i + window_size - 1, min(i + window_size + 5, len(md_numbers))):
            if j >= len(md_numbers):
                break
            window_mds = md_numbers[i:j+1]
            total_hits = sum(md_by_number[md]["hits"] for md in window_mds)
            total_games = sum(md_by_number[md]["total"] for md in window_mds)
            if total_games < min_games:
                continue
            bayes_rate, _, _ = bayesian_adjusted_rate(total_hits, total_games)
            windows.append({
                "start_md": window_mds[0],
                "end_md": window_mds[-1],
                "range_label": f"MD{window_mds[0]}-MD{window_mds[-1]}",
                "total_hits": total_hits,
                "total_games": total_games,
                "raw_rate": round(total_hits / total_games, 4),
                "bayesian_adjusted_rate": round(bayes_rate, 4),
                "num_matchdays": len(window_mds),
            })

    # Also try full-half windows: first 19, last 19, quarters
    if len(md_numbers) >= 38:
        for label, start, end in [
            ("Early Season (MD1-MD10)", 1, 10),
            ("Mid Season (MD11-MD20)", 11, 20),
            ("Late Season (MD21-MD30)", 21, 30),
            ("Final Stretch (MD31-MD38)", 31, 38),
            ("First Half (MD1-MD19)", 1, 19),
            ("Second Half (MD20-MD38)", 20, 38),
            ("First Quarter (MD1-MD10)", 1, 10),
            ("Second Quarter (MD11-MD19)", 11, 19),
            ("Third Quarter (MD20-MD28)", 20, 28),
            ("Fourth Quarter (MD29-MD38)", 29, 38),
        ]:
            window_mds = [md for md in md_numbers if start <= md <= end]
            if not window_mds:
                continue
            total_hits = sum(md_by_number[md]["hits"] for md in window_mds)
            total_games = sum(md_by_number[md]["total"] for md in window_mds)
            if total_games < min_games:
                continue
            bayes_rate, _, _ = bayesian_adjusted_rate(total_hits, total_games)
            windows.append({
                "start_md": start,
                "end_md": end,
                "range_label": label,
                "total_hits": total_hits,
                "total_games": total_games,
                "raw_rate": round(total_hits / total_games, 4),
                "bayesian_adjusted_rate": round(bayes_rate, 4),
                "num_matchdays": len(window_mds),
            })

    best_windows = sorted(windows, key=lambda x: x["bayesian_adjusted_rate"], reverse=True)[:15]

    return {
        "best_individual_matchdays": best_individual,
        "best_windows": best_windows,
        "total_matchdays_with_data": len(md_by_number),
        "matchday_range": f"{min(md_numbers)}-{max(md_numbers)}" if md_numbers else "N/A",
    }


# ── Step 9: Save report ────────────────────────────────────────────────────

def save_report(report):
    """Save the full report to the output path."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  💾 Report saved to: {OUTPUT_PATH}")
    return OUTPUT_PATH


# ── Step 10: Print beautiful summary ───────────────────────────────────────

def print_summary(report):
    """Print a beautiful color-coded summary with emojis."""
    meta = report["report_metadata"]
    hits = meta["total_matched"]
    total = hits + meta["total_unmatched"]
    matched = meta["total_matched"]
    unmatched = meta["total_unmatched"]
    evaluated = meta["total_evaluated"]
    unevaluated = meta["total_unevaluated"]

    print("\n" + "═" * 70)
    print("  🏟️  VFL PREDICTION ANALYTICS ENGINE — FINAL REPORT")
    print("═" * 70)

    print(f"\n  📊 DATA OVERVIEW")
    print(f"  ───────────────────────────────────────────────────")
    print(f"  📥 Predictions loaded:   {meta['total_predictions_loaded']}")
    print(f"  🏆 Results in DB:        {meta['total_results_in_db']}")
    print(f"  🔗 Matched to results:   {matched}")
    print(f"  ❌ Unmatched:            {unmatched}")
    print(f"  ✅ Evaluated (hit/miss): {evaluated}")
    print(f"  ❓ Unevaluated (unknown): {unevaluated}")

    # Per-market summary
    print(f"\n  🎯 HIT RATES BY MARKET TYPE")
    print(f"  ───────────────────────────────────────────────────")
    for m in report["hit_rates"]["per_market"]:
        bar = "█" * int(m["bayesian_adjusted_rate"] * 30)
        print(f"  {m['key']:25s}  {m['bayesian_adjusted_rate']*100:5.1f}%  [{bar:<30s}]  ({m['hits']}/{m['total']})")

    # Per-strength summary
    print(f"\n  💪 HIT RATES BY STRENGTH LEVEL")
    print(f"  ───────────────────────────────────────────────────")
    for s in report["hit_rates"]["per_strength"]:
        bar = "█" * int(s["bayesian_adjusted_rate"] * 30)
        print(f"  {s['key']:15s}  {s['bayesian_adjusted_rate']*100:5.1f}%  [{bar:<30s}]  ({s['hits']}/{s['total']})")

    # Best matchdays
    print(f"\n  🏆 TOP 10 MATCHDAYS (Bayesian adjusted)")
    print(f"  ───────────────────────────────────────────────────")
    for i, md in enumerate(report["optimal"]["best_individual_matchdays"][:10], 1):
        bar = "█" * int(md["bayesian_adjusted_rate"] * 30)
        print(f"  #{i:2d}  MD{int(md['key']):2d}  {md['bayesian_adjusted_rate']*100:5.1f}%  [{bar:<30s}]  ({md['hits']}/{md['total']})")

    # Optimal windows
    print(f"\n  🔥 OPTIMAL MATCHDAY RANGES")
    print(f"  ───────────────────────────────────────────────────")
    for i, w in enumerate(report["optimal"]["best_windows"][:10], 1):
        bar = "█" * int(w["bayesian_adjusted_rate"] * 30)
        print(f"  #{i:2d}  {w['range_label']:30s}  {w['bayesian_adjusted_rate']*100:5.1f}%  [{bar:<30s}]  ({w['total_hits']}/{w['total_games']})")

    # Top teams
    print(f"\n  🏅 TOP 10 TEAMS (highest hit rate when involved)")
    print(f"  ───────────────────────────────────────────────────")
    teams_sorted = sorted(
        [t for t in report["hit_rates"]["per_team"] if t["total"] >= MIN_SAMPLE_RAW],
        key=lambda x: x["bayesian_adjusted_rate"],
        reverse=True
    )[:10]
    for i, t in enumerate(teams_sorted, 1):
        bar = "█" * int(t["bayesian_adjusted_rate"] * 30)
        print(f"  #{i:2d}  {t['key']:25s}  {t['bayesian_adjusted_rate']*100:5.1f}%  [{bar:<30s}]  ({t['hits']}/{t['total']})")

    # Per season summary
    print(f"\n  📅 SEASON-BY-SEASON HIT RATES")
    print(f"  ───────────────────────────────────────────────────")
    seasons_sorted = sorted(
        report["hit_rates"]["per_season"],
        key=lambda x: x["bayesian_adjusted_rate"],
        reverse=True
    )[:20]
    for s in seasons_sorted:
        bar = "█" * int(s["bayesian_adjusted_rate"] * 30)
        print(f"  {s['key']:15s}  {s['bayesian_adjusted_rate']*100:5.1f}%  [{bar:<30s}]  ({s['hits']}/{s['total']})")

    # Best fixtures
    print(f"\n  ⚔️  TOP 10 FIXTURES (highest hit rate)")
    print(f"  ───────────────────────────────────────────────────")
    fixtures_sorted = sorted(
        [f for f in report["hit_rates"]["per_fixture"] if f["total"] >= MIN_SAMPLE_RAW],
        key=lambda x: x["bayesian_adjusted_rate"],
        reverse=True
    )[:10]
    for i, f in enumerate(fixtures_sorted, 1):
        bar = "█" * int(f["bayesian_adjusted_rate"] * 30)
        print(f"  #{i:2d}  {f['key']:35s}  {f['bayesian_adjusted_rate']*100:5.1f}%  [{bar:<30s}]  ({f['hits']}/{f['total']})")

    print("\n" + "═" * 70)
    print("  ✅ ANALYSIS COMPLETE")
    print("═" * 70 + "\n")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("═" * 70)
    print("  🏟️  VFL PREDICTION VS RESULTS ANALYTICS ENGINE")
    print("═" * 70)
    print()

    # Step 1: Load all prediction files
    print("  📥 Step 1: Loading predictions...")
    predictions = load_all_predictions()

    # Step 2: Load all results
    print("\n  🏆 Step 2: Loading results from DB...")
    results_by_key, results_by_event = load_all_results()

    if not predictions:
        print("  ❌ No predictions loaded. Exiting.")
        return

    if not results_by_key:
        print("  ❌ No results loaded. Exiting.")
        return

    # Step 3: Match predictions to results
    print("\n  🔗 Step 3: Matching predictions to results...")
    matched, unmatched = match_predictions_to_results(predictions, results_by_key, results_by_event)
    print(f"  ✅ Matched: {len(matched)} predictions")
    print(f"  ❌ Unmatched: {len(unmatched)} predictions")

    # Step 4-5: Evaluate and compute hit rates
    print("\n  📊 Step 4-5: Evaluating hits and computing rates...")
    hit_rates = compute_hit_rates(matched)

    # Count evaluated vs unevaluated
    evaluated = len(hit_rates["detailed_results"])
    unevaluated = len(matched) - evaluated

    # Step 8: Find optimal matchday range
    print("  🎯 Step 8: Identifying optimal matchday ranges...")
    optimal = find_optimal_matchday_range(hit_rates["per_matchday"])

    # Build final report
    report = {
        "report_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline": "vfl_prediction_analytics.py",
            "data_sources": {
                "results_db": RESULTS_DB,
                "predictions_latest": PREDICTIONS_LATEST,
                "predictions_archive_dir": PREDICTIONS_ARCHIVE_DIR,
            },
            "total_predictions_loaded": len(predictions),
            "total_results_in_db": len(results_by_key),
            "total_matched": len(matched),
            "total_unmatched": len(unmatched),
            "total_evaluated": evaluated,
            "total_unevaluated": unevaluated,
        },
        "parameters": {
            "bayesian_prior_alpha": BAYESIAN_PRIOR_ALPHA,
            "bayesian_prior_beta": BAYESIAN_PRIOR_BETA,
            "min_sample_raw": MIN_SAMPLE_RAW,
        },
        "hit_rates": hit_rates,
        "optimal": optimal,
    }

    # Step 9: Save report
    print("\n  💾 Step 9: Saving report...")
    save_report(report)

    # Step 10: Print summary
    print("\n  📋 Step 10: Summary")
    print_summary(report)

    return report


if __name__ == "__main__":
    main()
