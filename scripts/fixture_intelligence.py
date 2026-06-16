#!/usr/bin/env python3
"""
VFL Fixture Intelligence Engine
================================
Production-quality system that determines the correct market for each VFL fixture
by fusing three signal layers: all-time team profiles (L1), H2H history (L2),
and recent form (L3). Cross-validates against deep market odds when available.

Author: VFL Engineering Team
Version: 1.0.0
"""

from typing import Optional, Dict, Any, List, Tuple

# Add path for common tools
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db

# ──────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────

TEAMS = frozenset({
    "Aston Villa", "Bournemouth", "Brighton", "Chelsea", "Crystal Palace",
    "Everton", "Fulham", "Leeds", "Liverpool", "London Guns",
    "Manchester Blue", "Manchester Red", "Newcastle", "Tottenham",
    "West Ham", "Wolverhampton",
})

# Pre-computed per-team profiles from 19,033 historical matches (status=3)
# Format: {team: {avg_goals, o1_5_pct, u3_5_pct}}
TEAM_PROFILES = {
    # Defensive tier
    "Leeds":          {"avg_goals": 2.15, "o1_5_pct": 64.2, "u3_5_pct": 82.0, "tier": "defensive"},
    "Everton":        {"avg_goals": 2.16, "o1_5_pct": 64.7, "u3_5_pct": 83.6, "tier": "defensive"},
    "Fulham":         {"avg_goals": 2.30, "o1_5_pct": 68.2, "u3_5_pct": 81.3, "tier": "defensive"},
    # Balanced tier
    "Aston Villa":    {"avg_goals": 2.45, "o1_5_pct": 72.0, "u3_5_pct": 76.7, "tier": "balanced"},
    "Bournemouth":    {"avg_goals": 2.48, "o1_5_pct": 71.6, "u3_5_pct": 75.0, "tier": "balanced"},
    "Brighton":       {"avg_goals": 2.51, "o1_5_pct": 73.3, "u3_5_pct": 75.0, "tier": "balanced"},
    "Newcastle":      {"avg_goals": 2.54, "o1_5_pct": 73.4, "u3_5_pct": 75.3, "tier": "balanced"},
    "Crystal Palace": {"avg_goals": 2.69, "o1_5_pct": 75.0, "u3_5_pct": 70.7, "tier": "balanced"},
    # Attacking tier
    "Tottenham":      {"avg_goals": 2.61, "o1_5_pct": 75.0, "u3_5_pct": 73.3, "tier": "attacking"},
    "Manchester Red": {"avg_goals": 2.61, "o1_5_pct": 74.5, "u3_5_pct": 73.1, "tier": "attacking"},
    "Liverpool":      {"avg_goals": 2.68, "o1_5_pct": 76.4, "u3_5_pct": 72.0, "tier": "attacking"},
    "West Ham":       {"avg_goals": 2.78, "o1_5_pct": 77.5, "u3_5_pct": 68.8, "tier": "attacking"},
    # Powerhouse tier
    "London Guns":    {"avg_goals": 2.80, "o1_5_pct": 77.9, "u3_5_pct": 68.7, "tier": "powerhouse"},
    "Chelsea":        {"avg_goals": 2.86, "o1_5_pct": 79.3, "u3_5_pct": 67.5, "tier": "powerhouse"},
    "Wolverhampton":  {"avg_goals": 2.87, "o1_5_pct": 78.2, "u3_5_pct": 66.8, "tier": "powerhouse"},
    "Manchester Blue":{"avg_goals": 2.98, "o1_5_pct": 81.8, "u3_5_pct": 65.2, "tier": "powerhouse"},
}

TIER_ADJUSTMENTS = {
    # (home_tier, away_tier) -> adjustment_factor
    ("defensive", "defensive"):       -0.35,
    ("defensive", "balanced"):        -0.15,
    ("balanced",  "balanced"):         0.00,
    ("attacking", "defensive"):        0.00,
    ("balanced",  "defensive"):       -0.10,
    ("attacking", "attacking"):        0.20,
    ("attacking", "balanced"):         0.10,
    ("powerhouse", "defensive"):       0.15,
    ("powerhouse", "balanced"):        0.20,
    ("powerhouse", "attacking"):       0.25,
    ("powerhouse", "powerhouse"):      0.30,
    ("balanced",  "attacking"):        0.10,
    ("balanced",  "powerhouse"):       0.15,
    ("defensive", "attacking"):        0.05,
    ("defensive", "powerhouse"):       0.10,
    ("attacking", "powerhouse"):       0.25,
}

# Default for any missing tier combos
DEFAULT_TIER_ADJUSTMENT = 0.0

# Weights for the three signal layers
L1_WEIGHT = 0.70
L2_WEIGHT = 0.20
L3_WEIGHT = 0.10

# Decision thresholds
OVER_1_5_THRESHOLD = 1.6

# ──────────────────────────────────────────────────────────────────────
# DATABASE HELPERS
# ──────────────────────────────────────────────────────────────────────

def get_results_cur():
    """Returns a DictCursor for the Postgres database."""
    return get_db()

# Goal distribution from 19,033 matches (used for Poisson-free probability estimates)
GOAL_DISTRIBUTION = {
    0: 0.074,
    1: 0.187,
    2: 0.254,
    3: 0.220,
    4: 0.144,
    5: 0.078,
    6: 0.036,
    7: 0.008,
}

# ──────────────────────────────────────────────────────────────────────
# MAIN ENGINE CLASS
# ──────────────────────────────────────────────────────────────────────


class FixtureIntelligenceEngine:
    """
    VFL Fixture Intelligence Engine.

    Fuses three signal layers to predict expected goals and recommend the
    optimal market for any fixture.

    Usage:
        engine = FixtureIntelligenceEngine()
        result = engine.analyze_fixture("Everton", "Leeds")
        print(result)
    """

    def __init__(
        self,
        results_db_path: str = "",
        odds_db_path: str = "",
    ):
        """
        Initialize the engine with database paths.

        Args:
            results_db_path: Path to vfl_results.db. If empty, auto-resolves.
            odds_db_path: Path to vfl_odds.db. If empty, auto-resolves.
        """
        self.results_db_path = self._resolve_db_path(results_db_path, "vfl_results.db")
        self.odds_db_path = self._resolve_db_path(odds_db_path, "vfl_odds.db")
        self._results_conn: Optional[sqlite3.Connection] = None
        self._odds_conn: Optional[sqlite3.Connection] = None
        self._team_profiles: Dict[str, Dict[str, Any]] = TEAM_PROFILES
        # Check if odds DB has usable data for cross-validation
        self._odds_path_usable = bool(self.odds_db_path and os.path.isfile(self.odds_db_path))

    # ── Database connection management ──────────────────────────────

    @staticmethod
    def _resolve_db_path(provided: str, db_name: str) -> str:
        """Resolve a database path from provided value or discover it."""
        if provided and os.path.isfile(provided):
            return provided

        # Search likely locations
        candidates = [
            provided if provided else "",
            os.path.expanduser(f"~/{db_name}"),
            os.path.expanduser(f"~/faith-workspace/vfl-complete-data/databases/{db_name}"),
            os.path.expanduser(f"~/faith-workspace/vfl-empire/{db_name}"),
            os.path.expanduser(f"~/faith-workspace/vfl-empire/databases/{db_name}"),
            os.path.expanduser(f"~/faith-workspace/vfl-empire/dbs/{db_name}"),
            f"/home/ubuntu/faith-workspace/vfl-complete-data/databases/{db_name}",
        ]

        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate

        # Last resort: try current directory
        if os.path.isfile(db_name):
            return db_name

        raise FileNotFoundError(
            f"Cannot locate {db_name}. Tried: {', '.join(c for c in candidates if c)}"
        )

    def _get_results_conn(self) -> sqlite3.Connection:
        """Get or create a cached connection to vfl_results.db."""
        if self._results_conn is None:
            self._results_conn = sqlite3.connect(self.results_db_path)
            self._results_conn.row_factory = sqlite3.Row
        return self._results_conn

    def _get_odds_conn(self) -> sqlite3.Connection:
        """Get or create a cached connection to vfl_odds.db."""
        if self._odds_conn is None:
            self._odds_conn = sqlite3.connect(self.odds_db_path)
            self._odds_conn.row_factory = sqlite3.Row
        return self._odds_conn

    def close(self):
        """Close all database connections."""
        if self._results_conn:
            self._results_conn.close()
            self._results_conn = None
        if self._odds_conn:
            self._odds_conn.close()
            self._odds_conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── Team validation ─────────────────────────────────────────────

    @staticmethod
    def validate_team(team_name: str) -> str:
        """
        Validate and normalize a team name.

        Args:
            team_name: Team name to validate.

        Returns:
            Normalized team name.

        Raises:
            ValueError: If the team is not in VFL.
        """
        normalized = team_name.strip()
        if normalized not in TEAMS:
            # Try fuzzy matching
            matches = [t for t in TEAMS if normalized.lower() in t.lower()]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ValueError(
                    f"Ambiguous team '{team_name}'. Did you mean one of: {matches}?"
                )
            raise ValueError(
                f"Unknown team '{team_name}'. Valid teams: {sorted(TEAMS)}"
            )
        return normalized

    # ── Layer 1: All-time team profiles ────────────────────────────

    def _compute_l1(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Layer 1: Compute expected goals from all-time team profiles.

        Blends home and away team averages, then applies a tier-based
        adjustment (e.g., defensive+defensive = strong downward adjustment).

        Returns:
            dict with 'expected_goals', 'home_profile', 'away_profile', 'tier_adjustment'
        """
        home_profile = TEAM_PROFILES.get(home_team, {"avg_goals": 2.59, "tier": "balanced"})
        away_profile = TEAM_PROFILES.get(away_team, {"avg_goals": 2.59, "tier": "balanced"})

        # Base blend: average of the two team averages
        base = (home_profile["avg_goals"] + away_profile["avg_goals"]) / 2.0

        # Tier adjustment
        home_tier = home_profile.get("tier", "balanced")
        away_tier = away_profile.get("tier", "balanced")
        tier_adj = TIER_ADJUSTMENTS.get(
            (home_tier, away_tier), DEFAULT_TIER_ADJUSTMENT
        )

        # Home advantage: small boost (~0.08 goals) for home team
        home_advantage = 0.08

        expected = base + tier_adj + home_advantage
        expected = max(0.5, min(expected, 5.0))  # clamp reasonable range

        return {
            "expected_goals": round(expected, 4),
            "base_blend": round(base, 4),
            "home_profile": home_profile,
            "away_profile": away_profile,
            "tier_adjustment": round(tier_adj, 4),
            "home_advantage": home_advantage,
        }

    # ── Layer 2: H2H history ───────────────────────────────────────

    def _compute_l2(self, home_team: str, away_team: str) -> Dict[str, Any]:
        """
        Layer 2: Compute expected goals from H2H history.

        Queries vfl_results.db for all completed matches between these two teams.

        Returns:
            dict with 'expected_goals', 'n_matches', 'confidence', 'avg_total_goals',
                  'o1_5_rate', 'zero_zero_rate'
        """
        try:
            with get_db() as cursor:
                cursor.execute("""
                    SELECT AVG(total_goals) as avg_total,
                           SUM(CASE WHEN total_goals > 1.5 THEN 1 ELSE 0 END) * 100.0 / GREATEST(COUNT(*), 1) as o1_5_pct,
                           SUM(CASE WHEN total_goals <= 3 THEN 1 ELSE 0 END) * 100.0 / GREATEST(COUNT(*), 1) as u3_5_pct,
                           COUNT(*) as n
                    FROM vfl_results_v2
                    WHERE (home_team = %s AND away_team = %s)
                       OR (home_team = %s AND away_team = %s)
                """, (home_team, away_team, away_team, home_team))
                row = cursor.fetchone()
                if row and row['n'] >= 5:
                    return {
                        "expected_goals": round(float(row['avg_total']), 4),
                        "n_matches": int(row['n']),
                        "confidence": 1.0 if row['n'] >= 20 else 0.7,
                        "avg_total_goals": round(float(row['avg_total']), 4),
                        "o1_5_rate": round(float(row['o1_5_pct']), 1),
                        "under_3_5_rate": round(float(row['u3_5_pct']), 1),
                        "zero_zero_rate": 0.0,
                    }
        except Exception as e:
            return {"expected_goals": None, "n_matches": 0, "confidence": 0.0}

        return {
            "expected_goals": None,
            "n_matches": 0,
            "confidence": 0.0,
            "avg_total_goals": None,
            "o1_5_rate": None,
            "zero_zero_rate": None,
        }

    # ── Layer 3: Recent form ───────────────────────────────────────

    def _compute_l3(self, home_team: str, away_team: str, window: int = 5) -> Dict[str, Any]:
        """
        Layer 3: Compute expected goals from recent form.

        Queries the last N matches for each team (cross-season, most recent first)
        and computes average goals scored/conceded.

        Args:
            home_team: Home team name
            away_team: Away team name
            window: Number of recent matches to consider (default: 5)

        Returns:
            dict with 'expected_goals', 'n_home', 'n_away', details
        """
        try:
            with get_db() as cursor:
                cursor.execute("""
                    SELECT total_goals
                    FROM vfl_results_v2
                    WHERE home_team = %s OR away_team = %s
                    ORDER BY id DESC
                    LIMIT 5
                """, (home_team, home_team))
                home_rows = cursor.fetchall()
                cursor.execute("""
                    SELECT total_goals
                    FROM vfl_results_v2
                    WHERE home_team = %s OR away_team = %s
                    ORDER BY id DESC
                    LIMIT 5
                """, (away_team, away_team))
                away_rows = cursor.fetchall()
                
            if len(home_rows) >= 3 and len(away_rows) >= 3:
                goals = [r[0] for r in home_rows + away_rows]
                expected = sum(goals) / len(goals)
                return {
                    "expected_goals": round(expected, 4),
                    "n_home": len(home_rows),
                    "n_away": len(away_rows),
                    "confidence": 0.8,
                }
        except Exception as e:
            pass
        return {
            "expected_goals": None,
            "n_home": 0,
            "n_away": 0,
            "confidence": 0.0,
        }

    @staticmethod
    def _get_recent_form(
        conn: sqlite3.Connection, team: str, window: int = 5
    ) -> Dict[str, Any]:
        """
        Get recent form data for a team.

        Returns dict with goals for/against averages from the team's last N matches.
        """
        cursor = conn.execute(
            """
            SELECT
                home_team, away_team, home_goals, away_goals, total_goals,
                CASE WHEN home_team = ? THEN home_goals ELSE away_goals END as gf,
                CASE WHEN home_team = ? THEN away_goals ELSE home_goals END as ga,
                CASE WHEN home_team = ? THEN 1 ELSE 0 END as is_home
            FROM results
            WHERE status = 3
              AND (home_team = ? OR away_team = ?)
            ORDER BY captured_at DESC, event_id DESC
            LIMIT ?
            """,
            (team, team, team, team, team, window),
        )

        matches = cursor.fetchall()
        if not matches:
            return {"n": 0, "gf_avg": 0.0, "ga_avg": 0.0, "matches": []}

        total_gf = sum(m["gf"] for m in matches)
        total_ga = sum(m["ga"] for m in matches)
        n = len(matches)

        match_list = []
        for m in matches:
            match_list.append({
                "opponent": m["away_team"] if m["is_home"] else m["home_team"],
                "is_home": bool(m["is_home"]),
                "gf": m["gf"],
                "ga": m["ga"],
                "total_goals": m["total_goals"],
            })

        return {
            "n": n,
            "gf_avg": round(total_gf / n, 4),
            "ga_avg": round(total_ga / n, 4),
            "matches": match_list,
        }

    # ── Deep market cross-validation ───────────────────────────────

    def _cross_validate(
        self, home_team: str, away_team: str, blended_expected: float
    ) -> Dict[str, Any]:
        """
        Cross-validate the expected goals estimate against deep market odds.

        Queries vfl_odds.db for:
        - Correct Score odds (0-0 short → low-scoring confirmation)
        - Exact Goals odds (peak at 0/1 → low-scoring)
        - GG/NG odds (NG favored → low-scoring)
        - Over/Under odds

        Returns:
            dict with market_agreement, adjusted_confidence, signals
        """
        results = {
            "market_data_found": False,
            "agreement_level": "unknown",
            "adjustment": 0,
            "signals": [],
            "details": {},
        }

        conn = self._get_odds_conn()

        # Find the most recent event_id for this fixture
        event_id = self._find_latest_event_id(conn, home_team, away_team)
        if not event_id:
            return results

        results["market_data_found"] = True
        results["details"]["event_id"] = event_id

        try:
            # 1. Check Correct Score market - specifically 0:0 odds
            cs_odds = self._get_market_odds(
                conn, event_id, "Correct Score", "0:0"
            )
            if cs_odds:
                results["details"]["correct_score_00_odds"] = cs_odds
                if cs_odds < 10.0:
                    results["signals"].append(
                        f"0-0 CS odds @ {cs_odds:.2f} — very short, confirms low-scoring outlook"
                    )
                    results["adjustment"] -= 5
                elif cs_odds < 15.0:
                    results["signals"].append(
                        f"0-0 CS odds @ {cs_odds:.2f} — moderately short"
                    )
                    results["adjustment"] -= 2
                elif cs_odds > 30.0:
                    results["signals"].append(
                        f"0-0 CS odds @ {cs_odds:.2f} — very long, aligns with high-scoring"
                    )
                    results["adjustment"] += 3

            # 2. Check Exact Goals distribution
            exact_goals = self._get_exact_goals_odds(conn, event_id)
            if exact_goals:
                results["details"]["exact_goals"] = exact_goals
                # Find the lowest odds (most likely outcome) - keys are strings like "0", "1", "2"
                min_goal_str = min(exact_goals, key=lambda k: exact_goals[k])
                # Parse numeric goal count; "6+" treated as 6
                try:
                    min_goal = int(min_goal_str.replace('+', ''))
                except ValueError:
                    min_goal = 99
                if min_goal <= 1:
                    results["signals"].append(
                        f"Exact Goals peak at {min_goal_str}g (odds {exact_goals[min_goal_str]:.2f}) — low-scoring"
                    )
                    results["adjustment"] -= 3
                elif min_goal >= 3:
                    results["signals"].append(
                        f"Exact Goals peak at {min_goal}g — high-scoring"
                    )
                    results["adjustment"] += 3

            # 3. Check GG/NG market
            gg_odds = self._get_market_odds(conn, event_id, "GG/NG", "Yes")
            ng_odds = self._get_market_odds(conn, event_id, "GG/NG", "No")
            if gg_odds and ng_odds:
                results["details"]["gg_odds"] = gg_odds
                results["details"]["ng_odds"] = ng_odds
                if ng_odds < gg_odds:
                    results["signals"].append(
                        f"NG favored ({ng_odds:.2f} vs GG {gg_odds:.2f}) — low-scoring alignment"
                    )
                    results["adjustment"] -= 3
                elif gg_odds < ng_odds:
                    results["signals"].append(
                        f"GG favored ({gg_odds:.2f} vs NG {ng_odds:.2f}) — high-scoring alignment"
                    )
                    results["adjustment"] += 2

            # 4. Check Over/Under 2.5 market
            over25 = self._get_market_odds(
                conn, event_id, "Over/Under", "Over 2.5", specifiers="total=2.5"
            )
            under25 = self._get_market_odds(
                conn, event_id, "Over/Under", "Under 2.5", specifiers="total=2.5"
            )
            if over25 and under25:
                results["details"]["ou_2_5"] = {"over": over25, "under": under25}
                implied_over_prob = 1.0 / over25
                implied_under_prob = 1.0 / under25
                total_implied = implied_over_prob + implied_under_prob
                if total_implied > 0:
                    normalized_over = implied_over_prob / total_implied
                    if normalized_over > 0.55:
                        results["signals"].append(
                            f"Market implies {normalized_over:.0%} probability Over 2.5 — aggressive"
                        )
                        results["adjustment"] += 2
                    elif normalized_over < 0.40:
                        results["signals"].append(
                            f"Market implies only {normalized_over:.0%} Over 2.5 — conservative"
                        )
                        results["adjustment"] -= 2

            # Determine agreement level
            if results["adjustment"] >= 5:
                results["agreement_level"] = "strong_high_scoring"
            elif results["adjustment"] >= 2:
                results["agreement_level"] = "moderate_high_scoring"
            elif results["adjustment"] <= -5:
                results["agreement_level"] = "strong_low_scoring"
            elif results["adjustment"] <= -2:
                results["agreement_level"] = "moderate_low_scoring"
            else:
                results["agreement_level"] = "neutral"

        except sqlite3.Error as e:
            results["error"] = str(e)

        return results

    def _find_latest_event_id(
        self, conn: sqlite3.Connection, home_team: str, away_team: str
    ) -> Optional[str]:
        """Find the most recent event_id for a fixture in the odds database."""
        cursor = conn.execute(
            """
            SELECT event_id FROM event_details
            WHERE home_team = ? AND away_team = ?
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (home_team, away_team),
        )
        row = cursor.fetchone()
        if row:
            return row["event_id"]

        # Try reversed teams
        cursor = conn.execute(
            """
            SELECT event_id FROM event_details
            WHERE home_team = ? AND away_team = ?
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (away_team, home_team),
        )
        row = cursor.fetchone()
        if row:
            return row["event_id"]
        return None

    @staticmethod
    def _get_market_odds(
        conn: sqlite3.Connection,
        event_id: str,
        market_name: str,
        selection_name: str,
        specifiers: str = "",
    ) -> Optional[float]:
        """Get the latest odds for a specific market selection."""
        cursor = conn.execute(
            """
            SELECT odds FROM deep_markets
            WHERE event_id = ?
              AND market_name = ?
              AND selection_name = ?
              AND specifiers = ?
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (event_id, market_name, selection_name, specifiers),
        )
        row = cursor.fetchone()
        return float(row["odds"]) if row else None

    @staticmethod
    def _get_exact_goals_odds(
        conn: sqlite3.Connection, event_id: str
    ) -> Optional[Dict[str, float]]:
        """Get all exact goals odds for an event."""
        cursor = conn.execute(
            """
            SELECT selection_name, odds FROM deep_markets
            WHERE event_id = ?
              AND market_name = 'Exact goals'
            ORDER BY CAST(
                CASE WHEN selection_name = '6+' THEN '7' ELSE selection_name END
                AS REAL
            ) ASC
            """,
            (event_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            return None
        result = {}
        for row in rows:
            name = row["selection_name"]
            odds_val = float(row["odds"])
            result[name] = odds_val
        return result

    # ── League position adjustment ─────────────────────────────────

    def _get_league_position_adjustment(
        self, home_team: str, away_team: str
    ) -> Dict[str, Any]:
        """
        Check league positions from the odds database event_details.

        If available, apply a small adjustment based on rank differential.
        Bigger gap → more predictable → slight adjustment.

        Returns:
            dict with 'adjustment', 'home_rank', 'away_rank', 'found'
        """
        result = {"adjustment": 0.0, "home_rank": None, "away_rank": None, "found": False}

        conn = self._get_odds_conn()
        try:
            cursor = conn.execute(
                """
                SELECT home_rank, away_rank FROM event_details
                WHERE home_team = ? AND away_team = ?
                  AND home_rank IS NOT NULL
                  AND away_rank IS NOT NULL
                ORDER BY captured_at DESC
                LIMIT 1
                """,
                (home_team, away_team),
            )
            row = cursor.fetchone()

            if row is None:
                cursor = conn.execute(
                    """
                    SELECT home_rank, away_rank FROM event_details
                    WHERE home_team = ? AND away_team = ?
                      AND home_rank IS NOT NULL
                      AND away_rank IS NOT NULL
                    ORDER BY captured_at DESC
                    LIMIT 1
                    """,
                    (away_team, home_team),
                )
                row = cursor.fetchone()

            if row:
                home_rank = int(row["home_rank"])
                away_rank = int(row["away_rank"])
                result["home_rank"] = home_rank
                result["away_rank"] = away_rank
                result["found"] = True

                # If home team is significantly higher ranked (lower number), boost slightly
                rank_diff = away_rank - home_rank  # positive = home better
                if rank_diff > 5:
                    result["adjustment"] = 0.08
                elif rank_diff > 2:
                    result["adjustment"] = 0.04
                elif rank_diff < -5:
                    result["adjustment"] = -0.08
                elif rank_diff < -2:
                    result["adjustment"] = -0.04

                result["rank_diff"] = rank_diff

        except sqlite3.Error:
            pass

        return result

    # ── Priors from goal distribution ──────────────────────────────

    @staticmethod
    def _estimate_prob_under(goals_line: float, expected_goals: float) -> float:
        """
        Estimate the probability of Under {goals_line} given expected goals.

        Uses a simple heuristic based on the Poisson-like distribution:
        - For expected_goals near 1.0, Under 2.5 is very likely
        - For expected_goals near 3.0, Under 2.5 is unlikely

        Maps expected_goals → probability using a sigmoid-like function
        calibrated to the VFL goal distribution.
        """
        if goals_line == 1.5:
            # Probability that total_goals <= 1
            if expected_goals <= 0.5:
                return 0.90
            elif expected_goals <= 1.0:
                return 0.75
            elif expected_goals <= 1.5:
                return 0.55
            elif expected_goals <= 2.0:
                return 0.35
            elif expected_goals <= 2.5:
                return 0.20
            else:
                return 0.10

        elif goals_line == 2.5:
            # Probability that total_goals <= 2
            if expected_goals <= 1.0:
                return 0.85
            elif expected_goals <= 1.5:
                return 0.65
            elif expected_goals <= 2.0:
                return 0.45
            elif expected_goals <= 2.5:
                return 0.30
            elif expected_goals <= 3.0:
                return 0.18
            else:
                return 0.08

        elif goals_line == 3.5:
            # Probability that total_goals <= 3
            if expected_goals <= 1.0:
                return 0.95
            elif expected_goals <= 1.5:
                return 0.82
            elif expected_goals <= 2.0:
                return 0.68
            elif expected_goals <= 2.5:
                return 0.52
            elif expected_goals <= 3.0:
                return 0.38
            elif expected_goals <= 3.5:
                return 0.25
            else:
                return 0.12

        return 0.5

    # ── Most likely score prediction ───────────────────────────────

    @staticmethod
    def _predict_most_likely_scores(expected_goals: float) -> List[Dict[str, Any]]:
        """
        Given expected total goals, compute the most likely exact scores.

        Uses a Poisson-inspired model calibrated to VFL's actual score distribution
        (from 19,033 matches). Returns top 5 most likely scorelines.

        Args:
            expected_goals: Expected total goals for the fixture.

        Returns:
            List of {'score': 'X-Y', 'probability': P} sorted by probability descending.
        """
        # Base score probabilities from VFL's actual distribution
        # These are calibrated from the full 19,033 match dataset
        score_probs = {
            "0-0": (0.074, 0.0),
            "1-0": (0.103, 1.0),
            "0-1": (0.084, 1.0),
            "1-1": (0.116, 2.0),
            "2-0": (0.084, 2.0),
            "0-2": (0.054, 2.0),
            "2-1": (0.085, 3.0),
            "1-2": (0.067, 3.0),
            "2-2": (0.044, 4.0),
            "3-0": (0.044, 3.0),
            "3-1": (0.042, 4.0),
            "0-3": (0.025, 3.0),
            "1-3": (0.029, 4.0),
            "3-2": (0.021, 5.0),
            "4-0": (0.020, 4.0),
            "0-4": (0.010, 4.0),
            "4-1": (0.014, 5.0),
            "2-3": (0.010, 5.0),
            "3-3": (0.006, 6.0),
            "4-2": (0.008, 6.0),
            "1-4": (0.006, 5.0),
            "5-0": (0.007, 5.0),
        }

        # Weight scores by how close their total goals are to expected_goals
        # Also weight by base probability (common scores get boost)
        scored = []
        for score, (base_prob, total_g) in score_probs.items():
            # Distance factor: how close to expected_goals (Gaussian-ish)
            dist = abs(total_g - expected_goals)
            score_weight = max(0.01, 1.0 / (1.0 + dist * 0.8))

            # Combined score = base probability * distance weight
            combined = base_prob * score_weight
            scored.append((score, combined, total_g))

        # Sort by combined score descending
        scored.sort(key=lambda x: -x[1])

        # Normalize to probabilities
        total_score = sum(s[1] for s in scored[:7])
        results = []
        for score, s, total_g in scored[:5]:
            prob = round(s / total_score * 100, 1) if total_score > 0 else 0
            results.append({"score": score, "total_goals": total_g, "probability": prob})

        return results

    # ── Deep market odds cross-validation ──────────────────────────

    def _check_odds_crossval(
        self, home_team: str, away_team: str, market: str
    ) -> Dict[str, Any]:
        """
        Cross-validate the predicted market against deep market odds.

        Checks Correct Score and Exact Goals odds from vfl_odds.db to see
        if the market agrees with our recommendation.

        Args:
            home_team: Home team name.
            away_team: Away team name.
            market: Recommended market (e.g. "Over 1.5").

        Returns:
            dict with 'aligned', 'misaligned', 'boost', 'penalty', 'detail'
        """
        result = {
            "aligned": False,
            "misaligned": False,
            "boost": 0,
            "penalty": 0,
            "detail": "no odds data",
        }
        try:
            conn = self._get_odds_conn()
            is_over = "Over" in market

            # Fetch Correct Score odds for 0-0
            cursor = conn.execute(
                """
                SELECT dm.odds
                FROM deep_markets dm
                JOIN event_details ed ON dm.event_id = ed.event_id
                WHERE ed.home_team = ? AND ed.away_team = ?
                  AND dm.market_name = 'Correct Score'
                  AND dm.selection_name = '0-0'
                ORDER BY dm.captured_at DESC
                LIMIT 1
                """,
                (home_team, away_team),
            )
            row = cursor.fetchone()
            if row:
                zero_zero_odds = float(row["odds"])
                # Short 0-0 odds (< 8.0) imply market expects a 0-0
                if zero_zero_odds < 8.0:
                    if is_over:
                        # Market prices 0-0 as likely, contradicts Over 1.5
                        result["misaligned"] = True
                        result["penalty"] = 5
                        result["detail"] = f"0-0 @ {zero_zero_odds:.2f} (market expects 0-0)"
                    else:
                        result["aligned"] = True
                        result["boost"] = 5
                        result["detail"] = f"0-0 @ {zero_zero_odds:.2f} confirms low-scoring"
                elif zero_zero_odds > 15.0 and not is_over:
                    # Very long 0-0 odds contradict Under market
                    result["misaligned"] = True
                    result["penalty"] = 5
                    result["detail"] = f"0-0 @ {zero_zero_odds:.2f} (market sees goals)"
                elif zero_zero_odds > 15.0:
                    result["aligned"] = True
                    result["boost"] = 3
                    result["detail"] = f"0-0 @ {zero_zero_odds:.2f} (market sees no shutout)"

            # Also check GG/NG odds
            cursor = conn.execute(
                """
                SELECT dm.odds, dm.selection_name
                FROM deep_markets dm
                JOIN event_details ed ON dm.event_id = ed.event_id
                WHERE ed.home_team = ? AND ed.away_team = ?
                  AND dm.market_name = 'GG/NG'
                  AND dm.selection_name = 'NG'
                ORDER BY dm.captured_at DESC
                LIMIT 1
                """,
                (home_team, away_team),
            )
            row = cursor.fetchone()
            if row:
                ng_odds = float(row["odds"])
                # NG (No Goal = at least one team fails to score) < 2.0 implies low scoring
                if ng_odds < 1.8 and is_over:
                    # NG heavily favored, contradicts Over 1.5
                    result["misaligned"] = True
                    result["penalty"] = max(result["penalty"], 3)
                    result["detail"] += f"; NG @ {ng_odds:.2f}"
                elif ng_odds < 1.8 and not is_over:
                    result["aligned"] = True
                    result["boost"] = max(result["boost"], 3)
                    result["detail"] += f"; NG @ {ng_odds:.2f} confirms low-scoring"
                elif ng_odds > 2.5 and not is_over:
                    # GG likely (odds > 2.5 for NG), goals expected
                    result["misaligned"] = True
                    result["penalty"] = max(result["penalty"], 3)
                    result["detail"] += f"; NG @ {ng_odds:.2f} (market sees goals)"

        except (sqlite3.Error, ValueError, TypeError):
            pass  # Non-critical — gracefully degrade

        return result

    # ── Main analysis ──────────────────────────────────────────────

    def analyze_fixture(
        self,
        home_team: str,
        away_team: str,
        include_market_validation: bool = True,
    ) -> Dict[str, Any]:
        """
        Analyze a fixture and produce a rich prediction.

        This is the main entry point. It computes the 3-layer signal fusion,
        applies adjustments, makes a market decision, and cross-validates
        against deep market odds.

        Args:
            home_team: Home team name (must be one of the 16 VFL teams)
            away_team: Away team name
            include_market_validation: Whether to cross-validate against deep markets

        Returns:
            dict with keys:
                - fixture: dict with home_team, away_team
                - expected_goals: blended expected goals figure
                - recommended_market: e.g. "Over 1.5" or "Under 2.5"
                - confidence: 0-100 confidence score
                - strength: "STRONG", "MODERATE", or "WEAK"
                - breakdown: dict with L1, L2, L3 details
                - signals: list of explanatory signal strings
                - market_validation: dict if cross-validation ran
        """
        # Normalize and validate teams
        home_team = self.validate_team(home_team)
        away_team = self.validate_team(away_team)

        if home_team == away_team:
            raise ValueError(
                f"Home and away teams must be different (got '{home_team}' vs '{away_team}')"
            )

        signals: List[str] = []

        # ── Layer 1: All-time profiles ──
        l1 = self._compute_l1(home_team, away_team)
        l1_val = l1["expected_goals"]

        signals.append(f"{home_team} profile: avg {TEAM_PROFILES[home_team]['avg_goals']}g, "
                       f"{TEAM_PROFILES[home_team]['tier']}")
        signals.append(f"{away_team} profile: avg {TEAM_PROFILES[away_team]['avg_goals']}g, "
                       f"{TEAM_PROFILES[away_team]['tier']}")

        home_tier = TEAM_PROFILES[home_team]["tier"]
        away_tier = TEAM_PROFILES[away_team]["tier"]
        if home_tier == "defensive" and away_tier == "defensive":
            signals.append("Both teams defensive — strong downward adjustment applied")
        elif home_tier == "powerhouse" and away_tier == "powerhouse":
            signals.append("Both teams powerhouse — strong upward adjustment applied")

        # ── Layer 2: H2H history ──
        l2 = self._compute_l2(home_team, away_team)
        l2_val = l2.get("expected_goals")
        if l2_val is not None:
            signals.append(f"H2H history ({l2['n_matches']} matches): avg {l2['avg_total_goals']}g, "
                           f"{l2['o1_5_rate']}% O1.5")
            if l2["zero_zero_rate"] and l2["zero_zero_rate"] > 15:
                signals.append(f"High 0-0 rate in H2H: {l2['zero_zero_rate']}%")
        else:
            signals.append(f"No H2H history between these teams")

        # ── Layer 3: Recent form ──
        l3 = self._compute_l3(home_team, away_team)
        l3_val = l3.get("expected_goals")
        if l3_val is not None:
            signals.append(f"Recent form blends to {l3_val:.2f} expected goals "
                           f"(H:{l3['n_home']} matches, A:{l3['n_away']} matches)")

        # ── Blended estimate ──
        # Weights: L1=0.70, L2=0.20, L3=0.10
        # If L2 or L3 is missing, redistribute weight proportionally
        total_weight = 0.0
        blended = 0.0

        blended += l1_val * L1_WEIGHT
        total_weight += L1_WEIGHT

        if l2_val is not None:
            l2_weight = L2_WEIGHT * l2["confidence"]
            blended += l2_val * l2_weight
            total_weight += l2_weight
        else:
            signals.append("L2 (H2H) unavailable — weight redistributed to L1")

        if l3_val is not None:
            l3_weight = L3_WEIGHT * l3["confidence"]
            blended += l3_val * l3_weight
            total_weight += l3_weight
        else:
            signals.append("L3 (form) unavailable — weight redistributed to L1")

        # Renormalize
        if total_weight > 0:
            blended /= total_weight
        else:
            blended = l1_val

        # ── League position adjustment ──
        rank_adj = self._get_league_position_adjustment(home_team, away_team)
        if rank_adj["found"] and rank_adj["adjustment"] != 0:
            blended += rank_adj["adjustment"]
            signals.append(
                f"Rank differential ({rank_adj['home_rank']} vs {rank_adj['away_rank']}): "
                f"{'upward' if rank_adj['adjustment'] > 0 else 'downward'} adj of {rank_adj['adjustment']:.2f}"
            )

        blended = max(0.5, min(blended, 5.0))

        # ── PHASED DECISION ARCHITECTURE ──
        # Phase 1: Check if this is a LOW-SCORING EXCEPTION using H2H data
        # Phase 2: If not, default to Over 1.5 (73.9% of all VFL games)
        #
        # Rationale: Over 1.5 hits 73.9% of the time — it's the volume default.
        # Only switch to Under markets when H2H data strongly signals a
        # 0-0, 1-0, or 0-1 game (the 26.1% exception).

        h2h_o15 = l2.get("o1_5_rate") if l2 else None
        h2h_n = l2.get("n_matches", 0) if l2 else 0
        home_tier_obj = self._team_profiles.get(home_team, {})
        away_tier_obj = self._team_profiles.get(away_team, {})
        h_tier = home_tier_obj.get("tier", "balanced")
        a_tier = away_tier_obj.get("tier", "balanced")
        both_defensive = h_tier == "defensive" and a_tier == "defensive"
        one_defensive = h_tier == "defensive" or a_tier == "defensive"

        # H2H-driven low-scoring detection
        h2h_low_scoring = h2h_o15 is not None and h2h_n >= 40 and h2h_o15 < 55.0
        tier_low_scoring = both_defensive and one_defensive
        blended_under = blended < 1.8  # blended rarely under 1.6, use 1.8 as softer flag

        is_low_scoring_candidate = h2h_low_scoring or (tier_low_scoring and blended_under)

        if is_low_scoring_candidate:
            # ── LOW-SCORING PATH: Under 2.5 or Under 3.5 ──
            # Validate strength of signal
            h2h_u25 = l2.get("under_2_5_rate") if l2 else None
            h2h_u35 = l2.get("under_3_5_rate") if l2 else None
            effective_o15 = h2h_o15 if h2h_o15 is not None else 60.0

            # Pick Under market based on which has highest confidence
            if effective_o15 < 50.0 or (h2h_u35 is not None and h2h_u35 >= 90.0):
                recommended_market = "Under 3.5"
                # Very strong low-scoring signal: 50-85% confidence
                conf_factor = max(0.0, min(1.0, (55.0 - effective_o15) / 15.0))
                confidence = int(round(50 + conf_factor * 35))
            else:
                recommended_market = "Under 2.5"
                # Moderate low-scoring signal
                conf_factor = max(0.0, min(1.0, (58.0 - effective_o15) / 12.0))
                confidence = int(round(50 + conf_factor * 30))

            # Boost confidence with tier confirmation
            if both_defensive:
                confidence = min(92, confidence + 8)
                signals.append("Both teams defensive → confirmed low-scoring tendency")

            # Boost with form convergence
            if l3_val is not None and l3_val < 1.8:
                confidence = min(92, confidence + 5)
                signals.append(f"Recent form ({l3_val:.1f}g avg) supports low-scoring expectation")

            confidence = max(50, min(92, confidence))
            signals.append(
                f"H2H O1.5 rate {effective_o15:.1f}% (<55%) → {recommended_market} recommended"
            )

        else:
            # ── DEFAULT PATH: Over 1.5 ──
            recommended_market = "Over 1.5"
            # Confidence based on blended expected goals:
            # 1.6→70%, 2.0→80%, 2.5+→93%
            if blended >= 2.5:
                confidence = 93
                signals.append(f"Expected {blended:.2f}g ≥ 2.5 → Over 1.5 (HIGH confidence)")
            elif blended >= 2.0:
                conf_raw = 0.80 + (blended - 2.0) * (0.13 / 0.5)
                confidence = int(round(conf_raw * 100))
                signals.append(f"Expected {blended:.2f}g 2.0-2.5 → Over 1.5 (strong confidence)")
            else:
                # 1.6 to 2.0 — moderate confidence zone
                conf_raw = 0.70 + (blended - 1.6) * (0.10 / 0.4)
                confidence = int(round(conf_raw * 100))
                signals.append(f"Expected {blended:.2f}g 1.6-2.0 → Over 1.5 (moderate confidence)")

            # Boost confidence for attacking/powerhouse matchups
            if h_tier in ("attacking", "powerhouse") and a_tier in ("attacking", "powerhouse"):
                confidence = min(96, confidence + 5)
                signals.append("Both teams offensive → O1.5 boost applied")
            elif h_tier == "powerhouse" or a_tier == "powerhouse":
                confidence = min(96, confidence + 3)
                signals.append("Powerhouse involved → O1.5 boost applied")

            confidence = max(55, min(96, confidence))

        # ── Cross-validation with deep market odds ──
        if self._odds_path_usable:
            try:
                odds_signal = self._check_odds_crossval(
                    home_team, away_team, recommended_market
                )
                if odds_signal["aligned"]:
                    confidence = min(97, confidence + odds_signal["boost"])
                    signals.append(f"Deep market odds align ({odds_signal['detail']})")
                elif odds_signal["misaligned"] and confidence > 55:
                    confidence = max(55, confidence - odds_signal["penalty"])
                    signals.append(f"Deep market odds contradict ({odds_signal['detail']})")
            except Exception:
                pass  # Odds cross-validation is non-critical

        # ── Strength rating ──
        if confidence >= 80:
            strength = "STRONG"
        elif confidence >= 65:
            strength = "MODERATE"
        else:
            strength = "WEAK"

        # ── Most likely score prediction ──
        # Given expected goals, compute most likely exact scores
        likely_scores = self._predict_most_likely_scores(blended)

        result = {
            "fixture": {
                "home_team": home_team,
                "away_team": away_team,
            },
            "expected_goals": round(blended, 2),
            "recommended_market": recommended_market,
            "confidence": confidence,
            "strength": strength,
            "breakdown": {
                "L1_all_time_profiles": {
                    "expected_goals": l1["expected_goals"],
                    "base_blend": l1["base_blend"],
                    "tier_adjustment": l1["tier_adjustment"],
                    "home_advantage": l1["home_advantage"],
                    "home_tier": home_tier,
                    "away_tier": away_tier,
                },
                "L2_h2h_history": {
                    "expected_goals": l2.get("expected_goals"),
                    "n_matches": l2.get("n_matches", 0),
                    "confidence": l2.get("confidence", 0),
                    "o1_5_rate": l2.get("o1_5_rate"),
                    "zero_zero_rate": l2.get("zero_zero_rate"),
                },
                "L3_recent_form": {
                    "expected_goals": l3.get("expected_goals"),
                    "n_home": l3.get("n_home", 0),
                    "n_away": l3.get("n_away", 0),
                    "confidence": l3.get("confidence", 0),
                },
                "league_position_adjustment": {
                    "found": rank_adj["found"],
                    "adjustment": rank_adj["adjustment"],
                    "home_rank": rank_adj["home_rank"],
                    "away_rank": rank_adj["away_rank"],
                },
                "blended_raw": round(blended, 4),
            },
            "signals": signals,
            "likely_scores": likely_scores,
        }

        # ── Market cross-validation ──
        if include_market_validation:
            validation = self._cross_validate(home_team, away_team, blended)
            result["market_validation"] = validation

            if validation.get("market_data_found"):
                signals.extend(validation.get("signals", []))
                # Adjust confidence based on market agreement
                adj = validation.get("adjustment", 0)
                if adj != 0:
                    old_conf = confidence
                    confidence = max(40, min(98, confidence + adj))
                    result["confidence"] = confidence
                    result["market_validation"]["confidence_adjustment"] = adj
                    result["market_validation"]["confidence_before"] = old_conf
                    result["market_validation"]["confidence_after"] = confidence

                # Re-assess strength after market adjustment
                if confidence >= 80:
                    result["strength"] = "STRONG"
                elif confidence >= 65:
                    result["strength"] = "MODERATE"
                else:
                    result["strength"] = "WEAK"

        return result

    # ── Batch analysis ─────────────────────────────────────────────

    def analyze_fixtures(
        self, fixtures: List[Tuple[str, str]], **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Analyze multiple fixtures in batch.

        Args:
            fixtures: List of (home_team, away_team) tuples
            **kwargs: Passed through to analyze_fixture

        Returns:
            List of analysis results
        """
        results = []
        for home, away in fixtures:
            try:
                results.append(self.analyze_fixture(home, away, **kwargs))
            except (ValueError, sqlite3.Error) as e:
                results.append({
                    "fixture": {"home_team": home, "away_team": away},
                    "error": str(e),
                })
        return results

    # ── Utility: get team profile summary ─────────────────────────

    @staticmethod
    def get_team_profile(team_name: str) -> Dict[str, Any]:
        """Get the all-time profile for a team."""
        team = FixtureIntelligenceEngine.validate_team(team_name)
        return TEAM_PROFILES.get(team, {})

    @staticmethod
    def get_h2h_summary(results_db_path: str, team1: str, team2: str) -> Dict[str, Any]:
        """Get H2H summary for two teams directly from the database."""
        team1 = FixtureIntelligenceEngine.validate_team(team1)
        team2 = FixtureIntelligenceEngine.validate_team(team2)

        conn = sqlite3.connect(results_db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as n,
                    ROUND(AVG(total_goals), 2) as avg_goals,
                    SUM(CASE WHEN total_goals > 1.5 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as o1_5_pct,
                    SUM(CASE WHEN home_goals = 0 AND away_goals = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as zz_pct,
                    ROUND(AVG(home_goals), 2) as avg_home_goals,
                    ROUND(AVG(away_goals), 2) as avg_away_goals
                FROM results
                WHERE status = 3
                  AND (
                      (home_team = ? AND away_team = ?)
                      OR (home_team = ? AND away_team = ?)
                  )
                """,
                (team1, team2, team2, team1),
            )
            row = cursor.fetchone()
            if row and row["n"] > 0:
                return {
                    "team1": team1,
                    "team2": team2,
                    "n_matches": int(row["n"]),
                    "avg_total_goals": float(row["avg_goals"]),
                    "o1_5_pct": round(float(row["o1_5_pct"]), 1) if row["o1_5_pct"] else 0,
                    "zz_pct": round(float(row["zz_pct"]), 1) if row["zz_pct"] else 0,
                    "avg_home_goals": float(row["avg_home_goals"]),
                    "avg_away_goals": float(row["avg_away_goals"]),
                }
            return {"team1": team1, "team2": team2, "n_matches": 0}
        finally:
            conn.close()


# ──────────────────────────────────────────────────────────────────────
# COMMAND-LINE INTERFACE
# ──────────────────────────────────────────────────────────────────────


def main():
    """CLI entry point for the Fixture Intelligence Engine."""
    import argparse

    parser = argparse.ArgumentParser(
        description="VFL Fixture Intelligence Engine - Predict optimal markets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s Everton Leeds
  %(prog)s "Manchester Blue" "London Guns" --no-market-val
  %(prog)s --batch fixtures.json
  %(prog)s --h2h Everton Leeds
  %(prog)s --team-profile "Manchester Blue"
        """,
    )
    parser.add_argument("home_team", nargs="?", help="Home team name")
    parser.add_argument("away_team", nargs="?", help="Away team name")
    parser.add_argument(
        "--results-db",
        default="",
        help="Path to vfl_results.db (auto-detect if empty)",
    )
    parser.add_argument(
        "--odds-db",
        default="",
        help="Path to vfl_odds.db (auto-detect if empty)",
    )
    parser.add_argument(
        "--no-market-val",
        action="store_true",
        help="Skip market cross-validation",
    )
    parser.add_argument(
        "--batch",
        help="JSON file with list of [home, away] fixture pairs",
    )
    parser.add_argument(
        "--h2h",
        nargs=2,
        metavar=("TEAM1", "TEAM2"),
        help="Get H2H summary between two teams",
    )
    parser.add_argument(
        "--team-profile",
        metavar="TEAM",
        help="Get profile for a team",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    try:
        if args.team_profile:
            profile = FixtureIntelligenceEngine.get_team_profile(args.team_profile)
            if args.json:
                print(json.dumps(profile, indent=2))
            else:
                print(f"\n=== {args.team_profile} Profile ===")
                for k, v in profile.items():
                    print(f"  {k}: {v}")
            return

        if args.h2h:
            # Resolve results db path for standalone H2H query
            h2h_results_db = FixtureIntelligenceEngine._resolve_db_path(
                args.results_db or "", "vfl_results.db"
            )
            summary = FixtureIntelligenceEngine.get_h2h_summary(
                h2h_results_db, args.h2h[0], args.h2h[1],
            )
            if args.json:
                print(json.dumps(summary, indent=2))
            else:
                print(f"\n=== H2H: {summary['team1']} vs {summary['team2']} ===")
                for k, v in summary.items():
                    print(f"  {k}: {v}")
            return

        engine = FixtureIntelligenceEngine(
            results_db_path=args.results_db,
            odds_db_path=args.odds_db,
        )

        if args.batch:
            with open(args.batch, "r") as f:
                fixtures = json.load(f)
            results = engine.analyze_fixtures(
                fixtures, include_market_validation=not args.no_market_val
            )
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                for r in results:
                    _print_result(r)
            return

        if args.home_team and args.away_team:
            result = engine.analyze_fixture(
                args.home_team,
                args.away_team,
                include_market_validation=not args.no_market_val,
            )
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                _print_result(result)
        else:
            parser.print_help()

    except (ValueError, FileNotFoundError, sqlite3.Error) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _print_result(result: Dict[str, Any]):
    """Pretty-print an analysis result."""
    if "error" in result:
        print(f"\n⚠ Error: {result['error']}")
        return

    f = result["fixture"]
    print("\n" + "=" * 60)
    print(f"  {f['home_team']} vs {f['away_team']}")
    print("=" * 60)
    print(f"  Expected Goals:  {result['expected_goals']:.2f}")
    print(f"  Recommended:     {result['recommended_market']}")
    print(f"  Confidence:      {result['confidence']}% ({result['strength']})")
    print()

    print("  Signals:")
    for s in result.get("signals", []):
        print(f"    • {s}")
    print()

    bd = result["breakdown"]
    print("  ┌─ Layer 1 (All-Time Profiles) ──────────────────────────")
    l1 = bd["L1_all_time_profiles"]
    print(f"  │ Expected: {l1['expected_goals']:.4f}g (base {l1['base_blend']:.4f} + "
          f"tier adj {l1['tier_adjustment']:.4f} + home adv {l1['home_advantage']})")
    print(f"  │ {f['home_team']}: {l1['home_tier']} ({TEAM_PROFILES[f['home_team']]['avg_goals']}g)")
    print(f"  │ {f['away_team']}: {l1['away_tier']} ({TEAM_PROFILES[f['away_team']]['avg_goals']}g)")

    l2 = bd["L2_h2h_history"]
    print(f"  ├─ Layer 2 (H2H History) ───────────────────────────────")
    if l2["n_matches"] > 0:
        print(f"  │ {l2['n_matches']} matches, avg {l2['expected_goals']}g, "
              f"{l2['o1_5_rate']}% O1.5 (conf: {l2['confidence']})")
        if l2["zero_zero_rate"] and l2["zero_zero_rate"] > 0:
            print(f"  │ 0-0 rate: {l2['zero_zero_rate']}%")
    else:
        print(f"  │ No H2H data available")

    l3 = bd["L3_recent_form"]
    print(f"  ├─ Layer 3 (Recent Form) ───────────────────────────────")
    if l3["expected_goals"]:
        print(f"  │ {l3['expected_goals']}g ({l3['n_home']}H + {l3['n_away']}A matches, "
              f"conf: {l3['confidence']})")
    else:
        print(f"  │ No form data available")

    rank = bd["league_position_adjustment"]
    if rank["found"]:
        print(f"  ├─ League Position ────────────────────────────────────")
        print(f"  │ H rank: {rank['home_rank']}, A rank: {rank['away_rank']}, "
              f"adj: {rank['adjustment']:.4f}")

    print(f"  └─ Blended Raw: {bd['blended_raw']:.4f}")
    print()

    mv = result.get("market_validation")
    if mv and mv.get("market_data_found"):
        print("  Market Cross-Validation:")
        print(f"    Agreement: {mv['agreement_level']}")
        for s in mv.get("signals", []):
            print(f"    • {s}")
        print()

    print("=" * 60)


if __name__ == "__main__":
    main()
