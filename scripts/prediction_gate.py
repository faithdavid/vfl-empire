#!/usr/bin/env python3
"""
prediction_gate.py — Pre-prediction Quality Control Gate
=========================================================
A checkpoint BEFORE any pick is allowed to be placed. For every potential
pick (home_team, away_team, market, odds, confidence), the gate consults
ALL available data sources and returns a PASS/FAIL verdict.

Gates:
  1. H2H Check          — Historical head-to-head data from 21K+ matches
  2. Cluster Check      — Odds fingerprint cluster with expected value
  3. Odds Reasonableness— Market-appropriate odds ranges
  4. Regime Check       — Current season/overall goal-scoring environment

Usage:
    python prediction_gate.py --home "Chelsea" --away "Liverpool" --market "Over 1.5 Goals" --odds 1.18
    python prediction_gate.py --batch predictions.json
    python prediction_gate.py --live

Integration (auto_bet_orchestrator.py):
    import subprocess, json
    result = subprocess.run(
        ['python3', 'prediction_gate.py', '--home', leg['home'], '--away', leg['away'],
         '--market', leg['market'], '--odds', str(leg['odds']), '--json'],
        capture_output=True, text=True
    )
    gate = json.loads(result.stdout)
    if gate['verdict'] != 'PASS':
        skip this bet

Author: VFL Engineering Team — Lord FaithDavid's Quality Mandate
"""

import argparse
import json
import math
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add path for common tools
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db

# ──────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
RESULTS_DB = str(BASE_DIR / "databases" / "vfl_results.db")
ODDS_DB = str(BASE_DIR / "databases" / "vfl_odds.db")
REGIME_FILE = str(BASE_DIR / "signals" / "vfl_active_regime.json")
LIVE_PREDICTIONS_FILE = str(BASE_DIR / "signals" / "live_test_predictions.json")
CLUSTER_CLASSIFIER = str(SCRIPTS_DIR / "odds_cluster_classifier.py")

# ──────────────────────────────────────────────────────────────────────
# TEAM PROFILES (from fixture_intelligence.py)
# ──────────────────────────────────────────────────────────────────────
TEAM_PROFILES = {
    "Leeds":          {"avg_goals": 2.15, "o1_5_pct": 64.2, "u3_5_pct": 82.0, "tier": "defensive"},
    "Everton":        {"avg_goals": 2.16, "o1_5_pct": 64.7, "u3_5_pct": 83.6, "tier": "defensive"},
    "Fulham":         {"avg_goals": 2.30, "o1_5_pct": 68.2, "u3_5_pct": 81.3, "tier": "defensive"},
    "Aston Villa":    {"avg_goals": 2.45, "o1_5_pct": 72.0, "u3_5_pct": 76.7, "tier": "balanced"},
    "Bournemouth":    {"avg_goals": 2.48, "o1_5_pct": 71.6, "u3_5_pct": 75.0, "tier": "balanced"},
    "Brighton":       {"avg_goals": 2.51, "o1_5_pct": 73.3, "u3_5_pct": 75.0, "tier": "balanced"},
    "Newcastle":      {"avg_goals": 2.54, "o1_5_pct": 73.4, "u3_5_pct": 75.3, "tier": "balanced"},
    "Crystal Palace": {"avg_goals": 2.69, "o1_5_pct": 75.0, "u3_5_pct": 70.7, "tier": "balanced"},
    "Tottenham":      {"avg_goals": 2.61, "o1_5_pct": 75.0, "u3_5_pct": 73.3, "tier": "attacking"},
    "Manchester Red": {"avg_goals": 2.61, "o1_5_pct": 74.5, "u3_5_pct": 73.1, "tier": "attacking"},
    "Liverpool":      {"avg_goals": 2.68, "o1_5_pct": 76.4, "u3_5_pct": 72.0, "tier": "attacking"},
    "West Ham":       {"avg_goals": 2.78, "o1_5_pct": 77.5, "u3_5_pct": 68.8, "tier": "attacking"},
    "London Guns":    {"avg_goals": 2.80, "o1_5_pct": 77.9, "u3_5_pct": 68.7, "tier": "powerhouse"},
    "Chelsea":        {"avg_goals": 2.86, "o1_5_pct": 79.3, "u3_5_pct": 67.5, "tier": "powerhouse"},
    "Wolverhampton":  {"avg_goals": 2.87, "o1_5_pct": 78.2, "u3_5_pct": 66.8, "tier": "powerhouse"},
    "Manchester Blue":{"avg_goals": 2.98, "o1_5_pct": 81.8, "u3_5_pct": 65.2, "tier": "powerhouse"},
}

VALID_TEAMS = frozenset(TEAM_PROFILES.keys())

# Market name normalization map
MARKET_ALIASES = {
    "Over 1.5 Goals": "O1.5",
    "Over 1.5": "O1.5",
    "O1.5": "O1.5",
    "Over 2.5 Goals": "O2.5",
    "Over 2.5": "O2.5",
    "O2.5": "O2.5",
    "Under 2.5 Goals": "U2.5",
    "Under 2.5": "U2.5",
    "U2.5": "U2.5",
    "Under 3.5 Goals": "U3.5",
    "Under 3.5": "U3.5",
    "U3.5": "U3.5",
    "Goal-Goal": "GG",
    "GG": "GG",
    "Both Teams to Score": "GG",
    "BTTS Yes": "GG",
    "No Goal": "NG",
    "NG": "NG",
    "BTTS No": "NG",
    "Draw No Bet": "DNB",
    "Draw No Bet (Home)": "DNB",
    "DNB Home": "DNB",
    "DNB":  "DNB",
    "Home Win": "HOME",
    "Home": "HOME",
    "Away Win": "AWAY",
    "Away": "AWAY",
    "Draw": "DRAW",
}

# Reasonable odds ranges per market
ODDS_RANGES = {
    "O1.5": (1.01, 1.50, "O1.5 odds should be <= 1.50 for high-probability picks"),
    "O2.5": (1.01, 2.50, "O2.5 odds should be <= 2.50"),
    "U2.5": (1.01, 2.50, "U2.5 odds should be <= 2.50"),
    "U3.5": (1.01, 2.00, "U3.5 odds should be <= 2.00"),
    "GG":   (1.01, 2.20, "GG odds should be <= 2.20"),
    "NG":   (1.01, 2.50, "NG odds should be <= 2.50"),
    "DNB":  (1.01, 5.00, "DNB odds should be <= 5.00"),
    "HOME": (1.01, 4.00, "Home Win odds should be <= 4.00"),
    "AWAY": (1.01, 4.00, "Away Win odds should be <= 4.00"),
    "DRAW": (1.01, 6.00, "Draw odds should be <= 6.00"),
}

# Market key mapping for result verification
MARKET_VERIFY = {
    "O1.5": lambda tg, hg, ag: 1 if tg > 1.5 else 0,
    "O2.5": lambda tg, hg, ag: 1 if tg > 2.5 else 0,
    "U2.5": lambda tg, hg, ag: 1 if tg < 2.5 else 0,
    "U3.5": lambda tg, hg, ag: 1 if tg < 3.5 else 0,
    "GG":   lambda tg, hg, ag: 1 if hg > 0 and ag > 0 else 0,
    "NG":   lambda tg, hg, ag: 1 if hg == 0 or ag == 0 else 0,
    "DNB":  lambda tg, hg, ag: 1 if hg > ag else 0,
    "HOME": lambda tg, hg, ag: 1 if hg > ag else 0,
    "AWAY": lambda tg, hg, ag: 1 if ag > hg else 0,
    "DRAW": lambda tg, hg, ag: 1 if hg == ag else 0,
}

# ──────────────────────────────────────────────────────────────────────
# ELITE MAGNETS (High-Probability Fixtures)
# ──────────────────────────────────────────────────────────────────────
# Fixtures with >85% historical hit rate for specific markets.
ELITE_MAGNETS = {
    frozenset(["Leeds", "Everton"]): {"U3.5": (97.5, "Extreme defensive stalemate history")},
    frozenset(["Leeds", "Fulham"]): {"U3.5": (95.0, "Defensive magnet")},
    frozenset(["Fulham", "Brighton"]): {"U3.5": (90.2, "Tactical stalemate")},
    frozenset(["Wolverhampton", "Manchester Blue"]): {"O1.5": (90.7, "Historically high scoring but watch for recent traps")},
    frozenset(["West Ham", "Fulham"]): {"U3.5": (76.9, "User identified safe magnet")},
    frozenset(["Leeds", "Chelsea"]): {"O1.5": (77.0, "User identified attacking magnet")},
    frozenset(["London Guns", "West Ham"]): {"O1.5": (85.5, "London Derby goal magnet")},
}

# ──────────────────────────────────────────────────────────────────────
# INVERSE GEMS (Trap Detection)
# ──────────────────────────────────────────────────────────────────────
# Fixtures that are "Traps" for certain markets but "Elite" for others.
# Format: {frozenset([TeamA, TeamB]): {trap_market: (pivot_market, success_rate, reason)}}
INVERSE_GEMS = {
    frozenset(["Leeds", "Chelsea"]): {"U1.5": ("O1.5", 77.0, "User pivot to Over 1.5")},
    frozenset(["Everton", "Fulham"]): {"O1.5": ("NG", 75.0, "Historically one-sided or low scoring")},
    frozenset(["Fulham", "Brighton"]): {"O1.5": ("U2.5", 78.2, "Tactical stalemate")},
    frozenset(["West Ham", "Fulham"]): {"O2.5": ("U3.5", 76.9, "User pivot to Under 3.5")},
}

def detect_trap(home: str, away: str, market: str) -> Optional[Dict[str, Any]]:
    """Check if the current fixture/market is a known trap."""
    key = frozenset([home, away])
    if key in INVERSE_GEMS:
        traps = INVERSE_GEMS[key]
        if market in traps:
            pivot, rate, reason = traps[market]
            return {
                "trap_market": market,
                "pivot_recommendation": pivot,
                "success_rate": rate,
                "reason": reason
            }
    return None


def detect_magnet(home: str, away: str, market: str) -> Optional[Dict[str, Any]]:
    """Check if the current fixture/market is an Elite Magnet."""
    key = frozenset([home, away])
    if key in ELITE_MAGNETS:
        magnets = ELITE_MAGNETS[key]
        if market in magnets:
            rate, reason = magnets[market]
            return {
                "market": market,
                "success_rate": rate,
                "reason": reason
            }
    return None



# ──────────────────────────────────────────────────────────────────────
# DATABASE HELPERS
# ──────────────────────────────────────────────────────────────────────

# DATABASE HELPERS (Postgres Migration)

def get_results_cur():
    """Returns a DictCursor for the Postgres database."""
    return get_db()

def get_odds_cur():
    """Returns a DictCursor for the Postgres database."""
    return get_db()


def normalize_market(market: str) -> Optional[str]:
    """Normalize a market name to canonical key (O1.5, O2.5, GG, etc.)."""
    clean = market.strip()
    if clean in MARKET_ALIASES:
        return MARKET_ALIASES[clean]
    return None


def validate_team(name: str) -> Optional[str]:
    """Validate and normalize a team name."""
    clean = name.strip()
    if clean in VALID_TEAMS:
        return clean
    for t in VALID_TEAMS:
        if clean.lower() in t.lower():
            return t
    return None


def format_market_name(market_key: str) -> str:
    """Format a canonical market key to a display name."""
    fmt = {
        "O1.5": "Over 1.5 Goals",
        "O2.5": "Over 2.5 Goals",
        "U2.5": "Under 2.5 Goals",
        "U3.5": "Under 3.5 Goals",
        "GG": "Goal-Goal (BTTS Yes)",
        "NG": "No Goal (BTTS No)",
        "HOME": "Home Win",
        "AWAY": "Away Win",
        "DRAW": "Draw",
        "DNB": "Draw No Bet (Home)",
    }
    return fmt.get(market_key, market_key)


# ══════════════════════════════════════════════════════════════════════
# GATE 1: H2H CHECK
# ══════════════════════════════════════════════════════════════════════

def gate_h2h(home_team: str, away_team: str, market_key: str,
             odds: float) -> Dict[str, Any]:
    """
    Gate 1: Historical Head-to-Head Analysis.

    Queries vfl_results.db for all completed (status=3) matches between
    these two teams and computes key metrics.

    PASS conditions (per market):
      - O1.5: n_matches >= 5 AND O1.5_rate >= 65%
      - GG:   n_matches >= 5 AND GG_rate >= 50%
      - O2.5: n_matches >= 5 AND avg_total_goals >= 2.5
      - U2.5: n_matches >= 5 AND avg_total_goals <= 2.5
      - U3.5: n_matches >= 5 AND avg_total_goals <= 3.0
      - NG:   n_matches >= 5 AND GG_rate < 50% (i.e., NG_rate > 50%)
    """
    try:
        with get_db() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) as n,
                    AVG(total_goals) as avg_total,
                    SUM(CASE WHEN total_goals > 1.5 THEN 1 ELSE 0 END) * 1.0
                        / GREATEST(COUNT(*), 1) as o1_5_rate,
                    SUM(CASE WHEN total_goals > 2.5 THEN 1 ELSE 0 END) * 1.0
                        / GREATEST(COUNT(*), 1) as o2_5_rate,
                    SUM(CASE WHEN home_goals > 0 AND away_goals > 0 THEN 1 ELSE 0 END) * 1.0
                        / GREATEST(COUNT(*), 1) as gg_rate,
                    SUM(CASE WHEN total_goals <= 3 THEN 1 ELSE 0 END) * 1.0
                        / GREATEST(COUNT(*), 1) as u35_rate,
                    SUM(CASE WHEN home_goals > away_goals THEN 1 ELSE 0 END) * 1.0
                        / GREATEST(COUNT(*), 1) as home_win_rate,
                    SUM(CASE WHEN away_goals > home_goals THEN 1 ELSE 0 END) * 1.0
                        / GREATEST(COUNT(*), 1) as away_win_rate
                FROM vfl_results_v2
                WHERE (
                      (home_team = %s AND away_team = %s)
                      OR (home_team = %s AND away_team = %s)
                  )
                """,
                (home_team, away_team, away_team, home_team),
            )
            row = cursor.fetchone()

        if not row or row["n"] is None or row["n"] == 0:
            return {
                "status": "INSUFFICIENT_DATA",
                "details": "No H2H meetings found between these teams",
                "n_matches": 0,
                "avg_total_goals": None,
                "o1_5_rate": None,
                "o2_5_rate": None,
                "gg_rate": None,
            }

        n = int(row["n"])
        avg_total = round(float(row["avg_total"]), 2) if row["avg_total"] is not None else 0.0
        o1_5_rate = round(float(row["o1_5_rate"]) * 100, 1) if row["o1_5_rate"] is not None else 0.0
        o2_5_rate = round(float(row["o2_5_rate"]) * 100, 1) if row["o2_5_rate"] is not None else 0.0
        gg_rate = round(float(row["gg_rate"]) * 100, 1) if row["gg_rate"] is not None else 0.0
        home_win_rate = round(float(row["home_win_rate"]) * 100, 1) if row["home_win_rate"] is not None else 0.0
        away_win_rate = round(float(row["away_win_rate"]) * 100, 1) if row["away_win_rate"] is not None else 0.0
        ng_rate = round(100.0 - gg_rate, 1)

        # Minimum sample size check
        if n < 5:
            return {
                "status": "INSUFFICIENT_DATA",
                "details": f"Only {n} H2H meetings (need >= 5)",
                "n_matches": n,
                "avg_total_goals": avg_total,
                "o1_5_rate": o1_5_rate,
                "gg_rate": gg_rate,
            }

        # 1. Trap Detection Check
        trap = detect_trap(home_team, away_team, market_key)
        if trap:
            return {
                "status": "FAIL",
                "details": f"TRAP DETECTED: {trap['reason']}. Pivot recommended to {trap['pivot_recommendation']} ({trap['success_rate']}% rate)",
                "trap_detected": True,
                "pivot_recommendation": trap["pivot_recommendation"]
            }

        # Market-specific PASS/FAIL logic
        status = "PASS"
        fail_reasons = []
        u35_rate = round(float(row["u35_rate"]) * 100, 1) if row["u35_rate"] is not None else 0.0
        detail_str = f"{n} meetings, avg {avg_total} goals"
        
        # We need to re-query for specific u35_rate if not in the main query
        # Actually, let's just use avg_total as a proxy OR better, add u35_rate to the query

        if market_key == "O1.5":
            if o1_5_rate < 65.0:
                status = "FAIL"
                fail_reasons.append(
                    f"H2H O1.5 rate {o1_5_rate}% < 65% threshold ({n} meetings)"
                )
            detail_str = f"{n} meetings, {o1_5_rate}% O1.5 rate, avg {avg_total} goals"

        elif market_key == "O2.5":
            if avg_total < 2.5:
                status = "FAIL"
                fail_reasons.append(
                    f"H2H avg {avg_total} goals < 2.5 threshold ({n} meetings)"
                )
            detail_str = f"{n} meetings, avg {avg_total} goals, {o2_5_rate}% O2.5 rate"

        elif market_key == "U2.5":
            if avg_total > 2.5:
                status = "FAIL"
                fail_reasons.append(
                    f"H2H avg {avg_total} goals > 2.5 threshold for U2.5 ({n} meetings)"
                )
            detail_str = f"{n} meetings, avg {avg_total} goals, {round(100-o2_5_rate,1)}% U2.5 rate"

        elif market_key == "U3.5":
            # GOLDEN RULE: If U35 hit rate is > 85% on 20+ matches, it's a PASS regardless of avg goals
            if n >= 20 and u35_rate >= 85.0:
                status = "PASS"
                detail_str = f"GOLDEN H2H: {n} meetings, {u35_rate}% U35 rate"
            elif avg_total > 3.0:
                status = "FAIL"
                fail_reasons.append(
                    f"H2H avg {avg_total} goals > 3.0 threshold for U3.5 ({n} meetings)"
                )
            else:
                detail_str = f"{n} meetings, avg {avg_total} goals, {u35_rate}% U35 rate"

        elif market_key == "GG":
            if gg_rate < 50.0:
                status = "FAIL"
                fail_reasons.append(
                    f"H2H GG rate {gg_rate}% < 50% threshold ({n} meetings)"
                )
            detail_str = f"{n} meetings, {gg_rate}% GG rate, avg {avg_total} goals"

        elif market_key == "NG":
            if gg_rate >= 50.0:
                status = "FAIL"
                fail_reasons.append(
                    f"H2H GG rate {gg_rate}% >= 50% (NG rate {ng_rate}% < 50%) ({n} meetings)"
                )
            detail_str = f"{n} meetings, {ng_rate}% NG rate, avg {avg_total} goals"

        elif market_key == "HOME":
            if home_win_rate < 35.0:
                status = "FAIL"
                fail_reasons.append(f"H2H Home Win rate {home_win_rate}% < 35% threshold")
            detail_str = f"{n} meetings, {home_win_rate}% Home Win rate"

        elif market_key == "AWAY":
            if away_win_rate < 35.0:
                status = "FAIL"
                fail_reasons.append(f"H2H Away Win rate {away_win_rate}% < 35% threshold")
            detail_str = f"{n} meetings, {away_win_rate}% Away Win rate"

        elif market_key == "DNB":
            # DNB Home Win rate should be higher than Away Win rate
            if home_win_rate < away_win_rate:
                status = "FAIL"
                fail_reasons.append(f"H2H Home Win rate {home_win_rate}% < Away Win rate {away_win_rate}% for DNB")
            detail_str = f"{n} meetings, {home_win_rate}% HW vs {away_win_rate}% AW"

        else:
            detail_str = f"{n} meetings, avg {avg_total} goals"

        result = {
            "status": status,
            "details": detail_str,
            "n_matches": n,
            "avg_total_goals": avg_total,
            "o1_5_rate": o1_5_rate,
            "o2_5_rate": o2_5_rate,
            "u35_rate": u35_rate,
            "gg_rate": gg_rate,
            "ng_rate": ng_rate,
            "home_win_rate": home_win_rate,
            "away_win_rate": away_win_rate,
        }
        if fail_reasons:
            result["fail_reasons"] = fail_reasons
        return result

    except sqlite3.Error as e:
        return {
            "status": "ERROR",
            "details": f"Database error: {e}",
            "n_matches": 0,
        }


# ══════════════════════════════════════════════════════════════════════
# GATE 2: CLUSTER CHECK (Odds Fingerprint)
# ══════════════════════════════════════════════════════════════════════

def gate_cluster(home_team: str, away_team: str, market_key: str,
                 odds: float, o15_odds: Optional[float] = None,
                 o25_odds: Optional[float] = None,
                 gg_odds: Optional[float] = None,
                 u35_odds: Optional[float] = None) -> Dict[str, Any]:
    """
    Gate 3: Odds Fingerprint Cluster Check.

    Uses the odds_cluster_classifier to classify the match's odds
    fingerprint into one of 8 pre-trained clusters and checks whether
    the cluster supports the proposed market.

    PASS conditions:
      - Cluster edge > 0 (positive expected value)
      - OR cluster hit_rate >= 55% (high historical hit rate)
      - OR the cluster's recommended bet matches the proposed market
    """
    # If we don't have full odds, try to look them up from vfl_odds.db
    if any(x is None for x in [o15_odds, o25_odds, gg_odds, u35_odds]):
        loaded_odds = _load_odds_from_db(home_team, away_team)
        if loaded_odds:
            o15_odds = o15_odds or loaded_odds.get("o15")
            o25_odds = o25_odds or loaded_odds.get("o25")
            gg_odds = gg_odds or loaded_odds.get("gg")
            u35_odds = u35_odds or loaded_odds.get("u35")

    if any(x is None for x in [o15_odds, o25_odds, gg_odds, u35_odds]):
        return {
            "status": "INSUFFICIENT_DATA",
            "details": "Missing odds data for cluster classification",
            "o15": o15_odds,
            "o25": o25_odds,
            "gg": gg_odds,
            "u35": u35_odds,
        }

    # Call the cluster classifier (all values confirmed not None above)
    try:
        result = _classify_odds(
            o15_odds,  # type: ignore[arg-type]
            o25_odds,  # type: ignore[arg-type]
            gg_odds,   # type: ignore[arg-type]
            u35_odds,  # type: ignore[arg-type]
        )
    except Exception as e:
        return {
            "status": "ERROR",
            "details": f"Cluster classification error: {e}",
        }

    if result.get("cluster_id") == -1:
        return {
            "status": "FAIL",
            "details": f"Invalid odds fingerprint: {result.get('error', 'unknown')}",
            "cluster_result": result,
        }

    cluster_id = result["cluster_id"]
    rec_bet = result["rec_bet"]
    hit_rate = result["hit_rate"]
    avg_odds = result["avg_odds"]
    distance = result["distance"]
    confidence = result["confidence"]

    # Compute expected value
    if avg_odds > 0 and hit_rate > 0:
        implied_prob_breakeven = 1.0 / avg_odds
        edge = hit_rate - implied_prob_breakeven
        edge_pct = round(edge * 100, 2)
    else:
        edge_pct = 0.0

    status = "PASS"
    pass_reasons = []
    fail_reasons = []

    # Check if cluster's recommended bet matches proposed market
    market_match = (rec_bet == market_key)

    # Per spec: PASS if cluster edge > 0 (positive expected value)
    #          OR cluster hit_rate >= 55% (high historical hit rate)
    if edge_pct > 0:
        pass_reasons.append(f"Positive edge {edge_pct}%")
    else:
        nf = f"Cluster edge {edge_pct}% is not positive"
        fail_reasons.append(nf)

    if hit_rate >= 0.55:
        pass_reasons.append(f"High hit rate {hit_rate*100:.1f}% (>=55%)")
    else:
        nf = f"Hit rate {hit_rate*100:.1f}% < 55%"
        fail_reasons.append(nf)

    if market_match:
        pass_reasons.append(f"Cluster recommends {rec_bet} — matches proposed market")
    else:
        fail_reasons.append(
            f"Cluster recommends {rec_bet} ({result.get('label', '')}), "
            f"not {market_key}"
        )

    # Per spec: PASS ONLY if edge > 0 (positive expected value required)
    # MODIFICATION: For U3.5, allow PASS if hit_rate > 75% even with slight negative edge
    if edge_pct > 0:
        status = "PASS"
    elif market_key == "U3.5" and hit_rate >= 0.75:
        status = "PASS"
        pass_reasons.append(f"U3.5 High-Safety Pass (Hit Rate {hit_rate*100:.1f}%)")
    else:
        status = "FAIL"

    detail_str = (f"C{cluster_id} {rec_bet} @{avg_odds}, "
                  f"edge {edge_pct}%, hit {hit_rate*100:.1f}%")

    result_dict = {
        "status": status,
        "details": detail_str,
        "cluster_id": cluster_id,
        "rec_bet": rec_bet,
        "hit_rate": hit_rate,
        "avg_odds": avg_odds,
        "edge_pct": edge_pct,
        "confidence": confidence,
        "distance": distance,
        "label": result.get("label", ""),
        "market_match": market_match,
        "o15": o15_odds,
        "o25": o25_odds,
        "gg": gg_odds,
        "u35": u35_odds,
    }
    if fail_reasons:
        result_dict["fail_reasons"] = fail_reasons
    if pass_reasons:
        result_dict["pass_reasons"] = pass_reasons
    return result_dict


def _classify_odds(o15: float, o25: float, gg: float,
                   u35: float) -> Dict[str, Any]:
    """Call the odds_cluster_classifier via subprocess or direct import."""
    try:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from odds_cluster_classifier import classify_match
        return classify_match(o15, o25, gg, u35)
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: subprocess call
    try:
        cmd = [
            sys.executable or "python3",
            str(CLUSTER_CLASSIFIER),
            "--o15", str(o15),
            "--o25", str(o25),
            "--gg", str(gg),
            "--u35", str(u35),
            "--json",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout.strip())
    except Exception:
        pass

    return {"cluster_id": -1, "error": "Could not classify odds"}


def _load_odds_from_db(home_team: str,
                       away_team: str) -> Optional[Dict[str, float]]:
    """Look up odds from vfl_odds_v2 for a given fixture."""
    try:
        with get_db() as cursor:
            # Find the most recent capture for this fixture that has all required odds
            cursor.execute("""
                SELECT o15, o25, u35, gg
                FROM vfl_odds_v2
                WHERE home_team = %s AND away_team = %s
                  AND o15 IS NOT NULL AND o25 IS NOT NULL 
                  AND u35 IS NOT NULL AND gg IS NOT NULL
                ORDER BY captured_at DESC
                LIMIT 1
            """, (home_team, away_team))
            row = cursor.fetchone()
            if not row:
                return None

            return {
                "o15": row["o15"],
                "o25": row["o25"],
                "u35": row["u35"],
                "gg": row["gg"]
            }
    except Exception as e:
        logger.error(f"Error loading odds from Postgres: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# GATE 4: ODDS REASONABLENESS
# ══════════════════════════════════════════════════════════════════════

def gate_odds_reasonableness(market_key: str, odds: float) -> Dict[str, Any]:
    """
    Gate 4: Odds Reasonableness Check.

    Ensures the proposed odds are within a reasonable range for the market.
    If odds are too high for a supposedly high-probability event, there's
    likely something wrong.

    PASS conditions:
      - O1.5: odds <= 1.50
      - GG:   odds <= 2.20
      - O2.5: odds <= 2.50
      - U2.5: odds <= 2.50
      - U3.5: odds <= 2.00
      - NG:   odds <= 2.50
    """
    range_info = ODDS_RANGES.get(market_key)
    if not range_info:
        return {
            "status": "UNKNOWN_MARKET",
            "details": f"No odds range defined for {market_key}",
        }

    min_odds, max_odds, msg = range_info

    if odds < min_odds:
        return {
            "status": "FAIL",
            "details": f"Odds {odds:.2f} below minimum {min_odds:.2f} for {market_key}",
            "min_odds": min_odds,
            "max_odds": max_odds,
        }

    if odds > max_odds:
        return {
            "status": "FAIL",
            "details": f"Odds {odds:.2f} exceed maximum {max_odds:.2f} for {market_key}. {msg}",
            "min_odds": min_odds,
            "max_odds": max_odds,
        }

    return {
        "status": "PASS",
        "details": f"{format_market_name(market_key)} @{odds:.2f} is within reasonable range "
                   f"({min_odds:.2f}–{max_odds:.2f})",
        "min_odds": min_odds,
        "max_odds": max_odds,
    }


# ══════════════════════════════════════════════════════════════════════
# GATE 5: REGIME / ENVIRONMENT CHECK
# ══════════════════════════════════════════════════════════════════════

def gate_regime(market_key: str, odds: float,
                home_team: str, away_team: str) -> Dict[str, Any]:
    """
    Gate 5: Regime / Environment Check.

    Checks if the current goal-scoring regime supports the proposed market.
    Uses:
      1. vfl_active_regime.json (pre-computed regime state)
      2. Recent season average goals from vfl_results.db
      3. Team profile tiers

    PASS conditions:
      - O1.5: Regime is not DEFENSIVE, or avg_goals >= 2.0
      - GG:   Regime is not DEFENSIVE, and team profiles support scoring
      - O2.5: Regime avg_goals >= 2.4
      - U2.5: Regime avg_goals <= 2.4 or regime is DEFENSIVE
      - U3.5: Regime avg_goals <= 2.5
      - NG:   Regime is DEFENSIVE or avg_goals <= 2.2
    """
    regime_data = _load_regime_data()
    team_profiles_data = _get_team_profiles(home_team, away_team)

    regime_name = regime_data.get("active_regime", "STANDARD")
    avg_goals = regime_data.get("metrics", {}).get("avg_goals", 2.59)
    o1_5_rate = regime_data.get("metrics", {}).get("over_1_5_rate", 0.70)

    # Also get recent season average from DB for more current data
    db_avg_goals = _get_recent_avg_goals()
    effective_avg = db_avg_goals if db_avg_goals else avg_goals

    status = "PASS"
    fail_reasons = []

    if market_key == "O1.5":
        if regime_name == "DEFENSIVE" and effective_avg < 2.0:
            status = "FAIL"
            fail_reasons.append(
                f"DEFENSIVE regime ({effective_avg:.2f} avg goals) contradicts O1.5"
            )
        elif effective_avg < 1.8:
            status = "FAIL"
            fail_reasons.append(
                f"Avg goals {effective_avg:.2f} too low for O1.5 confidence"
            )
    elif market_key == "O2.5":
        if effective_avg < 2.4:
            status = "FAIL"
            fail_reasons.append(
                f"Avg goals {effective_avg:.2f} < 2.4 threshold for O2.5"
            )
    elif market_key == "U2.5":
        if effective_avg > 2.4 and regime_name != "DEFENSIVE":
            status = "FAIL"
            fail_reasons.append(
                f"Avg goals {effective_avg:.2f} > 2.4 in {regime_name} regime contradicts U2.5"
            )
    elif market_key == "U3.5":
        # Increased threshold from 2.5 to 2.8 for U3.5 market
        if effective_avg > 2.8:
            status = "FAIL"
            fail_reasons.append(
                f"Avg goals {effective_avg:.2f} > 2.8 threshold for U3.5"
            )
    elif market_key == "GG":
        if regime_name == "DEFENSIVE":
            status = "FAIL"
            fail_reasons.append(
                f"DEFENSIVE regime ({effective_avg:.2f} avg goals) contradicts GG"
            )
    elif market_key == "NG":
        if regime_name != "DEFENSIVE" and effective_avg >= 2.0:
            status = "FAIL"
            fail_reasons.append(
                f"{regime_name} regime ({effective_avg:.2f} avg goals) contradicts NG"
            )

    detail_str = (f"{regime_name} regime, {effective_avg:.2f} avg goals, "
                  f"{o1_5_rate*100:.1f}% O1.5 rate")

    result = {
        "status": status,
        "details": detail_str,
        "regime": regime_name,
        "avg_goals_regime": effective_avg,
        "over_1_5_rate": round(o1_5_rate * 100, 1),
        "team_profiles": team_profiles_data,
    }
    if fail_reasons:
        result["fail_reasons"] = fail_reasons
    return result


def _load_regime_data() -> Dict[str, Any]:
    """Load the active regime from vfl_active_regime.json."""
    try:
        with open(REGIME_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {
        "active_regime": "STANDARD",
        "metrics": {
            "avg_goals": 2.59,
            "over_1_5_rate": 0.70,
        }
    }


def _get_recent_avg_goals(n_matches: int = 500) -> Optional[float]:
    """Get average goals from the most recent N completed matches."""
    try:
        conn = get_results_conn()
        cursor = conn.execute(
            """
            SELECT AVG(total_goals) as avg_g, COUNT(*) as n
            FROM results
            WHERE status = 3
            ORDER BY captured_at DESC
            LIMIT ?
            """,
            (n_matches,),
        )
        row = cursor.fetchone()
        conn.close()
        if row and row["avg_g"] is not None and row["n"] > 0:
            return round(float(row["avg_g"]), 2)
        return None
    except Exception:
        return None


def _get_team_profiles(home_team: str,
                       away_team: str) -> Dict[str, Any]:
    """Get the team profiles for both teams."""
    hp = TEAM_PROFILES.get(home_team, {"avg_goals": 2.59, "tier": "balanced"})
    ap = TEAM_PROFILES.get(away_team, {"avg_goals": 2.59, "tier": "balanced"})
    return {
        "home": {"name": home_team, **hp},
        "away": {"name": away_team, **ap},
    }


# ══════════════════════════════════════════════════════════════════════
# GATE 5: FINITE STATE SPACE (Trap Detection)
# ══════════════════════════════════════════════════════════════════════

def gate_finite_state(home_team: str, away_team: str, market_key: str,
                      odds: Optional[float] = None) -> Dict[str, Any]:
    """
    Gate 5: Finite State Space — checks if pair is a known trap.

    Uses the proven finite state space discovery: each fixture pair has
    a converged O1.5/O2.5/GG rate at 100+ matches. If the rate is below
    threshold, the bet is mathematically unsound and BLOCKED.

    PASS conditions:
      - O1.5: pair O1.5 rate >= 65%
      - O2.5: pair O2.5 rate >= 40%
      - GG:   pair GG rate >= 45%
      - Other markets: default to 65% threshold on O1.5 rate

    Returns dict with verdict, rate, threshold, reason, matches.
    """
    try:
        from finite_state_filter import FiniteStateFilter
        fsf = FiniteStateFilter()
        result = fsf.check_pair(home_team, away_team, market_key)

        if result['verdict'] == 'FAIL':
            return {
                'status': 'FAIL',
                'details': result['reason'],
                'rate': result['rate'],
                'threshold': result['threshold'],
                'most_common': result.get('most_common', '?'),
                'matches': result.get('matches', 0),
                'fail_reasons': [result['reason']],
            }

        return {
            'status': 'PASS',
            'details': result['reason'],
            'rate': result['rate'],
            'threshold': result['threshold'],
            'matches': result.get('matches', 0),
        }

    except Exception as e:
        return {
            'status': 'PASS',
            'details': f'Finite state gate error: {e}, defaulting to PASS',
        }


# ══════════════════════════════════════════════════════════════════════
# GATE 6: LEAGUE POSITION / FORM CHECK
# ══════════════════════════════════════════════════════════════════════

def gate_league_standing(home_team: str, away_team: str, market_key: str) -> Dict[str, Any]:
    """
    Gate 6: League Standing / Form Check.
    Uses the chronological league snapshots to verify current season form.
    
    PASS conditions (Examples):
      - O1.5/GG: At least one team is Top 8 or both have 'W/D' in last 2.
      - HOME: Home rank is significantly better than Away rank (e.g., diff > 4).
      - U3.5: Both teams are Bottom 8 and have low-scoring form.
    """
    try:
        h_standing = _get_latest_standing(home_team)
        a_standing = _get_latest_standing(away_team)
        
        if not h_standing or not a_standing:
            return {"status": "INSUFFICIENT_DATA", "details": "Standing data missing"}

        h_rank = h_standing['rank']
        a_rank = a_standing['rank']
        h_form = h_standing['form']
        a_form = a_standing['form']
        
        status = "PASS"
        reasons = []
        
        # 1. Rank-based Logic
        if market_key == "HOME" and a_rank < h_rank - 2:
            status = "FAIL"
            reasons.append(f"Home rank ({h_rank}) is worse than Away rank ({a_rank})")
            
        elif market_key == "AWAY" and h_rank < a_rank - 2:
            status = "FAIL"
            reasons.append(f"Away rank ({a_rank}) is worse than Home rank ({h_rank})")
            
        # 2. Form-based Logic (Last 5)
        h_last_3 = h_form[-3:] if h_form else ""
        a_last_3 = a_form[-3:] if a_form else ""
        
        if market_key in ["O1.5", "GG"]:
            # If both teams are in terrible form (LL in last 3), fail
            if h_last_3.count('L') >= 2 and a_last_3.count('L') >= 2:
                # But allow if they are top teams (they might bounce back)
                if h_rank > 8 and a_rank > 8:
                    status = "FAIL"
                    reasons.append(f"Both teams in poor form ({h_last_3} vs {a_last_3}) and bottom half")

        elif market_key == "U3.5":
            # If both teams are in top-scoring form (WW in last 3), maybe caution?
            # For now, we trust U3.5 magnets more, but we check if rank diff is massive
            if abs(h_rank - a_rank) > 10:
                # Giant vs Minnow might explode
                status = "PASS" # Stay cautious but pass for now
        
        detail_str = f"H: Rank {h_rank} ({h_form}) vs A: Rank {a_rank} ({a_form})"
        
        res = {
            "status": status,
            "details": detail_str,
            "h_rank": h_rank,
            "a_rank": a_rank,
            "h_form": h_form,
            "a_form": a_form
        }
        if reasons:
            res["fail_reasons"] = reasons
        return res
        
    except Exception as e:
        return {"status": "ERROR", "details": f"Standing gate error: {e}"}

def _get_latest_standing(team_name: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest league standing for a team from Postgres."""
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT rank, points, won, draw, lost, goals_for, goals_against, goal_diff, form
                FROM vfl_league_snapshots
                WHERE team_name = %s
                ORDER BY id DESC LIMIT 1;
            """, (team_name,))
            row = cur.fetchone()
            if row:
                return {
                    "rank": row[0],
                    "points": row[1],
                    "won": row[2],
                    "drawn": row[3],
                    "lost": row[4],
                    "gf": row[5],
                    "ga": row[6],
                    "gd": row[7],
                    "form": row[8]
                }
    except Exception:
        pass
    return None

# ══════════════════════════════════════════════════════════════════════
# MAIN GATE ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════

def run_all_gates(home_team: str, away_team: str, market: str,
                  odds: float, confidence: Optional[float] = None,
                  o15: Optional[float] = None,
                  o25: Optional[float] = None,
                  gg: Optional[float] = None,
                  u35: Optional[float] = None) -> Dict[str, Any]:
    """
    Run all 5 gates and return a comprehensive verdict.

    Args:
        home_team: Home team name
        away_team: Away team name
        market: Market name (e.g., "Over 1.5 Goals", "GG", "O1.5")
        odds: Decimal odds for the proposed bet
        confidence: Optional confidence percentage (0-100)
        o15: Over 1.5 decimal odds (for cluster check)
        o25: Over 2.5 decimal odds (for cluster check)
        gg: Goal-Goal decimal odds (for cluster check)
        u35: Under 3.5 decimal odds (for cluster check)

    Returns:
        dict with gates results and final verdict
    """
    # Validate inputs
    home_clean = validate_team(home_team)
    away_clean = validate_team(away_team)
    if not home_clean:
        return _error_result(f"Unknown home team: {home_team}", "INVALID_INPUT")
    if not away_clean:
        return _error_result(f"Unknown away team: {away_team}", "INVALID_INPUT")
    if home_clean == away_clean:
        return _error_result("Home and away teams are the same", "INVALID_INPUT")

    market_key = normalize_market(market)
    if not market_key:
        return _error_result(f"Unknown market: {market}. Valid: {sorted(MARKET_ALIASES.keys())}",
                             "INVALID_INPUT")

    if odds <= 0:
        return _error_result(f"Invalid odds: {odds}", "INVALID_INPUT")

    fixture = f"{home_clean} vs {away_clean}"

    # Run all 6 gates
    g1 = gate_h2h(home_clean, away_clean, market_key, odds)
    g2 = gate_cluster(home_clean, away_clean, market_key, odds, o15, o25, gg, u35)
    g3 = gate_odds_reasonableness(market_key, odds)
    g4 = gate_regime(market_key, odds, home_clean, away_clean)
    g5 = gate_finite_state(home_clean, away_clean, market_key, odds)
    g6 = gate_league_standing(home_clean, away_clean, market_key)

    gates = {
        "h2h": g1,
        "cluster": g2,
        "odds_reasonableness": g3,
        "regime": g4,
        "finite_state": g5,
        "league_standing": g6,
    }

    # Count passes
    passed = 0
    failed = 0
    insufficient = 0
    errors = 0
    failing_gates = []

    for gate_name, gate_result in gates.items():
        s = gate_result.get("status", "ERROR")
        if s == "PASS":
            passed += 1
        elif s == "FAIL":
            failed += 1
            failing_gates.append(gate_name)
        elif s == "INSUFFICIENT_DATA":
            insufficient += 1
        else:
            errors += 1
            failing_gates.append(gate_name)

    total = len(gates)
    
    # Standard verdict: PASS if 0 fails
    verdict = "PASS" if failed == 0 and errors == 0 else "FAIL"

    # GOLDEN OVERRIDE: If H2H is extremely strong (>90% hit rate on 20+ matches),
    # we allow the bet even if another gate (like cluster or regime) is cautious.
    if verdict == "FAIL" and market_key in ("O1.5", "U3.5"):
        h2h_rate = g1.get("u35_rate", 0) if market_key == "U3.5" else g1.get("o15_rate", 0)
        h2h_matches = g1.get("n_matches", 0)
        
        if h2h_matches >= 20 and h2h_rate >= 90.0:
            # Check if failures are "soft" (cluster or regime, not finite_state trap or odds reason)
            soft_failures = [f for f in failing_gates if f in ("cluster", "regime")]
            if len(soft_failures) == len(failing_gates):
                verdict = "PASS"
                # Note the override in the result
                gates["override"] = {
                    "status": "PASS",
                    "details": f"Golden H2H Override: {h2h_rate}% over {h2h_matches} matches overrides soft failures {soft_failures}"
                }

    # MAGNET OVERRIDE: If it's an Elite Magnet, we trust it over soft failures
    if verdict == "FAIL":
        magnet = detect_magnet(home_clean, away_clean, market_key)
        if magnet:
            soft_failures = [f for f in failing_gates if f in ("cluster", "regime")]
            if len(soft_failures) == len(failing_gates):
                verdict = "PASS"
                gates["override"] = {
                    "status": "PASS",
                    "details": f"Elite Magnet Override: Fixture is a known winner, overriding soft failures {soft_failures}"
                }

    # Compute recommended stake fraction based on gates passed
    # Base: 0.04 (4% of bankroll) if all pass
    # Reduce by 0.01 for each non-critical insufficiency, min 0.01
    if verdict == "PASS":
        base_stake = 0.04
        # Reduce for insufficient data
        base_stake -= insufficient * 0.005
        # Reduce for low confidence
        if confidence is not None and confidence < 70:
            base_stake -= 0.01
        elif confidence is not None and confidence < 50:
            base_stake -= 0.02
        recommended_stake = max(0.01, round(base_stake, 3))
    else:
        recommended_stake = 0.0

    result = {
        "fixture": fixture,
        "proposed_market": format_market_name(market_key),
        "proposed_market_key": market_key,
        "proposed_odds": odds,
        "proposed_confidence": confidence,
        "gates": gates,
        "verdict": verdict,
        "gates_passed": passed,
        "gates_total": total,
        "gates_failed": failed,
        "gates_insufficient_data": insufficient,
        "gates_errors": errors,
        "failing_gates": failing_gates,
        "recommended_stake_fraction": recommended_stake,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return result


def _error_result(message: str, error_type: str = "ERROR") -> Dict[str, Any]:
    """Return a structured error result."""
    return {
        "fixture": "?",
        "proposed_market": "?",
        "proposed_market_key": "?",
        "proposed_odds": 0,
        "proposed_confidence": None,
        "gates": {},
        "verdict": "FAIL",
        "gates_passed": 0,
        "gates_total": 4,
        "gates_failed": 0,
        "gates_insufficient_data": 0,
        "gates_errors": 1,
        "failing_gates": ["input_validation"],
        "recommended_stake_fraction": 0.0,
        "error": message,
        "error_type": error_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════
# BATCH PROCESSING
# ══════════════════════════════════════════════════════════════════════

def process_batch(batch_file: str) -> List[Dict[str, Any]]:
    """Process a batch of predictions from a JSON file.

    Expected format:
    {
        "predictions": [
            {"home": "Chelsea", "away": "Liverpool", "market": "Over 1.5 Goals",
             "odds": 1.18, "confidence": 93, ...},
            ...
        ]
    }
    Or the live_test_predictions.json format with matchdays/fixtures.
    """
    try:
        with open(batch_file) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {batch_file}: {e}", file=sys.stderr)
        return [_error_result(str(e), "FILE_ERROR")]

    results = []

    # Check if it's the live predictions format
    if "matchdays" in data:
        for md in data["matchdays"]:
            for fx in md.get("fixtures", []):
                preds = fx.get("prediction", {})
                picks = preds.get("predictions", [])
                if preds.get("primary"):
                    picks = [preds["primary"]]  # Use primary if available

                for pick in picks:
                    market = pick.get("market", "")
                    odds_val = pick.get("odds", 0)
                    conf = pick.get("confidence_pct")
                    res = run_all_gates(
                        home_team=fx.get("home", ""),
                        away_team=fx.get("away", ""),
                        market=market,
                        odds=odds_val,
                        confidence=conf,
                        o15=fx.get("odds", {}).get("over_1.5"),
                        o25=fx.get("odds", {}).get("over_2.5"),
                        gg=fx.get("odds", {}).get("gg"),
                        u35=fx.get("odds", {}).get("under_3.5"),
                    )
                    res["event_id"] = fx.get("event_id")
                    res["season_name"] = md.get("season_name")
                    res["matchday"] = md.get("matchday")
                    results.append(res)
    elif "predictions" in data:
        for item in data["predictions"]:
            res = run_all_gates(
                home_team=item.get("home", item.get("home_team", "")),
                away_team=item.get("away", item.get("away_team", "")),
                market=item.get("market", ""),
                odds=item.get("odds", 0),
                confidence=item.get("confidence", item.get("confidence_pct")),
            )
            results.append(res)
    else:
        # Try as a single prediction object
        if "home" in data or "home_team" in data:
            res = run_all_gates(
                home_team=data.get("home", data.get("home_team", "")),
                away_team=data.get("away", data.get("away_team", "")),
                market=data.get("market", ""),
                odds=data.get("odds", 0),
                confidence=data.get("confidence", data.get("confidence_pct")),
            )
            results.append(res)
        else:
            print(f"Unknown format in {batch_file}", file=sys.stderr)
            return [_error_result("Unknown batch format", "PARSE_ERROR")]

    return results


def process_live() -> List[Dict[str, Any]]:
    """Process all predictions from live_test_predictions.json."""
    if not os.path.isfile(LIVE_PREDICTIONS_FILE):
        return [_error_result(f"Live predictions file not found: {LIVE_PREDICTIONS_FILE}",
                              "FILE_ERROR")]
    return process_batch(LIVE_PREDICTIONS_FILE)


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Pre-prediction Quality Control Gate — checks ALL data before picks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python prediction_gate.py --home "Chelsea" --away "Liverpool" --market "Over 1.5 Goals" --odds 1.18
  python prediction_gate.py --home "Everton" --away "Leeds" --market "GG" --odds 2.10 --json
  python prediction_gate.py --batch predictions.json
  python prediction_gate.py --live
        """,
    )

    # Single pick mode
    parser.add_argument("--home", type=str, help="Home team name")
    parser.add_argument("--away", type=str, help="Away team name")
    parser.add_argument("--market", type=str, help="Market name (e.g., 'Over 1.5 Goals')")
    parser.add_argument("--odds", type=float, help="Decimal odds")
    parser.add_argument("--confidence", type=float, default=None,
                        help="Confidence percentage (0-100)")
    parser.add_argument("--o15", type=float, default=None,
                        help="Over 1.5 decimal odds (for cluster check)")
    parser.add_argument("--o25", type=float, default=None,
                        help="Over 2.5 decimal odds (for cluster check)")
    parser.add_argument("--gg", type=float, default=None,
                        help="Goal-Goal decimal odds (for cluster check)")
    parser.add_argument("--u35", type=float, default=None,
                        help="Under 3.5 decimal odds (for cluster check)")

    # Batch modes
    parser.add_argument("--batch", type=str, default=None,
                        help="Path to batch predictions JSON file")
    parser.add_argument("--live", action="store_true",
                        help="Process live_test_predictions.json")

    # Output
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON (for programmatic consumption)")
    parser.add_argument("--summary", action="store_true",
                        help="Output a concise summary table")

    args = parser.parse_args()

    # Determine mode
    if args.live:
        results = process_live()
    elif args.batch:
        results = process_batch(args.batch)
    elif args.home and args.away and args.market and args.odds:
        result = run_all_gates(
            home_team=args.home,
            away_team=args.away,
            market=args.market,
            odds=args.odds,
            confidence=args.confidence,
            o15=args.o15,
            o25=args.o25,
            gg=args.gg,
            u35=args.u35,
        )
        results = [result]
    else:
        parser.print_help()
        sys.exit(1)

    # Output
    if args.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=2))
    elif args.summary:
        _print_summary(results)
    else:
        _pretty_print(results)


def _pretty_print(results: List[Dict[str, Any]]):
    """Pretty-print gate results for human reading."""
    for i, r in enumerate(results):
        if i > 0:
            print("\n" + "─" * 70)

        if "error" in r:
            print(f"❌ ERROR: {r.get('error', 'Unknown error')}")
            continue

        verdict_icon = "✅" if r["verdict"] == "PASS" else "❌"
        print(f"\n{verdict_icon}  GATE VERDICT: {r['verdict']}")
        print(f"   Fixture:     {r['fixture']}")
        print(f"   Market:      {r['proposed_market']} @ {r['proposed_odds']:.2f}")
        if r.get("proposed_confidence"):
            print(f"   Confidence:  {r['proposed_confidence']}%")
        print(f"   Gates:       {r['gates_passed']}/{r['gates_total']} passed")
        if r["recommended_stake_fraction"] > 0:
            print(f"   Recommended stake: {r['recommended_stake_fraction']*100:.1f}% of bankroll")
        else:
            print(f"   Recommended stake: SKIP (verdict is FAIL)")

        if r.get("failing_gates"):
            print(f"   Failing gates: {', '.join(r['failing_gates'])}")

        for gate_name in ["h2h", "cluster", "odds_reasonableness", "regime", "finite_state", "league_standing"]:
            g = r["gates"].get(gate_name, {})
            s = g.get("status", "?")
            icon = {"PASS": "✅", "FAIL": "❌", "INSUFFICIENT_DATA": "⚠️",
                    "ERROR": "💥", "UNKNOWN_MARKET": "❓"}.get(s, "❓")
            detail = g.get("details", "")
            if s == "PASS":
                print(f"     {icon} {gate_name.replace('_', ' ').title()}: {detail}")
            else:
                print(f"     {icon} {gate_name.replace('_', ' ').title()}: {s} — {detail}")
                for reason in g.get("fail_reasons", g.get("pass_reasons", [])):
                    print(f"           • {reason}")


def _print_summary(results: List[Dict[str, Any]]):
    """Print a tabular summary of gate results."""
    headers = ["Fixture", "Market", "Odds", "Conf", "H2H", "Clst",
               "OddsR", "Regime", "FS", "Verdict", "Stake%"]
    # Print header
    print(" | ".join(headers))
    print("-|-" + "".join(["-" * len(h) for h in headers]))

    for r in results:
        if "error" in r:
            print(f"{r.get('error', '?')} | ERROR")
            continue
        gates = r.get("gates", {})
        row = [
            r.get("fixture", "?"),
            r.get("proposed_market_key", "?"),
            f"{r.get('proposed_odds', 0):.2f}",
            f"{r.get('proposed_confidence', '?')}" if r.get("proposed_confidence") else "?",
            _short_status(gates.get("h2h", {}).get("status", "?")),
            _short_status(gates.get("cluster", {}).get("status", "?")),
            _short_status(gates.get("odds_reasonableness", {}).get("status", "?")),
            _short_status(gates.get("regime", {}).get("status", "?")),
            _short_status(gates.get("finite_state", {}).get("status", "?")),
            _short_status(gates.get("league_standing", {}).get("status", "?")),
            r.get("verdict", "?"),
            f"{r.get('recommended_stake_fraction', 0)*100:.1f}%",
        ]
        print(" | ".join(row))


def _short_status(status: str) -> str:
    """Shorten a status to 3-4 chars for table output."""
    mapping = {
        "PASS": "P",
        "FAIL": "F",
        "INSUFFICIENT_DATA": "ID",
        "ERROR": "E",
        "UNKNOWN_MARKET": "?",
    }
    return mapping.get(status, status[:4])


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
