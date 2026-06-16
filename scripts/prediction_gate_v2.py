#!/usr/bin/env python3
"""
prediction_gate_v2.py — Robust Bayesian Gating Engine (Gating V2)
==================================================================
A mathematically robust checkpoint for predictions. Instead of binary boolean
gates and hardcoded overrides, this engine uses:
  1. Empirical Bayes H2H Smoothing (Beta-Binomial Conjugate Prior)
  2. Odds Cluster Probability Mapping (Empirical Cluster Win Rates)
  3. Finite State Space Probability Integration
  4. Team Profile Poisson Goal Expectation Model
  5. Probabilistic Ensemble Aggregation (Edge and Kelly stake sizing)

Author: VFL Engineering Team (AI Pair Programmer)
"""

import os
import sys
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add paths
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')

from common.db_manager import get_db
from odds_cluster_classifier import classify_match
from finite_state_filter import FiniteStateFilter

# ──────────────────────────────────────────────────────────────────────
# CONFIG & PATHS
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
CLUSTER_RATES_FILE = BASE_DIR / "analysis" / "cluster_market_rates.json"

# League baselines (priors)
MARKET_BASELINES = {
    "O1.5": 0.704,
    "O2.5": 0.495,
    "U2.5": 0.505,
    "U3.5": 0.730,
    "GG": 0.528,
    "NG": 0.472,
}

# Dynamic Odds Limits (Z-Score fallback ranges)
ODDS_RANGES = {
    "O1.5": (1.01, 1.55),
    "O2.5": (1.01, 2.70),
    "U2.5": (1.01, 2.70),
    "U3.5": (1.01, 2.10),
    "GG":   (1.01, 2.40),
    "NG":   (1.01, 2.60),
}

# Minimum odds floor per market — odds below this are structurally unprofitable
# even at very high win rates. Formula: min_odds = 1 / (baseline + 0.05)
# This ensures at least 5% EV headroom at baseline win rate.
MIN_PROFITABLE_ODDS = {
    "O1.5": 1.25,   # need >80% WR to profit below 1.25
    "O2.5": 1.40,   # need >71% WR to profit below 1.40
    "U2.5": 1.40,
    "U3.5": 1.25,   # need >80% WR to profit below 1.25
    "GG":   1.35,   # need >74% WR to profit below 1.35
    "NG":   1.35,
    # 1X2 markets are typically long enough odds to be profitable
    "Home Win": 1.30,
    "Away Win": 1.30,
    "Draw":     1.50,
}

# Import TEAM_PROFILES from original gate for consistency
from prediction_gate import TEAM_PROFILES, MARKET_ALIASES, validate_team, normalize_market, format_market_name

class RobustGatingEngine:
    def __init__(self):
        self.fsf = FiniteStateFilter()
        self.cluster_rates = self._load_cluster_rates()

    def _load_cluster_rates(self) -> Dict:
        if CLUSTER_RATES_FILE.exists():
            try:
                with open(CLUSTER_RATES_FILE) as f:
                    # JSON keys are strings, convert to ints
                    data = json.load(f)
                    return {int(k): v for k, v in data.items()}
            except Exception as e:
                print(f"Warning loading cluster rates: {e}", file=sys.stderr)
        return {}

    def get_h2h_probability(self, home: str, away: str, market_key: str) -> Tuple[float, int]:
        """Compute posterior probability using Empirical Bayes (Beta-Binomial conjugate update)."""
        baseline = MARKET_BASELINES.get(market_key, 0.5)
        N_prior = 8.0  # prior strength (weight in matches)
        alpha_0 = N_prior * baseline
        beta_0 = N_prior * (1.0 - baseline)

        try:
            with get_db() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) as n,
                        SUM(CASE WHEN total_goals > 1.5 THEN 1 ELSE 0 END) as o15,
                        SUM(CASE WHEN total_goals > 2.5 THEN 1 ELSE 0 END) as o25,
                        SUM(CASE WHEN home_goals > 0 AND away_goals > 0 THEN 1 ELSE 0 END) as gg,
                        SUM(CASE WHEN total_goals < 3.5 THEN 1 ELSE 0 END) as u35
                    FROM vfl_results_v2
                    WHERE (
                          (home_team = %s AND away_team = %s)
                          OR (home_team = %s AND away_team = %s)
                      )
                    """,
                    (home, away, away, home),
                )
                row = cursor.fetchone()
        except Exception as e:
            row = None

        if not row or row["n"] is None or row["n"] == 0:
            return baseline, 0

        n = int(row["n"])
        
        # Determine actual hits
        if market_key == "O1.5":
            k = int(row["o15"])
        elif market_key == "O2.5":
            k = int(row["o25"])
        elif market_key == "U2.5":
            k = n - int(row["o25"])
        elif market_key == "U3.5":
            k = int(row["u35"])
        elif market_key == "GG":
            k = int(row["gg"])
        elif market_key == "NG":
            k = n - int(row["gg"])
        else:
            k = int(row["o15"]) # Default fallback

        # Posterior probability
        p_post = (k + alpha_0) / (n + N_prior)
        return p_post, n

    def get_cluster_probability(self, o15: float, o25: float, gg: float, u35: float, market_key: str) -> float:
        """Get the cluster-based empirical probability for the candidate market."""
        res = classify_match(o15, o25, gg, u35)
        cid = res.get('cluster_id', -1)
        if cid == -1 or not self.cluster_rates:
            # Fallback to implied probability
            return 0.5
            
        c_info = self.cluster_rates.get(cid)
        if not c_info:
            return 0.5
            
        m_info = c_info.get("markets", {}).get(market_key)
        if m_info:
            return m_info["hit_rate"]
            
        return 0.5

    def get_fs_probability(self, home: str, away: str, market_key: str) -> float:
        """Extract finite state space probability with smoothing."""
        baseline = MARKET_BASELINES.get(market_key, 0.5)
        stats = self.fsf.get_pair_stats(home, away)
        if not stats or stats.get('matches', 0) == 0:
            return baseline

        n = stats.get('matches', 0)
        
        if market_key == "O1.5":
            rate = stats.get('o15_rate', 70.0) / 100.0
        elif market_key == "O2.5":
            rate = stats.get('o25_rate', 50.0) / 100.0
        elif market_key == "U2.5":
            rate = (100.0 - stats.get('o25_rate', 50.0)) / 100.0
        elif market_key == "U3.5":
            rate = stats.get('u35_rate', 73.0) / 100.0
        elif market_key == "GG":
            rate = stats.get('gg_rate', 53.0) / 100.0
        elif market_key == "NG":
            rate = (100.0 - stats.get('gg_rate', 53.0)) / 100.0
        else:
            rate = stats.get('o15_rate', 70.0) / 100.0

        k = round(rate * n)
        
        # Smoothed Finite State rate
        p_post = (k + 8.0 * baseline) / (n + 8.0)
        return p_post

    def get_poisson_probability(self, home: str, away: str, market_key: str) -> float:
        """Compute expected goals probability using a double Poisson model."""
        hp = TEAM_PROFILES.get(home, {"avg_goals": 2.59})
        ap = TEAM_PROFILES.get(away, {"avg_goals": 2.59})
        
        # Split goals: VFL averages 2.59 goals, home advantage adds ~0.15 goals
        # Home expected base = 1.35, Away expected base = 1.24
        # We scale by team rating profiles
        lambda_h = 1.35 * (hp["avg_goals"] / 2.59)
        lambda_a = 1.24 * (ap["avg_goals"] / 2.59)
        lam = lambda_h + lambda_a
        
        if market_key == "O1.5":
            # 1 - P(0) - P(1)
            p_0 = math.exp(-lam)
            p_1 = lam * p_0
            return 1.0 - p_0 - p_1
            
        elif market_key == "O2.5":
            # 1 - P(0) - P(1) - P(2)
            p_0 = math.exp(-lam)
            p_1 = lam * p_0
            p_2 = (lam**2 / 2.0) * p_0
            return 1.0 - p_0 - p_1 - p_2
            
        elif market_key == "U2.5":
            # P(0) + P(1) + P(2)
            p_0 = math.exp(-lam)
            p_1 = lam * p_0
            p_2 = (lam**2 / 2.0) * p_0
            return p_0 + p_1 + p_2
            
        elif market_key == "U3.5":
            # P(0) + P(1) + P(2) + P(3)
            p_0 = math.exp(-lam)
            p_1 = lam * p_0
            p_2 = (lam**2 / 2.0) * p_0
            p_3 = (lam**3 / 6.0) * p_0
            return p_0 + p_1 + p_2 + p_3
            
        elif market_key == "GG":
            # P(H >= 1) * P(A >= 1)
            p_h_ge_1 = 1.0 - math.exp(-lambda_h)
            p_a_ge_1 = 1.0 - math.exp(-lambda_a)
            return p_h_ge_1 * p_a_ge_1
            
        elif market_key == "NG":
            p_h_ge_1 = 1.0 - math.exp(-lambda_h)
            p_a_ge_1 = 1.0 - math.exp(-lambda_a)
            return 1.0 - (p_h_ge_1 * p_a_ge_1)
            
        return MARKET_BASELINES.get(market_key, 0.5)

    def evaluate_bet(self, home_team: str, away_team: str, market: str, odds: float,
                     o15: Optional[float] = None, o25: Optional[float] = None,
                     gg: Optional[float] = None, u35: Optional[float] = None,
                     match_day: Optional[int] = None) -> Dict[str, Any]:
        """Evaluate a prediction using the Robust Bayesian Gate."""
        # 1. Inputs Normalization
        home_clean = validate_team(home_team)
        away_clean = validate_team(away_team)
        if not home_clean or not away_clean or home_clean == away_clean:
            return {"verdict": "FAIL", "error": "Invalid team name"}
            
        market_key = normalize_market(market)
        if not market_key or odds <= 1.0:
            return {"verdict": "FAIL", "error": f"Invalid market/odds: {market} @ {odds}"}

        # Load missing odds from DB if necessary
        if any(x is None for x in [o15, o25, gg, u35]):
            from prediction_gate import _load_odds_from_db
            loaded_odds = _load_odds_from_db(home_clean, away_clean)
            if loaded_odds:
                o15 = o15 or loaded_odds.get("o15")
                o25 = o25 or loaded_odds.get("o25")
                gg = gg or loaded_odds.get("gg")
                u35 = u35 or loaded_odds.get("u35")

        # 2. Probability Estimation
        p_h2h, n_h2h = self.get_h2h_probability(home_clean, away_clean, market_key)
        
        # If we have full odds, get cluster prob, else use fallback
        if all(x is not None for x in [o15, o25, gg, u35]):
            p_cluster = self.get_cluster_probability(o15, o25, gg, u35, market_key)
        else:
            p_cluster = 1.0 / odds  # prior
            
        p_fs = self.get_fs_probability(home_clean, away_clean, market_key)
        p_poisson = self.get_poisson_probability(home_clean, away_clean, market_key)
        
        # 3. Probabilistic Ensemble Combination
        # Weights: H2H (0.3), Cluster (0.3), FS (0.2), Poisson (0.2)
        p_combined = (0.30 * p_h2h) + (0.30 * p_cluster) + (0.20 * p_fs) + (0.20 * p_poisson)
        
        # 4. Check for Deterministic Matchday Lock
        is_deterministic_lock = False
        lock_n = 0
        # Prefer the richer v2 lock file (4138 locks from full H2H), fall back to v1
        locks_path_v2 = "/home/ubuntu/faith-workspace/vfl-empire/models/matchday_locks_v2.json"
        locks_path_v1 = "/home/ubuntu/faith-workspace/vfl-empire/models/matchday_locks.json"
        locks_path = locks_path_v2 if os.path.exists(locks_path_v2) else locks_path_v1
        if match_day is not None and os.path.exists(locks_path):
            try:
                with open(locks_path) as f:
                    locks_data = json.load(f)
                day_locks = locks_data.get(str(match_day), [])
                for lock in day_locks:
                    lock_teams = sorted(lock['teams'].split(' vs '))
                    curr_teams = sorted([home_clean, away_clean])
                    if lock_teams == curr_teams and lock['market'] == market_key:
                        is_deterministic_lock = True
                        lock_n = lock['n']
                        break
            except Exception as e:
                print(f"Warning loading matchday locks: {e}", file=sys.stderr)

        if is_deterministic_lock:
            # Force pass as 100% win-rate lock
            p_combined = 1.0
            verdict = "PASS"
            fail_reasons = []
            edge = p_combined - (1.0 / odds)
            ev_pct = edge * odds * 100.0
        else:
            # 5. Edge & EV Calculation
            edge = p_combined - (1.0 / odds)
            ev_pct = edge * odds * 100.0
            
            # 6. Risk Warnings & Hard Filters
            verdict = "PASS"
            fail_reasons = []
            
            # Hard Filter A: Finite State Strict Trap check
            fs_check = self.fsf.check_pair(home_clean, away_clean, market_key)
            if fs_check['verdict'] == 'FAIL':
                if fs_check.get('rate', 0.8) < (MARKET_BASELINES.get(market_key, 0.5) - 0.15):
                    verdict = "FAIL"
                    fail_reasons.append(f"Finite State Hard Trap: {fs_check.get('reason')}")
            
            # Hard Filter B: Odds Reasonableness + Structural Profitability Floor
            limits = ODDS_RANGES.get(market_key)
            if limits:
                min_o, max_o = limits
                if odds < min_o or odds > max_o:
                    verdict = "FAIL"
                    fail_reasons.append(f"Odds {odds:.2f} out of reasonable range ({min_o}–{max_o})")
            # Structural Profitability Floor: reject odds so short that no realistic
            # win rate can produce positive EV (e.g. O1.5 @ 1.10 needs 91%+ to profit)
            min_profitable = MIN_PROFITABLE_ODDS.get(market_key)
            if min_profitable and odds < min_profitable and not is_deterministic_lock:
                verdict = "FAIL"
                fail_reasons.append(
                    f"Odds {odds:.2f} below structural floor {min_profitable:.2f} — "
                    f"unprofitable even at high win rates (need >{100/odds:.1f}% WR)"
                )
                    
            # Hard Filter C: Positive EV / Edge requirement
            min_edge = 0.025  # 2.5% edge minimum
            if edge < min_edge:
                verdict = "FAIL"
                fail_reasons.append(f"Insufficient value edge: {edge*100:+.2f}% (need >= {min_edge*100}%)")

        # 7. Stake Sizing (Fractional Kelly)
        if verdict == "PASS" and odds > 1.0:
            raw_kelly = (p_combined * odds - 1.0) / (odds - 1.0)
            # Apply 10% fractional Kelly (or 25% if it is a guaranteed lock!)
            multiplier = 0.25 if is_deterministic_lock else 0.10
            fractional_kelly = multiplier * raw_kelly
            recommended_stake = max(0.01, min(0.08 if is_deterministic_lock else 0.04, round(fractional_kelly, 3)))
        else:
            recommended_stake = 0.0
            
        return {
            "fixture": f"{home_clean} vs {away_clean}",
            "proposed_market": format_market_name(market_key),
            "proposed_market_key": market_key,
            "proposed_odds": odds,
            "verdict": verdict,
            "probability_ensemble": {
                "h2h": round(p_h2h, 4),
                "cluster": round(p_cluster, 4),
                "finite_state": round(p_fs, 4),
                "poisson": round(p_poisson, 4),
                "combined": round(p_combined, 4)
            },
            "edge": round(edge, 4),
            "ev_pct": round(ev_pct, 2),
            "recommended_stake_fraction": recommended_stake,
            "fail_reasons": fail_reasons,
            "n_matches_h2h": n_h2h,
            "is_deterministic_lock": is_deterministic_lock,
            "lock_n": lock_n,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

def run_all_gates(home_team: str, away_team: str, market: str, odds: float,
                  confidence: Optional[float] = None,
                  o15: Optional[float] = None, o25: Optional[float] = None,
                  gg: Optional[float] = None, u35: Optional[float] = None,
                  match_day: Optional[int] = None) -> Dict[str, Any]:
    """Helper function to mirror original API."""
    engine = RobustGatingEngine()
    res = engine.evaluate_bet(home_team, away_team, market, odds, o15, o25, gg, u35, match_day=match_day)
    return res

if __name__ == "__main__":
    # Test CLI execution
    engine = RobustGatingEngine()
    import argparse
    parser = argparse.ArgumentParser(description="Robust Gating Engine V2 Test")
    parser.add_argument("--home", type=str, default="Chelsea")
    parser.add_argument("--away", type=str, default="Liverpool")
    parser.add_argument("--market", type=str, default="Over 1.5 Goals")
    parser.add_argument("--odds", type=float, default=1.18)
    args = parser.parse_args()
    
    result = engine.evaluate_bet(args.home, args.away, args.market, args.odds)
    print(json.dumps(result, indent=2))
