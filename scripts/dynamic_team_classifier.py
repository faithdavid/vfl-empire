#!/usr/bin/env python3
"""
Dynamic Team Classifier — replaces static tier tables with DB-backed dynamic profiles.
====================================================================================

Queries vfl_results.db (18,777+ matches across 82 seasons) to compute per-team
dynamic profiles, applies known prior strength classifications (Bayesian priors),
and blends all-time identity (70%) with current-season form (30%).

NOW WITH RECENCY-WEIGHTED PROFILES:
  - Flat all-time averages are still available via all_time_profiles
  - Recency-weighted profiles (weighted_profiles) give more weight to recent
    seasons, later matchdays within seasons, and each team's last 5 matches.
  - get_team_profile() returns the weighted profile by default.
  - Season form blend is now 50/50 (instead of 70/30) when season_id is provided,
    because the base is already recency-weighted.

Usage:
    from dynamic_team_classifier import DynamicTeamClassifier
    classifier = DynamicTeamClassifier()
    profile = classifier.get_team_profile("Manchester Blue")
    score = classifier.get_matchup_u35_score("Manchester Blue", "Leeds")
"""

import logging
import threading
import sys
import os
import json
from typing import Dict, Any, List, Optional
from collections import defaultdict
from pathlib import Path

# Add paths
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from win_quota_analyst import WinQuotaAnalyst
from common.db_manager import get_db
from season_fingerprinter import SeasonFingerprinter

logger = logging.getLogger("[DYNAMIC_CLASSIFIER]")

# ── Recency-weighting parameters ───────────────────────────────────────────────
DEFAULT_DECAY_RATE = 0.85       # Exponential decay factor per ~30 season units
DEFAULT_RECENT_MULT = 2.0       # Within-season matchday boost multiplier
DEFAULT_RECENT_WINDOW = 5       # Last N matches per team get extra multiplier

# ── Default fallback (neutral) ─────────────────────────────────────────────────
DEFAULT_SCORE = 75
DEFAULT_PROFILE = {
    "u35_rate": 75.0,
    "o15_rate": 70.0,
    "draw_rate": 37.0,
    "avg_goals": 2.5,
    "avg_scored": 1.3,
    "avg_conceded": 1.2,
    "n_matches": 0,
    "strength_class": "balanced",
}

# ── Known Team Strength Classifications (Bayesian Priors) ──────────────────────
# Reflects real-world EPL reputation as a prior belief.
# Keys: o15_home_boost / u35_penalty / u35_boost are additive adjustments
# applied to the blended base rate.
TEAM_STRENGTH_PRIORS = {
    # Attacking Powerhouses (high goals, low U3.5)
    "Manchester Blue": {
        "class": "powerhouse",
        "goal_ceiling": 5,
        "o15_home_boost": 15,
        "u35_penalty": -8,
    },
    "Chelsea": {
        "class": "powerhouse",
        "goal_ceiling": 5,
        "o15_home_boost": 8,
        "u35_penalty": -5,
    },
    "London Guns": {
        "class": "powerhouse",
        "goal_ceiling": 5,
        "o15_home_boost": 8,
        "u35_penalty": -5,
    },
    "Manchester Red": {
        "class": "powerhouse",
        "goal_ceiling": 5,
        "o15_home_boost": 10,
        "u35_penalty": -5,
    },
    "Liverpool": {
        "class": "powerhouse",
        "goal_ceiling": 5,
        "o15_home_boost": 10,
        "u35_penalty": -5,
    },
    # Attacking teams
    "Tottenham": {
        "class": "attacking",
        "goal_ceiling": 4,
        "o15_home_boost": 5,
        "u35_penalty": -2,
    },
    "West Ham": {
        "class": "attacking",
        "goal_ceiling": 4,
        "o15_home_boost": 5,
        "u35_penalty": -2,
    },
    "Wolverhampton": {
        "class": "attacking",
        "goal_ceiling": 4,
        "o15_home_boost": 5,
        "u35_penalty": -2,
    },
    # Mid-table balanced
    "Crystal Palace": {
        "class": "balanced",
        "goal_ceiling": 4,
        "o15_home_boost": 2,
        "u35_penalty": 0,
    },
    "Brighton": {
        "class": "balanced",
        "goal_ceiling": 3,
        "o15_home_boost": 0,
        "u35_penalty": 0,
    },
    "Bournemouth": {
        "class": "balanced",
        "goal_ceiling": 3,
        "o15_home_boost": 0,
        "u35_penalty": 0,
    },
    "Newcastle": {
        "class": "balanced",
        "goal_ceiling": 3,
        "o15_home_boost": 0,
        "u35_penalty": 0,
    },
    "Aston Villa": {
        "class": "balanced",
        "goal_ceiling": 3,
        "o15_home_boost": 0,
        "u35_penalty": 0,
    },
    # Defensive Walls (low goals, high U3.5)
    "Fulham": {
        "class": "defensive",
        "goal_ceiling": 2,
        "o15_home_boost": -5,
        "u35_boost": 5,
    },
    "Leeds": {
        "class": "defensive",
        "goal_ceiling": 2,
        "o15_home_boost": -8,
        "u35_boost": 8,
    },
    "Everton": {
        "class": "defensive",
        "goal_ceiling": 2,
        "o15_home_boost": -10,
        "u35_boost": 10,
    },
}


def _normalize_team(name: str) -> str:
    """Normalise team name to canonical form."""
    n = name.strip().lower()
    aliases = {
        "manchester blue": "Manchester Blue",
        "man blue": "Manchester Blue",
        "manchester red": "Manchester Red",
        "man red": "Manchester Red",
        "london guns": "London Guns",
        "london gunners": "London Guns",
        "arsenal": "London Guns",
        "chelsea": "Chelsea",
        "liverpool": "Liverpool",
        "aston villa": "Aston Villa",
        "tottenham": "Tottenham",
        "tottenham hotspur": "Tottenham",
        "everton": "Everton",
        "wolverhampton": "Wolverhampton",
        "wolves": "Wolverhampton",
        "newcastle": "Newcastle",
        "newcastle united": "Newcastle",
        "leeds": "Leeds",
        "leeds united": "Leeds",
        "fulham": "Fulham",
        "west ham": "West Ham",
        "west ham united": "West Ham",
        "bournemouth": "Bournemouth",
        "brighton": "Brighton",
        "brighton & hove albion": "Brighton",
        "crystal palace": "Crystal Palace",
    }
    return aliases.get(n, name.strip().title())


def _extract_season_int(season_id: str) -> int:
    """Extract the integer part from a season_id like 'vf:season:3091718'."""
    try:
        return int(season_id.split(":")[-1])
    except (ValueError, IndexError, AttributeError):
        return 0


def _cap_score(score: float) -> int:
    """Clamp a score between 10 and 99 (inclusive)."""
    return max(10, min(99, round(score)))


class DynamicTeamClassifier:
    """
    Database-backed dynamic team classifier.

    On init, connects to vfl_results.db and pre-computes both flat all-time
    profiles AND recency-weighted profiles for every team. Profiles are cached
    for fast lookups.

    Core operations:
        get_matchup_u35_score(home, away) -> int  (0-99)
        get_matchup_o15_score(home, away) -> int  (0-99)
        get_matchup_draw_score(home, away) -> int  (0-90)
        get_team_profile(team) -> dict
        get_team_report(team) -> str
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._profiles: dict[str, dict] = {}           # Flat all-time profiles
        self._weighted_profiles: dict[str, dict] = {}  # Recency-weighted profiles
        self._h2h_cache: dict[tuple[str, str], dict] = {}
        self._initialized = False
        self._init_error = None
        self._latest_season_int = 0   # Auto-detected from DB
        self._weighted_ok = False     # Whether weighted computation succeeded
        self._quota_analyst = WinQuotaAnalyst()
        self._fingerprinter = SeasonFingerprinter()
        self._seasonal_debt = 0.0 # Goal debt relative to 2.55 target
        # Attempt init; if DB is unavailable, we'll use defaults
        try:
            self._load_all_profiles()
            self._compute_weighted_profiles()
            self._initialized = True
            logger.info(
                f"Loaded flat profiles for {len(self._profiles)} teams, "
                f"weighted profiles for {len(self._weighted_profiles)} teams "
                f"from DB (latest season int: {self._latest_season_int})"
            )
        except Exception as e:
            self._init_error = str(e)
            logger.error(f"Failed to initialize DynamicTeamClassifier: {e}")

    def reload(self):
        """Reload profiles and clear H2H cache from database."""
        with self._lock:
            self._h2h_cache.clear()
            self._profiles.clear()
            self._weighted_profiles.clear()
            self._initialized = False
            self._weighted_ok = False
        try:
            self._load_all_profiles()
            self._compute_weighted_profiles()
            with self._lock:
                self._initialized = True
            logger.info("DynamicTeamClassifier successfully reloaded all profiles from DB")
        except Exception as e:
            logger.error(f"Failed to reload DynamicTeamClassifier: {e}")


    def _load_all_profiles(self):
        """Query results table and populate flat all-time profiles."""
        with get_db() as cur:
            cur.execute(
                """
                SELECT 
                    team,
                    COUNT(*) as n_matches,
                    ROUND(AVG(avg_goals_match)::numeric, 2) as avg_goals,
                    ROUND(AVG(scored)::numeric, 2) as avg_scored,
                    ROUND(AVG(conceded)::numeric, 2) as avg_conceded,
                    SUM(u35_count) * 100.0 / COUNT(*) as u35_rate,
                    SUM(o15_count) * 100.0 / COUNT(*) as o15_rate,
                    SUM(draw_count) * 100.0 / COUNT(*) as draw_rate
                FROM (
                    SELECT
                        home_team as team,
                        CAST(total_goals AS REAL) as avg_goals_match,
                        CAST(home_goals AS REAL) as scored,
                        CAST(away_goals AS REAL) as conceded,
                        CASE WHEN total_goals < 3.5 THEN 1 ELSE 0 END as u35_count,
                        CASE WHEN total_goals >= 1.5 THEN 1 ELSE 0 END as o15_count,
                        CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END as draw_count
                    FROM results
                    UNION ALL
                    SELECT
                        away_team as team,
                        CAST(total_goals AS REAL) as avg_goals_match,
                        CAST(away_goals AS REAL) as scored,
                        CAST(home_goals AS REAL) as conceded,
                        CASE WHEN total_goals < 3.5 THEN 1 ELSE 0 END as u35_count,
                        CASE WHEN total_goals >= 1.5 THEN 1 ELSE 0 END as o15_count,
                        CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END as draw_count
                    FROM results
                ) combined
                GROUP BY team
                ORDER BY team
                """
            )
            rows = cur.fetchall()
            for r in rows:
                team_name = _normalize_team(r["team"])
                prior = TEAM_STRENGTH_PRIORS.get(team_name, {})
                self._profiles[team_name] = {
                    "u35_rate": float(r["u35_rate"]),
                    "o15_rate": float(r["o15_rate"]),
                    "draw_rate": float(r["draw_rate"]),
                    "avg_goals": float(r["avg_goals"]),
                    "avg_scored": float(r["avg_scored"]),
                    "avg_conceded": float(r["avg_conceded"]),
                    "n_matches": int(r["n_matches"]),
                    "strength_class": prior.get("class", "balanced"),
                }

            # Ensure all known priors have entries even if DB missing them
            for team_name, prior in TEAM_STRENGTH_PRIORS.items():
                if team_name not in self._profiles:
                    self._profiles[team_name] = dict(DEFAULT_PROFILE)
                    self._profiles[team_name]["strength_class"] = prior.get("class", "balanced")

    def _get_current_win_streak(self, team: str, season_id: str) -> int:
        """Find the current consecutive win count for a team in the active season."""
        try:
            canon = _normalize_team(team)
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT home_team, away_team, home_goals, away_goals 
                    FROM results 
                    WHERE season_id = %s AND (home_team = %s OR away_team = %s)
                    ORDER BY match_day DESC
                    LIMIT 10
                    """,
                    (season_id, canon, canon)
                )
                matches = cur.fetchall()
                streak = 0
                for m in matches:
                    if m["home_team"] == canon:
                        if m["home_goals"] > m["away_goals"]: streak += 1
                        else: break
                    else:
                        if m["away_goals"] > m["home_goals"]: streak += 1
                        else: break
                return streak
        except Exception as e:
            logger.warning(f"Streak lookup failed for {team}: {e}")
            return 0

    def _load_engine_regime(self) -> dict:
        """Load regime adjustments from unified_intel.json."""
        intel_path = "/home/ubuntu/faith-workspace/vfl-complete-data/analysis/unified_intel.json"
        try:
            if os.path.exists(intel_path):
                with open(intel_path) as f:
                    intel = json.load(f)
                    return intel.get("engine_regime", {}).get("recommended_adjustments", {})
        except Exception:
            pass
        return {}

    def _compute_weighted_profiles(
        self,
        decay_rate: float = DEFAULT_DECAY_RATE,
        recent_mult: float = DEFAULT_RECENT_MULT,
        recent_window: int = DEFAULT_RECENT_WINDOW,
    ):
        """Compute recency-weighted profiles for every team using Postgres."""
        with get_db() as cur:
            cur.execute("SELECT MAX(season_id) FROM results")
            row = cur.fetchone()
            latest_id = row[0] if row else "vf:season:0"
            latest_int = _extract_season_int(latest_id)
            self._latest_season_int = latest_int

            for team in self._profiles.keys():
                cur.execute(
                    """
                    SELECT 
                        season_id, match_day, total_goals,
                        CASE WHEN home_team = %s THEN home_goals ELSE away_goals END as scored,
                        CASE WHEN home_team = %s THEN away_goals ELSE home_goals END as conceded
                    FROM results
                    WHERE home_team = %s OR away_team = %s
                    ORDER BY season_id DESC, match_day DESC
                    LIMIT 100
                    """,
                    (team, team, team, team)
                )
                matches = cur.fetchall()
                
                if not matches:
                    self._weighted_profiles[team] = self._profiles[team]
                    continue

                total_weight = 0.0
                w_u35 = 0.0
                w_o15 = 0.0
                w_draw = 0.0
                w_win = 0.0
                w_goals = 0.0
                w_scored = 0.0
                w_conceded = 0.0

                n = len(matches)
                for i, m in enumerate(reversed(matches)):
                    s_int = _extract_season_int(m["season_id"])
                    seasons_ago = (latest_int - s_int) / 30.0
                    season_weight = decay_rate ** max(0.0, seasons_ago)
                    day_boost = 1.0 + (m["match_day"] / 30.0) * recent_mult
                    is_recent = (i >= n - recent_window)
                    recent_boost = 2.0 if is_recent else 1.0

                    weight = season_weight * day_boost * recent_boost
                    total_weight += weight
                    
                    w_goals += m["total_goals"] * weight
                    w_scored += m["scored"] * weight
                    w_conceded += m["conceded"] * weight

                    if m["total_goals"] < 3.5: w_u35 += 1.0 * weight
                    if m["total_goals"] >= 1.5: w_o15 += 1.0 * weight
                    if m["scored"] == m["conceded"]: w_draw += 1.0 * weight
                    if m["scored"] > m["conceded"]: w_win += 1.0 * weight

                if total_weight > 0:
                    prior = TEAM_STRENGTH_PRIORS.get(team, {})
                    self._weighted_profiles[team] = {
                        "u35_rate": round(w_u35 / total_weight * 100, 1),
                        "o15_rate": round(w_o15 / total_weight * 100, 1),
                        "draw_rate": round(w_draw / total_weight * 100, 1),
                        "win_rate": round(w_win / total_weight * 100, 1),
                        "avg_goals": round(w_goals / total_weight, 2),
                        "avg_scored": round(w_scored / total_weight, 2),
                        "avg_conceded": round(w_conceded / total_weight, 2),
                        "n_matches": n,
                        "strength_class": prior.get("class", "balanced"),
                    }
        self._weighted_ok = True

    def _get_current_matchday(self, season_id: str) -> int:
        with get_db() as cur:
            cur.execute("SELECT MAX(match_day) FROM results WHERE season_id = %s", (season_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else 0

    def _get_team_wins(self, team: str, season_id: str) -> int:
        with get_db() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM results 
                WHERE season_id = %s AND 
                ((home_team = %s AND home_goals > away_goals) OR (away_team = %s AND away_goals > home_goals))
                """,
                (season_id, team, team)
            )
            row = cur.fetchone()
            return row[0] if row else 0

    def _get_h2h(self, team1: str, team2: str) -> dict:
        key = tuple(sorted([team1, team2]))
        if key in self._h2h_cache: return self._h2h_cache[key]
        
        with get_db() as cur:
            cur.execute(
                """
                SELECT total_goals, home_team, home_goals, away_goals FROM results
                WHERE (home_team = %s AND away_team = %s) OR (home_team = %s AND away_team = %s)
                ORDER BY captured_at DESC LIMIT 10
                """,
                (team1, team2, team2, team1)
            )
            rows = cur.fetchall()
            if not rows: return None
            
            n = len(rows)
            u35 = sum(1 for r in rows if r["total_goals"] < 3.5)
            draws = sum(1 for r in rows if r["home_goals"] == r["away_goals"])
            res = {"n": n, "u35_rate": u35/n*100, "draw_rate": draws/n*100}
            self._h2h_cache[key] = res
            return res


    def get_team_profile(self, team_name: str) -> dict:
        name = _normalize_team(team_name)
        return self._weighted_profiles.get(name, self._profiles.get(name, DEFAULT_PROFILE))


    def _get_seasonal_debt(self, season_id: str) -> float:
        """Calculate difference between current season avg and 2.55 target."""
        try:
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT AVG(r.home_goals + r.away_goals) 
                    FROM vfl_results_v2 r
                    JOIN vfl_matchdays m ON r.matchday_id = m.id
                    WHERE m.season_id = (SELECT id FROM vfl_seasons WHERE season_id = %s)
                    """,
                    (season_id,)
                )
                row = cur.fetchone()
                if row and row[0]:
                    current_avg = float(row[0])
                    return 2.55 - current_avg
                return 0.0
        except Exception:
            return 0.0

    def get_matchup_draw_score(self, home: str, away: str, season_id: str = None) -> int:
        return self.get_matchup_1x2_scores(home, away, season_id)["draw"]

    def get_team_report(self, team_name: str) -> str:
        p = self.get_team_profile(team_name)
        return f"Team: {team_name} | Class: {p['strength_class']} | U3.5: {p['u35_rate']}% | O1.5: {p['o15_rate']}% | Avg: {p['avg_goals']}"

    def _init_fallback_profiles(self):
        """Build profiles from priors only when DB is unavailable."""
        for team_name, prior in TEAM_STRENGTH_PRIORS.items():
            cls = prior.get("class", "balanced")
            # Set sensible defaults based on strength class
            if cls == "powerhouse":
                self._profiles[team_name] = {
                    "u35_rate": 68.0,
                    "o15_rate": 80.0,
                    "draw_rate": 34.0,
                    "avg_goals": 2.9,
                    "avg_scored": 1.6,
                    "avg_conceded": 1.2,
                    "n_matches": 0,
                    "strength_class": cls,
                }
            elif cls == "attacking":
                self._profiles[team_name] = {
                    "u35_rate": 72.0,
                    "o15_rate": 76.0,
                    "draw_rate": 37.0,
                    "avg_goals": 2.6,
                    "avg_scored": 1.4,
                    "avg_conceded": 1.2,
                    "n_matches": 0,
                    "strength_class": cls,
                }
            elif cls == "defensive":
                self._profiles[team_name] = {
                    "u35_rate": 82.0,
                    "o15_rate": 66.0,
                    "draw_rate": 41.0,
                    "avg_goals": 2.2,
                    "avg_scored": 1.1,
                    "avg_conceded": 1.1,
                    "n_matches": 0,
                    "strength_class": cls,
                }
            else:  # balanced
                self._profiles[team_name] = dict(DEFAULT_PROFILE)
                self._profiles[team_name]["strength_class"] = cls

    # ── Profile Properties ─────────────────────────────────────────────────────

    @property
    def all_time_profiles(self) -> dict[str, dict]:
        """Flat all-time average profiles (backward-compat access)."""
        return self._profiles

    @property
    def weighted_profiles(self) -> dict[str, dict]:
        """Recency-weighted profiles."""
        return self._weighted_profiles if self._weighted_ok else self._profiles

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_team_profile(self, team_name: str) -> dict:
        """
        Return the full profile for a team.

        Returns the recency-weighted profile when available, otherwise falls
        back to flat all-time, then to neutral defaults.

        Dict keys:
            u35_rate, o15_rate, draw_rate, avg_goals, avg_scored,
            avg_conceded, n_matches, strength_class
        """
        canon = _normalize_team(team_name)

        # Prefer weighted profiles when available
        if self._weighted_ok and canon in self._weighted_profiles:
            return self._weighted_profiles[canon]

        profile = self._profiles.get(canon)
        if profile is not None:
            return profile

        # Unknown team — return neutral fallback
        logger.warning(
            f"Unknown team '{team_name}' (canonical: '{canon}'), "
            f"returning neutral default"
        )
        return dict(DEFAULT_PROFILE)

    def get_matchup_u35_score(
        self, home: str, away: str, season_id: str = None
    ) -> int:
        """
        Compute Under 3.5 Goals confidence score (10-99).

        Methodology:
        1. Recency-weighted team identity base (from weighted_profiles)
        2. Prior strength adjustment from TEAM_STRENGTH_PRIORS
        3. H2H historical adjustment if available
        4. Current season form adjustment (50%) if season_id provided
        """
        home_p = self.get_team_profile(home)
        away_p = self.get_team_profile(away)

        # 1. Recency-weighted base
        base = (home_p["u35_rate"] + away_p["u35_rate"]) / 2.0

        # 2. Prior adjustment
        h_prior = TEAM_STRENGTH_PRIORS.get(_normalize_team(home), {})
        a_prior = TEAM_STRENGTH_PRIORS.get(_normalize_team(away), {})

        boost = (
            h_prior.get("u35_boost", 0)
            + a_prior.get("u35_boost", 0)
            + h_prior.get("u35_penalty", 0)
            + a_prior.get("u35_penalty", 0)
        )
        base += boost

        # 3. H2H adjustment (weighted by sample size)
        h2h = self._get_h2h(_normalize_team(home), _normalize_team(away))
        if h2h:
            # Strict H2H Scoreline Lock: if 100% of historical H2H matches ended Under 3.5 (min 5 matches)
            if h2h["n"] >= 5 and h2h.get("scorelines"):
                over_35_count = sum(count for score, count in h2h["scorelines"].items() if sum(map(int, score.split("-"))) > 3.5)
                if over_35_count == 0:
                    logger.info(f"H2H SCORELINE LOCK (U3.5): 100% of {h2h['n']} historical matches ended Under 3.5. Locking to 99%.")
                    return 99

            if h2h["n"] >= 10:
                # Dynamic weighting: more matches = more weight to H2H
                # 10 matches: ~0.3 weight, 100+ matches: up to 0.8 weight
                h2h_weight = min(0.8, 0.2 + (h2h["n"] / 100.0) * 0.6)
                base = base * (1.0 - h2h_weight) + h2h["u35_rate"] * h2h_weight
                
                # Scoreline-based H2H check: if matchup historically produces a lot of goals (O3.5)
                if h2h.get("scorelines"):
                    over_35_count = sum(count for score, count in h2h["scorelines"].items() if sum(map(int, score.split("-"))) > 3.5)
                    over_35_rate = over_35_count * 100.0 / h2h["n"]
                    if over_35_rate >= 35.0:
                        base -= 8
                        logger.info(f"H2H Scoreline Penalty (U3.5): {home} vs {away} has high O3.5 rate ({over_35_rate:.1f}%) -> -8 pts")

        # 4. Engine Regime Adjustment
        regime = self._load_engine_regime()
        base += regime.get("under_3_5_boost", 0) * 100 # Adjust scale

        # 5. Season form & Streak adjustment
        if season_id:
            season_u35, match_count = self._get_season_u35_rate(
                _normalize_team(home), _normalize_team(away), season_id
            )
            if season_u35 is not None and match_count > 0:
                z = match_count / (match_count + 10.0)
                base = base * (1.0 - z) + season_u35 * z
            
            # 6. Streak & Win Quota Logic
            match_day = self._get_current_matchday(season_id)
            if match_day and match_day >= 5:
                for team in [home, away]:
                    streak = self._get_current_win_streak(team, season_id)
                    is_powerhouse = TEAM_STRENGTH_PRIORS.get(_normalize_team(team), {}).get("class") == "powerhouse"
                    
                    # If powerhouse or attacking team is on a streak, penalize U3.5 significantly (expecting more goals)
                    team_cls = TEAM_STRENGTH_PRIORS.get(_normalize_team(team), {}).get("class", "balanced")
                    if team_cls in ("powerhouse", "attacking") and streak >= 3:
                        logger.info(f"Streak Momentum (U3.5): {team} on {streak} win streak. Suppressing regression and penalizing U3.5.")
                        base -= 12 # Penalize U3.5 (expecting more goals)
                    
                    if match_day >= 15:
                        wins = self._get_team_wins(team, season_id)
                        pressure = self._quota_analyst.calculate_win_pressure(team, wins, match_day)
                        
                        # Only apply regression boost to U3.5 if streak is broken or team is not powerhouse
                        if pressure < -0.3 and (not is_powerhouse or streak < 3):
                            adjustment = abs(pressure) * 10.0
                            base += adjustment
                            logger.info(f"Win Pressure Boost (U3.5): {team} pressure {pressure:.2f} -> +{adjustment:.1f}")

        # 7. Tier Differential Boost (U3.5)
        h_cls = home_p.get("strength_class", "balanced")
        a_cls = away_p.get("strength_class", "balanced")
        if h_cls == "defensive" and a_cls == "defensive":
            base += 10 # Two defensive teams = high U3.5
        elif h_cls == "defensive" or a_cls == "defensive":
            base += 4

        # 8. League Table Form Boost (League Table Method)
        if season_id:
            md = self._get_current_matchday(season_id)
            if md >= 3:
                for team in [home, away]:
                    form = self._get_team_form(team, season_id, md)
                    if form:
                        # WDL form logic
                        if form.count('L') >= 2: # Losing streak/struggling
                            base += 5 # Lean towards Under 3.5 (caution)
                        if form.count('W') >= 2: # Winning streak/momentum
                            base -= 3 # Lean away from Under 3.5 (aggressive)

                # 9. 2-2-4 Trap Detector (Starvation Cycle)
                for team in [home, away]:
                    last_totals = self._get_team_last_totals(team, season_id, md, n=3)
                    if last_totals and len(last_totals) >= 2:
                        if all(t < 2 for t in last_totals[:2]): # Two consecutive U1.5 games
                            base += 10
                            logger.info(f"Trap Boost (U3.5): {team} in starvation cycle -> +10 pts")

                # 10. Seasonal Entropy Correction
                debt = self._get_seasonal_debt(season_id)
                if debt < -0.2: # Season is over-scoring
                    base += 7
                    logger.info(f"Entropy Boost (U3.5): Season goal surplus {abs(debt):.2f} -> +7 pts")
                elif debt > 0.2: # Season is under-scoring
                    base -= 5
                    logger.info(f"Entropy Penalty (U3.5): Season goal debt {debt:.2f} -> -5 pts")

                # 11. Late-Season League Table Standing Pressure (Rank 1-4 vs Rank 15-16)
                if md >= 20:
                    r_home = self._get_team_rank(home, season_id, md)
                    r_away = self._get_team_rank(away, season_id, md)
                    if r_home and r_away:
                        is_top_vs_bottom = (
                            (r_home <= 4 and r_away >= 15) or (r_away <= 4 and r_home >= 15)
                        )
                        if is_top_vs_bottom:
                            base -= 10
                            logger.info(f"League Pressure Penalty (U3.5): Top vs Bottom matchup (ranks {r_home} vs {r_away}) in late season -> -10 pts")

        return _cap_score(base)

    def _get_team_last_totals(self, team: str, season_id: str, matchday: int, n: int = 3) -> List[int]:
        """Fetch last N total goals for a team in a season."""
        try:
            canon = _normalize_team(team)
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT (r.home_goals + r.away_goals) 
                    FROM vfl_results_v2 r
                    JOIN vfl_matchdays m ON r.matchday_id = m.id
                    WHERE m.season_id = (SELECT id FROM vfl_seasons WHERE season_id = %s)
                    AND m.matchday_number < %s
                    AND (r.home_team = %s OR r.away_team = %s)
                    ORDER BY m.matchday_number DESC LIMIT %s
                    """,
                    (season_id, matchday, canon, canon, n)
                )
                return [int(row[0]) for row in cur.fetchall()]
        except Exception as e:
            logger.warning(f"Failed to get last totals for {team}: {e}")
            return []

    def _get_team_wins(self, team: str, season_id: str) -> int:
        """Fetch current win count for a team in a season."""
        try:
            canon = _normalize_team(team)
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM results 
                    WHERE season_id = %s AND 
                    ((home_team = %s AND home_goals > away_goals) OR (away_team = %s AND away_goals > home_goals))
                    """,
                    (season_id, canon, canon)
                )
                row = cur.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.warning(f"Failed to get team wins: {e}")
            return 0

    def _get_team_form(self, team: str, season_id: str, matchday: int) -> Optional[str]:
        """Fetch form string (e.g. 'WWW', 'WDL') from league snapshots."""
        try:
            canon = _normalize_team(team)
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT form FROM vfl_league_snapshots ls
                    JOIN vfl_matchdays m ON ls.matchday_id = m.id
                    WHERE m.season_id = (SELECT id FROM vfl_seasons WHERE season_id = %s)
                    AND m.matchday_number = %s
                    AND ls.team_name = %s
                    """,
                    (season_id, matchday, canon)
                )
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.warning(f"Failed to get team form for {team}: {e}")
            return None

    def _get_team_rank(self, team: str, season_id: str, matchday: int) -> Optional[int]:
        """Fetch current rank from league snapshots."""
        try:
            canon = _normalize_team(team)
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT rank FROM vfl_league_snapshots ls
                    JOIN vfl_matchdays m ON ls.matchday_id = m.id
                    WHERE m.season_id = (SELECT id FROM vfl_seasons WHERE season_id = %s)
                    AND m.matchday_number = %s
                    AND ls.team_name = %s
                    """,
                    (season_id, matchday, canon)
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        except Exception as e:
            logger.warning(f"Failed to get team rank for {team}: {e}")
            return None


    def get_matchup_o15_score(
        self, home: str, away: str, season_id: str = None
    ) -> int:
        """
        Compute Over 1.5 Goals confidence score (10-99).

        Same methodology as u35 but for O1.5 market.
        """
        home_p = self.get_team_profile(home)
        away_p = self.get_team_profile(away)

        # 1. Recency-weighted base
        base = (home_p["o15_rate"] + away_p["o15_rate"]) / 2.0

        h_prior = TEAM_STRENGTH_PRIORS.get(_normalize_team(home), {})
        a_prior = TEAM_STRENGTH_PRIORS.get(_normalize_team(away), {})
        
        boost = h_prior.get("o15_home_boost", 0) + a_prior.get("o15_home_boost", 0)
        
        # Powerhouse Global Boost: Top teams are inherently high-scoring
        if h_prior.get("class") == "powerhouse": boost += 5
        if a_prior.get("class") == "powerhouse": boost += 3
        
        base += boost

        # 2.1 Tier Differential Boost (Always applies)
        h_cls = home_p.get("strength_class", "balanced")
        a_cls = away_p.get("strength_class", "balanced")
        if h_cls == "powerhouse" and a_cls != "powerhouse":
            base += 10 # Dominant powerhouse vs lower tier
        elif h_cls == "attacking" and a_cls in ["balanced", "defensive"]:
            base += 6
        elif a_cls == "powerhouse" and h_cls != "powerhouse":
            base += 5 # Away powerhouse still dominant

        # 3. H2H adjustment (weighted by powerhouse presence)
        h2h = self._get_h2h(_normalize_team(home), _normalize_team(away))
        if h2h and h2h["n"] >= 3:
            # Strict H2H Scoreline Lock: if 100% of historical H2H matches ended Over 1.5 (min 5 matches)
            if h2h["n"] >= 5 and h2h.get("scorelines"):
                under_15_count = sum(count for score, count in h2h["scorelines"].items() if sum(map(int, score.split("-"))) < 1.5)
                if under_15_count == 0:
                    logger.info(f"H2H SCORELINE LOCK (O1.5): 100% of {h2h['n']} historical matches ended Over 1.5. Locking to 99%.")
                    return 99

            # If a powerhouse is involved, H2H is less relevant than recent dominance
            h2h_weight = 0.1 if (h_cls == "powerhouse" or a_cls == "powerhouse") else 0.2
            base = base * (1.0 - h2h_weight) + h2h["o15_rate"] * h2h_weight
            
            # Scoreline-based H2H check: if matchup historically produces very few goals (U1.5)
            if h2h.get("scorelines"):
                under_15_count = sum(count for score, count in h2h["scorelines"].items() if sum(map(int, score.split("-"))) < 1.5)
                under_15_rate = under_15_count * 100.0 / h2h["n"]
                if under_15_rate >= 35.0:
                    base -= 8
                    logger.info(f"H2H Scoreline Penalty (O1.5): {home} vs {away} has high U1.5 rate ({under_15_rate:.1f}%) -> -8 pts")

        # 4. Engine Regime Adjustment
        regime = self._load_engine_regime()
        base += regime.get("over_1_5_boost", 0) * 100

        # 5. Season form & Streak adjustment
        if season_id:
            season_o15, match_count = self._get_season_o15_rate(
                _normalize_team(home), _normalize_team(away), season_id
            )
            if season_o15 is not None and match_count > 0:
                z = match_count / (match_count + 10.0)
                base = base * (1.0 - z) + season_o15 * z

            # 6. Streak Momentum & Win Quota Logic
            match_day = self._get_current_matchday(season_id)
            if match_day and match_day >= 3:
                for team in [home, away]:
                    streak = self._get_current_win_streak(team, season_id)
                    team_cls = TEAM_STRENGTH_PRIORS.get(_normalize_team(team), {}).get("class", "balanced")
                    
                    # Streak Momentum: Strong teams on streaks get a confidence boost for O1.5
                    if team_cls in ["powerhouse", "attacking"] and streak >= 3:
                        momentum_boost = min(15, streak * 3) # Increased from 10
                        
                        # Extra boost for "Big 6" favorites on a streak
                        if any(t in team for t in ["Manchester Blue", "Manchester Red", "London Guns", "Liverpool", "Chelsea", "Tottenham"]):
                            momentum_boost += 5
                            
                        base += momentum_boost
                        logger.info(f"Streak Momentum (O1.5): {team} on {streak} win streak -> +{momentum_boost} pts")

                    if match_day >= 15:
                        wins = self._get_team_wins(team, season_id)
                        pressure = self._quota_analyst.calculate_win_pressure(team, wins, match_day)
                        
                        # Only apply regression penalty if streak is not high
                        if pressure < -0.3 and streak < 4:
                            adjustment = abs(pressure) * 10
                            base -= adjustment
                            logger.info(f"Win Pressure Penalty (O1.5): {team} pressure {pressure:.2f} -> -{adjustment:.1f}")

                # 7. League Table Form Boost (League Table Method)
                for team in [home, away]:
                    form = self._get_team_form(team, season_id, match_day)
                    if form:
                        if form.count('W') >= 2: # Winning momentum
                            base += 8 # Boost O1.5
                        if form.count('L') >= 2: # Losing momentum
                            base -= 5 # Penalize O1.5

                # 8. Season Mimicry Boost (Mimic the Mirror Season Regime)
                try:
                    # Get current season name (e.g. VFLM 5146)
                    with get_db() as cur:
                        cur.execute("SELECT season_name FROM vfl_seasons WHERE season_id = %s", (season_id,))
                        row = cur.fetchone()
                        if row:
                            s_name = row['season_name']
                            # Look back 1 matchday to find the mirror
                            mirrors = self._fingerprinter.find_mirror_seasons(s_name, match_day - 1, top_n=1)
                            if mirrors:
                                top_mirror = mirrors[0]
                                guidance = self._fingerprinter.get_mirrored_predictions(top_mirror['id'], match_day)
                                if guidance:
                                    # Calculate O2.5 rate of the mirror MD
                                    o25_rate = sum(1 for g in guidance if g['total'] > 2.5) / 8.0
                                    if o25_rate >= 0.6: # Explosive regime
                                        base += 10
                                        logger.info(f"Mimicry Boost (O1.5): Mirror {top_mirror['season_name']} had high O2.5 rate ({o25_rate*100}%)")
                                    elif o25_rate <= 0.25: # Defensive regime
                                        base -= 15
                except Exception as e:
                    logger.warning(f"Mimicry Boost error: {e}")

                # 9. Seasonal Entropy Correction (PRNG Balancing)
                debt = self._get_seasonal_debt(season_id)
                if debt > 0.2: # Season is under-scoring significantly
                    base += 8
                    logger.info(f"Entropy Boost (O1.5): Season goal debt {debt:.2f} -> +8 pts")
                elif debt < -0.2: # Season is over-scoring
                    base -= 5
                    logger.info(f"Entropy Penalty (O1.5): Season goal surplus {abs(debt):.2f} -> -5 pts")

                # 10. Late-Season Goal Contraction (MD 22+)
                if match_day and match_day >= 22:
                    phi = 1.0 - 0.12 * (((match_day - 20) / 10.0) ** 2)
                    base = base * phi
                    logger.info(f"Late-Season Decay (O1.5): MD {match_day} -> multiplier {phi:.3f} (base: {base:.1f})")

        return _cap_score(base)

    def get_matchup_1x2_scores(
        self, home: str, away: str, season_id: str = None
    ) -> dict:
        """
        Compute H/D/A confidence scores (10-90) using:
        1. Fellenius tier-vs-tier baselines
        2. Recency-weighted team win/draw/loss rates
        3. Win Quota (pressure) adjustment
        """
        h_p = self.get_team_profile(home)
        a_p = self.get_team_profile(away)
        
        # 1. Tier Baseline
        h_cls = h_p.get("strength_class", "balanced")
        a_cls = a_p.get("strength_class", "balanced")
        
        # Simple tier mapping
        cls_to_tier = {"powerhouse": 1, "attacking": 2, "balanced": 3, "defensive": 4}
        ht = cls_to_tier.get(h_cls, 3)
        at = cls_to_tier.get(a_cls, 3)
        
        # Fellenius Tier Baselines (empirical H/D/A %)
        FELLENIUS = {
            (1, 1): (45, 25, 30), (1, 2): (58, 24, 18), (1, 3): (64, 18, 18), (1, 4): (77, 15, 8),
            (2, 1): (31, 29, 40), (2, 2): (47, 23, 30), (2, 3): (44, 26, 30), (2, 4): (62, 24, 14),
            (3, 1): (33, 29, 39), (3, 2): (44, 24, 32), (3, 3): (46, 24, 31), (3, 4): (61, 21, 17),
            (4, 1): (18, 19, 63), (4, 2): (25, 29, 46), (4, 3): (29, 27, 45), (4, 4): (45, 27, 28)
        }
        b_h, b_d, b_a = FELLENIUS.get((ht, at), (44, 25, 31))
        
        # 2. Recency-weighted rates
        # Home team win rate + Away team loss rate
        h_win_rate = h_p.get("win_rate", 44)
        a_win_rate = a_p.get("win_rate", 44)
        
        # Blend (60% Baseline, 40% Weighted Identity)
        p_h = b_h * 0.5 + h_win_rate * 0.5
        p_d = b_d * 0.5 + ((h_p.get("draw_rate", 25) + a_p.get("draw_rate", 25)) / 2) * 0.5
        p_a = b_a * 0.5 + a_win_rate * 0.5

        # 3. H2H Integration (if sufficient data)
        h2h = self._get_h2h(_normalize_team(home), _normalize_team(away))
        if h2h and h2h["n"] >= 3:
            # Determine winner from H2H scorelines
            if h2h.get("scorelines"):
                team1 = home if home < away else away
                is_home_team1 = (team1 == home)
                
                team1_wins = 0
                team2_wins = 0
                draws = 0
                for scoreline, count in h2h["scorelines"].items():
                    hg, ag = map(int, scoreline.split("-"))
                    if hg > ag:
                        team1_wins += count
                    elif hg < ag:
                        team2_wins += count
                    else:
                        draws += count
                
                h_wins = team1_wins if is_home_team1 else team2_wins
                a_wins = team2_wins if is_home_team1 else team1_wins
                
                total_h2h = team1_wins + team2_wins + draws
                if total_h2h > 0:
                    h2h_h = (h_wins / total_h2h) * 100
                    h2h_d = (draws / total_h2h) * 100
                    h2h_a = (a_wins / total_h2h) * 100
                    # Blend H2H (20% weight)
                    p_h = p_h * 0.8 + h2h_h * 0.2
                    p_d = p_d * 0.8 + h2h_d * 0.2
                    p_a = p_a * 0.8 + h2h_a * 0.2

        # 4. Engine Regime Bias
        regime = self._load_engine_regime()
        if regime:
            # High scoring regimes favor favorites (lower volatility)
            # Low scoring regimes favor draws/underdogs
            adj = regime.get("over_1_5_boost", 0)
            if adj > 0.05: # High scoring
                if ht < at: p_h += 5 # Favorite at home boosted
                elif at < ht: p_a += 5 # Favorite away boosted
            elif adj < -0.05: # Low scoring
                p_d += 8 # Draw more likely
        
        # 5. Win Quota Pressure Adjustment
        if season_id:
            md = self._get_current_matchday(season_id)
            if md >= 10:
                h_wins = self._get_team_wins(home, season_id)
                a_wins = self._get_team_wins(away, season_id)
                h_pressure = self._quota_analyst.calculate_win_pressure(home, h_wins, md)
                a_pressure = self._quota_analyst.calculate_win_pressure(away, a_wins, md)
                
                # Positive pressure = due for win, Negative = due for regression
                p_h += h_pressure * 15
                p_a += a_pressure * 15
                
        # Normalize
        total = p_h + p_d + p_a
        return {
            "home": max(5, min(95, round(p_h / total * 100))),
            "draw": max(5, min(95, round(p_d / total * 100))),
            "away": max(5, min(95, round(p_a / total * 100)))
        }

    def get_matchup_draw_score(
        self, home: str, away: str, season_id: str = None
    ) -> int:
        scores = self.get_matchup_1x2_scores(home, away, season_id)
        return scores["draw"]

    def get_team_report(self, team_name: str) -> str:
        """Return a human-readable summary of a team's profile."""
        canon = _normalize_team(team_name)
        p = self.get_team_profile(canon)
        prior = TEAM_STRENGTH_PRIORS.get(canon, {})
        cls_label = prior.get("class", p["strength_class"])

        profile_type = "recency-weighted" if self._weighted_ok else "all-time flat"

        lines = [
            f"📊 Team Report: {canon}",
            f"   Class: {cls_label}",
            f"   Profile type: {profile_type}",
            f"   All-time matches: {p['n_matches']}",
            f"   Avg goals: {p['avg_goals']}",
            f"   Avg scored: {p['avg_scored']}  |  Avg conceded: {p['avg_conceded']}",
            f"   U3.5 rate: {p['u35_rate']}%",
            f"   O1.5 rate: {p['o15_rate']}%",
            f"   Draw rate: {p['draw_rate']}%",
        ]

        # Add flat-vs-weighted comparison if both available
        if self._weighted_ok and canon in self._profiles and canon in self._weighted_profiles:
            flat = self._profiles[canon]
            weighted = self._weighted_profiles[canon]
            lines.append(
                f"   📈 Flat vs Weighted — "
                f"U3.5: {flat['u35_rate']}%→{weighted['u35_rate']}% "
                f"O1.5: {flat['o15_rate']}%→{weighted['o15_rate']}% "
                f"AvgGls: {flat['avg_goals']}→{weighted['avg_goals']}"
            )

        return "\n".join(lines)

    # ── H2H Cache ──────────────────────────────────────────────────────────────

    def _get_h2h(self, team1: str, team2: str) -> dict | None:
        """Get cached or compute H2H stats between two teams."""
        if not self._initialized:
            return None
        key = (team1, team2) if team1 < team2 else (team2, team1)
        with self._lock:
            if key in self._h2h_cache:
                return self._h2h_cache[key]

        # Compute from DB
        try:
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT home_team, away_team, home_goals, away_goals, total_goals
                    FROM results
                    WHERE (home_team = %s AND away_team = %s)
                       OR (home_team = %s AND away_team = %s)
                    """,
                    (team1, team2, team2, team1),
                )
                rows = cur.fetchall()
                if rows:
                    n = len(rows)
                    avg_total = sum(r["total_goals"] for r in rows) / n
                    u35_count = sum(1 for r in rows if r["total_goals"] < 3.5)
                    o15_count = sum(1 for r in rows if r["total_goals"] >= 1.5)
                    draw_count = sum(1 for r in rows if r["home_goals"] == r["away_goals"])
                    
                    scorelines = defaultdict(int)
                    for r in rows:
                        # Normalize scoreline: team1 goals first, team2 goals second
                        if _normalize_team(r["home_team"]) == team1:
                            skey = f"{r['home_goals']}-{r['away_goals']}"
                        else:
                            skey = f"{r['away_goals']}-{r['home_goals']}"
                        scorelines[skey] += 1
                        
                    result = {
                        "n": n,
                        "avg_total": round(avg_total, 2),
                        "u35_rate": u35_count * 100.0 / n,
                        "o15_rate": o15_count * 100.0 / n,
                        "draw_rate": draw_count * 100.0 / n,
                        "scorelines": dict(scorelines),
                    }
                else:
                    result = None
        except Exception as e:
            logger.warning(f"H2H lookup failed: {e}")
            result = None

        with self._lock:
            self._h2h_cache[key] = result
        return result

    # ── Season Form Queries ────────────────────────────────────────────────────

    def _get_season_u35_rate(
        self, home: str, away: str, season_id: str
    ) -> tuple[float | None, int]:
        """Compute blended U3.5 rate and match count for both teams in current season."""
        if not self._initialized:
            return None, 0
        try:
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT
                        SUM(CASE WHEN total_goals < 3.5 THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as u35_rate,
                        COUNT(*) as match_count
                    FROM results
                    WHERE season_id = %s
                      AND (home_team = %s OR away_team = %s
                           OR home_team = %s OR away_team = %s)
                    """,
                    (season_id, home, home, away, away),
                )
                row = cur.fetchone()
                if row and row["u35_rate"] is not None:
                    return float(row["u35_rate"]), int(row["match_count"])
                return None, 0
        except Exception as e:
            logger.warning(f"Season U3.5 lookup failed: {e}")
            return None, 0

    def _get_season_o15_rate(
        self, home: str, away: str, season_id: str
    ) -> tuple[float | None, int]:
        """Compute blended O1.5 rate and match count for both teams in current season."""
        if not self._initialized:
            return None, 0
        try:
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT
                        SUM(CASE WHEN total_goals >= 1.5 THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as o15_rate,
                        COUNT(*) as match_count
                    FROM results
                    WHERE season_id = %s
                      AND (home_team = %s OR away_team = %s
                           OR home_team = %s OR away_team = %s)
                    """,
                    (season_id, home, home, away, away),
                )
                row = cur.fetchone()
                if row and row["o15_rate"] is not None:
                    return float(row["o15_rate"]), int(row["match_count"])
                return None, 0
        except Exception as e:
            logger.warning(f"Season O1.5 lookup failed: {e}")
            return None, 0

    def _get_season_draw_rate(
        self, home: str, away: str, season_id: str
    ) -> float | None:
        """Compute blended draw rate for both teams in current season."""
        if not self._initialized:
            return None
        try:
            with get_db() as cur:
                cur.execute(
                    """
                    SELECT
                        SUM(CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as draw_rate
                    FROM results
                    WHERE season_id = %s
                      AND (home_team = %s OR away_team = %s
                           OR home_team = %s OR away_team = %s)
                    """,
                    (season_id, home, home, away, away),
                )
                row = cur.fetchone()
                if row and row["draw_rate"] is not None:
                    return float(row["draw_rate"])
                return None
        except Exception as e:
            logger.warning(f"Season draw lookup failed: {e}")
            return None


# ── Module-level singleton for FastAPI integration ─────────────────────────────
_classifier: DynamicTeamClassifier | None = None
_classifier_lock = threading.Lock()


def get_classifier() -> DynamicTeamClassifier:
    """Lazy-init singleton for thread-safe reuse."""
    global _classifier
    if _classifier is None:
        with _classifier_lock:
            if _classifier is None:
                _classifier = DynamicTeamClassifier()
    return _classifier


# ── Convenience functions (same signature as static Oracle) ────────────────────

def oracle_u35(home: str, away: str, season_id: str = None) -> tuple:
    """
    Compute Under 3.5 Goals confidence and expected value multiplier.
    Returns (score, ev_mult) where score is 10-99.
    """
    cls = get_classifier()
    score = cls.get_matchup_u35_score(home, away, season_id)
    prob = score / 100.0
    ev_mult = 1.0 / prob if prob > 0 else 1.0
    return score, round(ev_mult, 4)


def oracle_o15(home: str, away: str, season_id: str = None) -> tuple:
    """
    Compute Over 1.5 Goals confidence and expected value multiplier.
    Returns (score, ev_mult) where score is 10-99.
    """
    cls = get_classifier()
    score = cls.get_matchup_o15_score(home, away, season_id)
    prob = score / 100.0
    ev_mult = 1.0 / prob if prob > 0 else 1.0
    return score, round(ev_mult, 4)


def oracle_draw(home: str, away: str, season_id: str = None) -> tuple:
    """
    Compute Draw confidence and expected value multiplier.
    Returns (score, ev_mult) where score is 10-90.
    """
    cls = get_classifier()
    score = cls.get_matchup_draw_score(home, away, season_id)
    prob = score / 100.0
    ev_mult = 1.0 / prob if prob > 0 else 1.0
    return score, round(ev_mult, 4)


# ── Main (self-test) ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s %(message)s",
    )

    print("=" * 65)
    print("  Dynamic Team Classifier — Self Test (v2 with Recency Weighting)")
    print("=" * 65)

    c = DynamicTeamClassifier()

    print(f"\n{'Team':<22} {'Class':<14} {'Matches':>8} {'AvgGls':>6} "
          f"{'U3.5%':>6} {'O1.5%':>6} {'Draw%':>6}")
    print("-" * 70)
    for team in sorted(c._profiles.keys()):
        p = c._profiles[team]
        print(f"{team:<22} {p['strength_class']:<14} {p['n_matches']:>8} "
              f"{p['avg_goals']:>6} {p['u35_rate']:>6} {p['o15_rate']:>6} "
              f"{p['draw_rate']:>6}")

    # Show recency-weighted comparison for Manchester Blue
    print(f"\n── Recency-Weighted Comparison for Manchester Blue ──")
    if c._weighted_ok:
        flat = c._profiles.get("Manchester Blue", {})
        w = c._weighted_profiles.get("Manchester Blue", {})
        print(f"  Flat (all-time):   U3.5={flat.get('u35_rate','?'):>6}%  "
              f"O1.5={flat.get('o15_rate','?'):>6}%  "
              f"Avg={flat.get('avg_goals','?'):>5}")
        print(f"  Weighted (recent):  U3.5={w.get('u35_rate','?'):>6}%  "
              f"O1.5={w.get('o15_rate','?'):>6}%  "
              f"Avg={w.get('avg_goals','?'):>5}")

    # Test known matchups
    matchups = [
        ("Manchester Blue", "Leeds"),
        ("Liverpool", "Everton"),
        ("Chelsea", "Fulham"),
        ("Manchester Red", "Manchester Blue"),
        ("Tottenham", "Crystal Palace"),
        ("Everton", "Leeds"),
    ]

    print(f"\n{'Home':<20} {'Away':<20} {'U3.5':>6} {'O1.5':>6} {'Draw':>6}")
    print("-" * 60)
    for home, away in matchups:
        u35 = c.get_matchup_u35_score(home, away)
        o15 = c.get_matchup_o15_score(home, away)
        drw = c.get_matchup_draw_score(home, away)
        print(f"{home:<20} {away:<20} {u35:>6} {o15:>6} {drw:>6}")

    # Team report sample
    print("\n" + c.get_team_report("Manchester Blue"))
    print()
    print(c.get_team_report("Everton"))

    # Verify bounds
    print("\n✓ Bounds check: all scores ∈ [10, 99]")
    all_ok = True
    for home, away in matchups:
        for fn in [c.get_matchup_u35_score, c.get_matchup_o15_score]:
            s = fn(home, away)
            if not (10 <= s <= 99):
                print(f"  ✗ {fn.__name__}({home}, {away}) = {s}  OUT OF BOUNDS")
                all_ok = False
        s = c.get_matchup_draw_score(home, away)
        if not (10 <= s <= 90):
            print(f"  ✗ get_matchup_draw_score({home}, {away}) = {s}  OUT OF BOUNDS")
            all_ok = False
    if all_ok:
        print("  ✓ All scores within valid bounds")

    print("\nDone.")
