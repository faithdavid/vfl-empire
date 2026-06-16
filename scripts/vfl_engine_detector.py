#!/usr/bin/env python3
"""
VFL Engine Regime Detector — Determines current scoring environment.
====================================================================
Computes the current "engine regime" (OFFENSIVE / DEFENSIVE / NEUTRAL)
by analyzing recent match data from the results database.

Usage:
    from vfl_engine_detector import EngineRegimeDetector
    detector = EngineRegimeDetector()
    regime = detector.get_current_regime()
    # Returns: {"regime": "OFFENSIVE", "trend": "rising", "avg_goals": 2.58, ...}
"""
import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("[ENGINE_DETECTOR]")

RESULTS_DB = Path("/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db")


class EngineRegimeDetector:
    """Detects the current scoring regime from recent VFL match data.

    Analyzes the last N matches to determine if the league is in an
    OFFENSIVE (high goals), DEFENSIVE (low goals), or NEUTRAL regime.
    Also computes trend direction and statistical summary.
    """

    OFFENSIVE_THRESHOLD = 2.70   # avg_goals above this → OFFENSIVE
    DEFENSIVE_THRESHOLD = 2.40   # avg_goals below this → DEFENSIVE
    RECENT_MATCHES = 500         # window size for regime analysis

    def __init__(self, db_path: str = None):
        self._db_path = db_path or str(RESULTS_DB)

    def _get_conn(self):
        """Get a read-only SQLite connection."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_current_regime(self) -> dict:
        """Analyze recent matches and determine the current engine regime.

        Returns a dict with:
            regime: str - "OFFENSIVE", "DEFENSIVE", or "NEUTRAL"
            trend: str - "rising", "falling", or "stable"
            avg_goals: float - average total goals in the window
            n_matches: int - number of matches analyzed
            u35_rate: float - under 3.5 goals rate in window
            o15_rate: float - over 1.5 goals rate in window
            draw_rate: float - draw rate in window
            season_id: str - most recent season_id
        """
        try:
            conn = self._get_conn()
            try:
                # Get the most recent season
                cur = conn.execute(
                    "SELECT season_id FROM results ORDER BY season_id DESC LIMIT 1"
                )
                row = cur.fetchone()
                latest_season = row["season_id"] if row else None

                # Analyze last N matches
                cur = conn.execute(
                    """
                    SELECT
                        COUNT(*) as n,
                        ROUND(AVG(total_goals), 2) as avg_goals,
                        SUM(CASE WHEN total_goals < 3.5 THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as u35_rate,
                        SUM(CASE WHEN total_goals >= 1.5 THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as o15_rate,
                        SUM(CASE WHEN home_goals = away_goals THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as draw_rate
                    FROM (
                        SELECT total_goals, home_goals, away_goals FROM results
                        ORDER BY rowid DESC
                        LIMIT ?
                    )
                    """,
                    (self.RECENT_MATCHES,),
                )
                row = cur.fetchone()
                if not row or row["n"] == 0:
                    return self._default_regime()

                n = row["n"]
                avg_goals = row["avg_goals"]
                u35_rate = round(row["u35_rate"], 1) if row["u35_rate"] else 0
                o15_rate = round(row["o15_rate"], 1) if row["o15_rate"] else 0
                draw_rate = round(row["draw_rate"], 1) if row["draw_rate"] else 0

                # Determine regime
                if avg_goals >= self.OFFENSIVE_THRESHOLD:
                    regime = "OFFENSIVE"
                elif avg_goals <= self.DEFENSIVE_THRESHOLD:
                    regime = "DEFENSIVE"
                else:
                    regime = "NEUTRAL"

                # Determine trend by comparing first half vs second half of window
                trend = self._compute_trend(conn)

                return {
                    "regime": regime,
                    "trend": trend,
                    "avg_goals": avg_goals,
                    "n_matches": n,
                    "u35_rate": u35_rate,
                    "o15_rate": o15_rate,
                    "draw_rate": draw_rate,
                    "season_id": latest_season or "",
                    "window_size": self.RECENT_MATCHES,
                }

            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Could not query DB for regime detection: {e}")
            return self._default_regime()

    def _compute_trend(self, conn) -> str:
        """Compare first half vs second half of the analysis window."""
        try:
            half = self.RECENT_MATCHES // 2
            cur = conn.execute(
                """
                SELECT
                    ROUND(AVG(CASE WHEN rn <= ? THEN total_goals END), 2) as recent_avg,
                    ROUND(AVG(CASE WHEN rn > ? THEN total_goals END), 2) as older_avg
                FROM (
                    SELECT total_goals,
                           ROW_NUMBER() OVER (ORDER BY rowid DESC) as rn
                    FROM results
                    LIMIT ?
                )
                """,
                (half, half, self.RECENT_MATCHES),
            )
            row = cur.fetchone()
            if row and row["recent_avg"] is not None and row["older_avg"] is not None:
                diff = row["recent_avg"] - row["older_avg"]
                if diff > 0.1:
                    return "rising"
                elif diff < -0.1:
                    return "falling"
            return "stable"
        except Exception:
            return "stable"

    def _default_regime(self) -> dict:
        """Return a safe default when DB is unavailable."""
        return {
            "regime": "NEUTRAL",
            "trend": "stable",
            "avg_goals": 2.5,
            "n_matches": 0,
            "u35_rate": 70.0,
            "o15_rate": 75.0,
            "draw_rate": 27.5,
            "season_id": "",
            "window_size": self.RECENT_MATCHES,
        }

    def get_regime_adjustment(self, market: str, regime_dict: dict = None) -> int:
        """Get the confidence adjustment for a market based on regime.

        Args:
            market: "O1.5" or "U3.5"
            regime_dict: output from get_current_regime() (or None to auto-detect)

        Returns:
            Adjustment to apply to confidence score (e.g., +8 means boost by 8)
        """
        if regime_dict is None:
            regime_dict = self.get_current_regime()

        regime = regime_dict.get("regime", "NEUTRAL")

        if market == "O1.5" and regime == "OFFENSIVE":
            return 8   # boost O1.5 confidence by 8 points
        elif market == "U3.5" and regime == "DEFENSIVE":
            return 8   # boost U3.5 confidence by 8 points
        elif market == "O1.5" and regime == "DEFENSIVE":
            return -5  # reduce O1.5 confidence in defensive regime
        elif market == "U3.5" and regime == "OFFENSIVE":
            return -5  # reduce U3.5 confidence in offensive regime

        return 0

    def get_team_trend(self, team_name: str, last_n: int = 30) -> dict:
        """Is this team's performance rising or falling vs their all-time?

        Compares the team's last N matches against their all-time averages.
        Returns:
            trend: str - "rising", "falling", or "stable"
            delta_o15: float - pp change in O1.5 rate
            delta_u35: float - pp change in U3.5 rate
            delta_goals: float - change in avg goals
            sample_size: int - matches analyzed
        """
        try:
            conn = self._get_conn()
            try:
                # All-time averages for the team
                cur = conn.execute(
                    """
                    SELECT
                        COUNT(*) as n_all,
                        ROUND(AVG(total_goals), 2) as avg_goals_all,
                        SUM(CASE WHEN total_goals >= 1.5 THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as o15_all,
                        SUM(CASE WHEN total_goals < 3.5 THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as u35_all
                    FROM results
                    WHERE home_team = ? OR away_team = ?
                    """,
                    (team_name, team_name),
                )
                row_all = cur.fetchone()

                # Last N matches for the team
                cur = conn.execute(
                    """
                    SELECT
                        COUNT(*) as n_recent,
                        ROUND(AVG(total_goals), 2) as avg_goals_recent,
                        SUM(CASE WHEN total_goals >= 1.5 THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as o15_recent,
                        SUM(CASE WHEN total_goals < 3.5 THEN 1 ELSE 0 END)
                            * 100.0 / COUNT(*) as u35_recent
                    FROM (
                        SELECT * FROM results
                        WHERE home_team = ? OR away_team = ?
                        ORDER BY season_id DESC, match_day DESC
                        LIMIT ?
                    )
                    """,
                    (team_name, team_name, last_n),
                )
                row_recent = cur.fetchone()

                if not row_all or not row_recent or row_all["n_all"] == 0:
                    return {"trend": "stable", "delta_o15": 0, "delta_u35": 0, "delta_goals": 0, "sample_size": 0}

                delta_o15 = round(row_recent["o15_recent"] - row_all["o15_all"], 1) if row_recent["o15_recent"] and row_all["o15_all"] else 0
                delta_u35 = round(row_recent["u35_recent"] - row_all["u35_all"], 1) if row_recent["u35_recent"] and row_all["u35_all"] else 0
                delta_goals = round(row_recent["avg_goals_recent"] - row_all["avg_goals_all"], 2) if row_recent["avg_goals_recent"] and row_all["avg_goals_all"] else 0

                if delta_o15 > 5:
                    trend = "rising"
                elif delta_o15 < -5:
                    trend = "falling"
                else:
                    trend = "stable"

                return {
                    "trend": trend,
                    "delta_o15": delta_o15,
                    "delta_u35": delta_u35,
                    "delta_goals": delta_goals,
                    "sample_size": row_recent["n_recent"] if row_recent else 0,
                }
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Could not compute team trend for {team_name}: {e}")
            return {"trend": "stable", "delta_o15": 0, "delta_u35": 0, "delta_goals": 0, "sample_size": 0}


# Module-level singleton
_detector = None


def get_detector() -> EngineRegimeDetector:
    global _detector
    if _detector is None:
        _detector = EngineRegimeDetector()
    return _detector


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    d = EngineRegimeDetector()
    regime = d.get_current_regime()
    print(f"Regime: {regime['regime']}")
    print(f"Trend: {regime['trend']}")
    print(f"Last {regime['n_matches']} matches: {regime['avg_goals']} avg goals")
    print(f"Draw rate: {regime['draw_rate']}%")
    adj_o15 = d.get_regime_adjustment("O1.5", regime)
    adj_u35 = d.get_regime_adjustment("U3.5", regime)
    print(f"O1.5 adjust: {adj_o15:+d}")
    print(f"U3.5 adjust: {adj_u35:+d}")
    # Test team trend
    trend = d.get_team_trend("Manchester Blue")
    print(f"Man Blue trend: {trend['trend']} (delta O1.5={trend['delta_o15']:+.1f}pp)")
