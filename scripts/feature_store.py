#!/usr/bin/env python3
"""
feature_store.py — Rolling metrics engine that computes live rates from history.db

CORE intelligence engine. Queries the database and computes ACTUAL statistical
rates for every team in the current season, then feeds them into a
prediction-ready format.

Usage:
    python3 feature_store.py              # load from saved file
    python3 feature_store.py --refresh    # query DB + API, save, load
    python3 feature_store.py --season vf:season:1234567  # specific season

As module:
    from feature_store import FeatureStore
    store = FeatureStore()
    store.load()           # loads from file
    store.refresh()        # queries DB + API, saves, and loads
    store.team_rates['BOURNEMOUTH']['over_15_rate']
    store.matchup_rates['MANCHESTER RED_vs_BOURNEMOUTH']['under_35_rate']
    store.league_avg_over_15
"""

import json
import logging
import os
import sqlite3
import sys
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Paths ───────────────────────────────────────────────────────────────────
# Canonical history.db location
HISTORY_DB = os.path.expanduser(
    "~/Documents/Projects/vfl-data/databases/history.db"
)
# Output location
FEATURE_STORE_PATH = os.path.expanduser(
    "~/Documents/Projects/vfl-data/analysis/feature_store.json"
)
# Season tracker cache (optional fallback for current season info)
SEASON_TRACKER_PATH = os.path.expanduser(
    "~/faith-workspace/vfl-complete-data/analysis/season_tracker.json"
)

# ─── Team Name Normalisation ──────────────────────────────────────────────────
# The history.db stores names in both UPPERCASE and Mixed Case.
# We normalise to UPPERCASE for consistency as output keys.
TEAM_ALIASES = {
    "MANCHESTER RED": "MANCHESTER RED",
    "MANCHESTER UNITED": "MANCHESTER RED",
    "MANCHESTER BLUE": "MANCHESTER BLUE",
    "MANCHESTER CITY": "MANCHESTER BLUE",
    "LONDON GUNS": "LONDON GUNS",
    "LONDON GUNNERS": "LONDON GUNS",
    "ARSENAL": "LONDON GUNS",
    "CHELSEA": "CHELSEA",
    "LIVERPOOL": "LIVERPOOL",
    "ASTON VILLA": "ASTON VILLA",
    "TOTTENHAM": "TOTTENHAM",
    "EVERTON": "EVERTON",
    "WOLVERHAMPTON": "WOLVERHAMPTON",
    "NEWCASTLE": "NEWCASTLE",
    "LEEDS": "LEEDS",
    "FULHAM": "FULHAM",
    "WEST HAM": "WEST HAM",
    "BOURNEMOUTH": "BOURNEMOUTH",
    "BRIGHTON": "BRIGHTON",
    "CRYSTAL PALACE": "CRYSTAL PALACE",
}


def normalize(name: str) -> str:
    """Normalise team name to UPPERCASE canonical form."""
    n = name.strip().upper()
    return TEAM_ALIASES.get(n, n)


# ─── Feature Store ────────────────────────────────────────────────────────────


class FeatureStore:
    """Rolling metrics engine — computes live rates from history.db.

    Attributes:
        team_rates (dict): Per-team statistical rates keyed by TEAM (UPPERCASE).
        matchup_rates (dict): H2H-specific rates keyed by 'TEAM1_vs_TEAM2'.
        league_averages (dict): League-wide averages.
        tiers_from_data (dict): Data-driven tiers.
        current_matchday (int): Current match day.
        season (str): Current season name (e.g. 'VFLM 5105').
        season_id (str): Current season ID (e.g. 'vf:season:1234567').
        generated_at (str): ISO timestamp of last refresh.
        _data (dict): Raw stored data.
    """

    def __init__(self, db_path: str = HISTORY_DB):
        self.db_path = db_path

        self.team_rates: Dict[str, Dict] = {}
        self.matchup_rates: Dict[str, Dict] = {}
        self.league_averages: Dict[str, float] = {}
        self.tiers_from_data: Dict[str, List[str]] = {}
        self.current_matchday: int = 0
        self.season: str = ""
        self.season_id: str = ""
        self.generated_at: str = ""

        self._data: Dict[str, Any] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def load(self, path: str = FEATURE_STORE_PATH) -> bool:
        """Load feature store from saved JSON file. Returns True on success."""
        if not os.path.exists(path):
            logger.warning("Feature store file not found: %s", path)
            return False
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self._from_dict(data)
            logger.info(
                "Loaded feature store: %s (season %s, %d teams)",
                path,
                self.season,
                len(self.team_rates),
            )
            return True
        except (json.JSONDecodeError, IOError) as e:
            logger.error("Failed to load feature store: %s", e)
            return False

    def refresh(
        self,
        season_id: Optional[str] = None,
        season_name: Optional[str] = None,
        match_day: Optional[int] = None,
        save_path: str = FEATURE_STORE_PATH,
    ) -> Dict[str, Any]:
        """Query DB + API, compute all rates, save to file, and load.

        Args:
            season_id: Explicit season ID (e.g. 'vf:season:3091747').
                       If None, auto-detect from API or season_tracker.json.
            season_name: Explicit season name (e.g. 'VFLM 5105').
            match_day: Current match day (if known).
            save_path: Where to save the output JSON.

        Returns:
            The full feature store dict.
        """
        data = self._compute(
            season_id=season_id,
            season_name=season_name,
            match_day=match_day,
        )
        self._from_dict(data)
        self._save(save_path)
        return data

    # ── Convenience accessors ───────────────────────────────────────────────

    @property
    def league_avg_over_15(self) -> float:
        return self.league_averages.get("over_15_rate", 0.0)

    @property
    def league_avg_under_35(self) -> float:
        return self.league_averages.get("under_35_rate", 0.0)

    @property
    def league_avg_total_goals(self) -> float:
        return self.league_averages.get("avg_total_goals", 0.0)

    def get_team_rate(self, team: str, metric: str) -> float:
        """Get a specific rate for a team. Returns 0.0 if missing."""
        key = normalize(team)
        return self.team_rates.get(key, {}).get(metric, 0.0)

    def get_matchup_rate(self, home: str, away: str, metric: str) -> float:
        """Get a specific rate for a matchup. Returns 0.0 if missing."""
        key = f"{normalize(home)}_vs_{normalize(away)}"
        return self.matchup_rates.get(key, {}).get(metric, 0.0)

    # ── Internal: computation engine ────────────────────────────────────────

    def _compute(
        self,
        season_id: Optional[str] = None,
        season_name: Optional[str] = None,
        match_day: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Core computation: query DB, compute rates, return data dict."""
        # 1. Determine current season
        if season_id is None:
            season_id, season_name, match_day = self._detect_current_season()

        logger.info(
            "Computing rates for season %s (%s), match day %s",
            season_id,
            season_name,
            match_day,
        )

        # 2. Query completed matches for this season
        matches = self._query_matches(season_id, season_name)

        if not matches:
            logger.warning(
                "No completed matches found for season %s / %s. "
                "Falling back to most recent complete season.",
                season_id,
                season_name,
            )
            # Fall back: find the most recent complete season in DB
            fallback = self._find_most_recent_season()
            if fallback:
                sid, sname = fallback
                matches = self._query_matches(sid, sname)
                if season_id is None:
                    season_id = sid
                if season_name is None:
                    season_name = sname
                logger.info(
                    "Using fallback season %s (%s) with %d matches",
                    sid,
                    sname,
                    len(matches),
                )

        if not matches:
            logger.error("No match data available at all!")
            return self._empty_result(season_id or "", season_name or "", match_day or 0)

        # 3. Compute per-team rates
        team_rates = self._compute_team_rates(matches)

        # 4. Compute matchup (H2H) rates
        matchup_rates = self._compute_matchup_rates(matches)

        # 5. Compute league averages
        league_averages = self._compute_league_averages(matches)

        # 6. Determine data-driven tiers
        tiers_from_data = self._compute_tiers(team_rates)

        generated_at = datetime.now(timezone.utc).isoformat()

        result = {
            "season": season_name or season_id or "",
            "season_id": season_id or "",
            "current_matchday": match_day or 0,
            "generated_at": generated_at,
            "team_rates": team_rates,
            "matchup_rates": matchup_rates,
            "league_averages": league_averages,
            "tiers_from_data": tiers_from_data,
        }

        logger.info(
            "Computed rates: %d teams, %d matchups, %d total matches",
            len(team_rates),
            len(matchup_rates),
            len(matches),
        )

        return result

    def _detect_current_season(
        self,
    ) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        """Detect current season from msport_api or season_tracker fallback.

        Returns:
            (season_id, season_name, match_day)
        """
        # Try msport_api first
        try:
            sys.path.insert(
                0,
                os.path.dirname(os.path.abspath(__file__)),
            )
            from msport_api import get_current_match_day_info

            info = get_current_match_day_info()
            if info:
                sid = info.get("seasonId")
                sname = info.get("seasonName")
                md = info.get("matchDay")
                if sid:
                    logger.info(
                        "Detected current season from API: %s (%s), MD %s",
                        sid,
                        sname,
                        md,
                    )
                    return sid, sname, md
        except Exception as e:
            logger.debug("msport_api not available: %s", e)

        # Fall back to season_tracker.json
        try:
            st_path = SEASON_TRACKER_PATH
            if os.path.exists(st_path):
                with open(st_path, "r") as f:
                    st = json.load(f)
                sid = st.get("current_season_id")
                meta = st.get("current_season_meta", {})
                sname = meta.get("seasonName")
                md = meta.get("matchDay")
                if sid:
                    logger.info(
                        "Detected current season from tracker: %s (%s), MD %s",
                        sid,
                        sname,
                        md,
                    )
                    return sid, sname, md
        except Exception as e:
            logger.debug("season_tracker.json fallback failed: %s", e)

        logger.warning("Could not detect current season from any source")
        return None, None, None

    def _query_matches(
        self,
        season_id: Optional[str],
        season_name: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Query completed matches from history.db for the given season.

        The DB stores seasons in two formats:
            - 'vf:season:NNNNNNN' (API season IDs)
            - 'VFLM NNNN' (human-readable season names)

        We try the season_id first, then season_name.
        """
        if not os.path.exists(self.db_path):
            logger.error("History DB not found: %s", self.db_path)
            return []

        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            matches = []

            # Try exact season_id match
            if season_id:
                cur.execute(
                    """SELECT season, day, home, away, h, a, total, outcome
                       FROM matches
                       WHERE season = ? AND h IS NOT NULL AND outcome IS NOT NULL
                       ORDER BY day, home""",
                    (season_id,),
                )
                matches = [dict(row) for row in cur.fetchall()]

            # Try season_name match
            if not matches and season_name:
                cur.execute(
                    """SELECT season, day, home, away, h, a, total, outcome
                       FROM matches
                       WHERE season = ? AND h IS NOT NULL AND outcome IS NOT NULL
                       ORDER BY day, home""",
                    (season_name,),
                )
                matches = [dict(row) for row in cur.fetchall()]

            # Try 'VFLM NNNN' pattern — extract number from season_name
            if not matches and season_name and season_name.startswith("VFLM "):
                # Also check for numeric-only season values that might match
                num_part = season_name.replace("VFLM ", "").strip()
                if num_part.isdigit():
                    cur.execute(
                        """SELECT season, day, home, away, h, a, total, outcome
                           FROM matches
                           WHERE season = ? AND h IS NOT NULL AND outcome IS NOT NULL
                           ORDER BY day, home""",
                        (num_part,),
                    )
                    matches = [dict(row) for row in cur.fetchall()]

            conn.close()
            return matches

        except sqlite3.Error as e:
            logger.error("SQLite error querying history.db: %s", e)
            return []

    def _find_most_recent_season(self) -> Optional[Tuple[str, str]]:
        """Find the most recent complete season in history.db.

        Returns (season_value, display_name) — e.g. ('VFLM 5047', 'VFLM 5047')
        or ('vf:season:3089669', 'vf:season:3089669').

        Prefers seasons with the most completed matches. When counts are
        tied (e.g. multiple 240-match seasons), picks the most recent one
        by descending name to ensure we use current-era data.
        """
        if not os.path.exists(self.db_path):
            return None

        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()

            # Find VFLM seasons — prefer most matches, then most recent name
            cur.execute(
                """SELECT season, COUNT(*) as cnt
                   FROM matches
                   WHERE h IS NOT NULL AND outcome IS NOT NULL
                     AND season GLOB 'VFLM *'
                   GROUP BY season
                   ORDER BY cnt DESC, season DESC
                   LIMIT 1"""
            )
            row = cur.fetchone()
            if row and row[1] >= 200:
                conn.close()
                season_val = row[0]
                logger.info("Fallback: using VFLM season %s (%d matches)", season_val, row[1])
                return season_val, season_val

            # Fall back to vf:season IDs — prefer most matches, then most recent ID
            cur.execute(
                """SELECT season, COUNT(*) as cnt
                   FROM matches
                   WHERE h IS NOT NULL AND outcome IS NOT NULL
                     AND season GLOB 'vf:*'
                   GROUP BY season
                   ORDER BY cnt DESC, season DESC
                   LIMIT 1"""
            )
            row = cur.fetchone()
            if row and row[1] >= 200:
                conn.close()
                season_val = row[0]
                logger.info("Fallback: using vf:season %s (%d matches)", season_val, row[1])
                return season_val, season_val

            # Last resort: any season with data
            cur.execute(
                """SELECT season, COUNT(*) as cnt
                   FROM matches
                   WHERE h IS NOT NULL AND outcome IS NOT NULL
                   GROUP BY season
                   ORDER BY cnt DESC, season DESC
                   LIMIT 1"""
            )
            row = cur.fetchone()
            if row:
                conn.close()
                logger.info("Fallback: using season %s (%d matches)", row[0], row[1])
                return row[0], row[0]

            conn.close()
            return None

        except sqlite3.Error as e:
            logger.error("SQLite error finding most recent season: %s", e)
            return None

    def _compute_team_rates(
        self,
        matches: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, float]]:
        """Compute per-team statistical rates from match data.

        For each team, aggregates all matches (both home and away) and
        calculates:
            - over_15_rate: fraction with total >= 2
            - under_35_rate: fraction with total < 4
            - avg_goals_scored: average goals scored per match
            - avg_goals_conceded: average goals conceded per match
            - avg_total_goals: average total goals per match
            - btts_rate: both teams to score rate
            - home_avg_goals: average goals scored at home
            - away_avg_goals: average goals scored away
            - sample_size: number of matches used
        """
        # Data structures: team -> list of stat dicts
        team_stats: Dict[str, Dict] = defaultdict(
            lambda: {
                "total_matches": 0,
                "over_15": 0,
                "under_35": 0,
                "goals_scored": 0,
                "goals_conceded": 0,
                "total_goals": 0,
                "btts": 0,
                "home_matches": 0,
                "home_goals": 0,
                "away_matches": 0,
                "away_goals": 0,
            }
        )

        for m in matches:
            home = normalize(m.get("home", ""))
            away = normalize(m.get("away", ""))
            h_goals = m.get("h")
            a_goals = m.get("a")
            total = m.get("total")

            # Sanity check
            if h_goals is None or a_goals is None:
                continue
            h_goals = int(h_goals)
            a_goals = int(a_goals)
            if total is None:
                total = h_goals + a_goals
            else:
                total = int(total)

            # Home team stats
            hs = team_stats[home]
            hs["total_matches"] += 1
            hs["goals_scored"] += h_goals
            hs["goals_conceded"] += a_goals
            hs["total_goals"] += total
            if total >= 2:
                hs["over_15"] += 1
            if total < 4:
                hs["under_35"] += 1
            if h_goals > 0 and a_goals > 0:
                hs["btts"] += 1
            hs["home_matches"] += 1
            hs["home_goals"] += h_goals

            # Away team stats
            as_ = team_stats[away]
            as_["total_matches"] += 1
            as_["goals_scored"] += a_goals
            as_["goals_conceded"] += h_goals
            as_["total_goals"] += total
            if total >= 2:
                as_["over_15"] += 1
            if total < 4:
                as_["under_35"] += 1
            if h_goals > 0 and a_goals > 0:
                as_["btts"] += 1
            as_["away_matches"] += 1
            as_["away_goals"] += a_goals

        # Convert to rates
        team_rates: Dict[str, Dict[str, float]] = {}
        for team, s in team_stats.items():
            n = s["total_matches"]
            if n == 0:
                continue

            home_n = s["home_matches"]
            away_n = s["away_matches"]

            team_rates[team] = {
                "over_15_rate": round(s["over_15"] / n, 4),
                "under_35_rate": round(s["under_35"] / n, 4),
                "avg_goals_scored": round(s["goals_scored"] / n, 4),
                "avg_goals_conceded": round(s["goals_conceded"] / n, 4),
                "avg_total_goals": round(s["total_goals"] / n, 4),
                "btts_rate": round(s["btts"] / n, 4),
                "home_avg_goals": round(s["home_goals"] / home_n, 4) if home_n else 0.0,
                "away_avg_goals": round(s["away_goals"] / away_n, 4) if away_n else 0.0,
                "sample_size": n,
            }

        return team_rates

    def _compute_matchup_rates(
        self,
        matches: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, float]]:
        """Compute head-to-head matchup rates from match data.

        Groups matches by (home, away) pairing and computes rates.
        Key format: 'TEAM1_vs_TEAM2' (ordered alphabetically).
        """
        # We store matchups in a canonical order: alphabetically by team name
        matchup_data: Dict[str, Dict] = defaultdict(
            lambda: {
                "matches": [],
                "total_goals_sum": 0,
                "over_15": 0,
                "under_35": 0,
                "btts": 0,
            }
        )

        for m in matches:
            home = normalize(m.get("home", ""))
            away = normalize(m.get("away", ""))
            h_goals = m.get("h")
            a_goals = m.get("a")
            total = m.get("total")

            if h_goals is None or a_goals is None:
                continue
            h_goals = int(h_goals)
            a_goals = int(a_goals)
            if total is None:
                total = h_goals + a_goals
            else:
                total = int(total)

            # Canonical key: always ALPHABETICAL_vs_OTHER
            teams = sorted([home, away])
            key = f"{teams[0]}_vs_{teams[1]}"

            md = matchup_data[key]
            md["matches"].append(
                {
                    "home": home,
                    "away": away,
                    "h_goals": h_goals,
                    "a_goals": a_goals,
                    "total": total,
                }
            )
            md["total_goals_sum"] += total
            if total >= 2:
                md["over_15"] += 1
            if total < 4:
                md["under_35"] += 1
            if h_goals > 0 and a_goals > 0:
                md["btts"] += 1

        matchup_rates: Dict[str, Dict[str, float]] = {}
        for key, md in matchup_data.items():
            n = len(md["matches"])
            if n == 0:
                continue
            matchup_rates[key] = {
                "over_15_rate": round(md["over_15"] / n, 4),
                "under_35_rate": round(md["under_35"] / n, 4),
                "avg_total_goals": round(md["total_goals_sum"] / n, 4),
                "btts_rate": round(md["btts"] / n, 4),
                "sample_size": n,
            }

        return matchup_rates

    def _compute_league_averages(
        self,
        matches: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Compute league-wide averages from all matches."""
        n = len(matches)
        if n == 0:
            return {
                "avg_total_goals": 0.0,
                "over_15_rate": 0.0,
                "under_35_rate": 0.0,
                "home_win_rate": 0.0,
                "draw_rate": 0.0,
                "away_win_rate": 0.0,
                "avg_home_goals": 0.0,
                "avg_away_goals": 0.0,
                "total_matches": 0,
            }

        total_goals = 0
        over_15 = 0
        under_35 = 0
        home_wins = 0
        draws = 0
        away_wins = 0
        total_home_goals = 0
        total_away_goals = 0

        for m in matches:
            h_goals = m.get("h")
            a_goals = m.get("a")
            outcome = m.get("outcome", "")

            if h_goals is None or a_goals is None:
                continue

            h_goals = int(h_goals)
            a_goals = int(a_goals)
            total = h_goals + a_goals

            total_goals += total
            total_home_goals += h_goals
            total_away_goals += a_goals

            if total >= 2:
                over_15 += 1
            if total < 4:
                under_35 += 1

            outcome_up = outcome.strip().upper()
            if outcome_up == "HOME" or outcome_up == "H":
                home_wins += 1
            elif outcome_up == "AWAY" or outcome_up == "A":
                away_wins += 1
            elif outcome_up == "DRAW" or outcome_up == "D":
                draws += 1

        return {
            "avg_total_goals": round(total_goals / n, 4),
            "over_15_rate": round(over_15 / n, 4),
            "under_35_rate": round(under_35 / n, 4),
            "home_win_rate": round(home_wins / n, 4),
            "draw_rate": round(draws / n, 4),
            "away_win_rate": round(away_wins / n, 4),
            "avg_home_goals": round(total_home_goals / n, 4),
            "avg_away_goals": round(total_away_goals / n, 4),
            "total_matches": n,
        }

    def _compute_tiers(
        self,
        team_rates: Dict[str, Dict[str, float]],
    ) -> Dict[str, List[str]]:
        """Compute data-driven tiers by clustering teams by avg_total_goals.

        Uses avg_total_goals as the primary sorting metric and creates
        4 tiers (T1-T4) with roughly equal teams per tier.
        """
        if not team_rates:
            # Fall back to hardcoded tiers if no data
            return {
                "T1": ["MANCHESTER BLUE", "LIVERPOOL", "MANCHESTER RED", "CHELSEA"],
                "T2": ["TOTTENHAM", "LONDON GUNS", "ASTON VILLA", "WEST HAM"],
                "T3": ["EVERTON", "BRIGHTON", "LEEDS", "WOLVERHAMPTON"],
                "T4": ["NEWCASTLE", "CRYSTAL PALACE", "FULHAM", "BOURNEMOUTH"],
            }

        # Score teams by a composite metric: total goals + goals scored - goals conceded
        # Higher = stronger attacking team
        scored_teams = []
        for team, rates in team_rates.items():
            # Composite score: avg_total_goals is good proxy for entertainment,
            # but for tiers we want team strength.
            # Use avg_goals_scored as primary strength indicator,
            # with avg_total_goals as secondary.
            score = rates.get("avg_goals_scored", 0) * 2 + rates.get("avg_total_goals", 0)
            scored_teams.append((score, team))

        scored_teams.sort(reverse=True)
        sorted_teams = [t for _, t in scored_teams]

        n = len(sorted_teams)
        if n == 0:
            return {}

        # Distribute into 4 tiers
        tier_size = max(1, n // 4)
        tiers = {}
        tier_names = ["T1", "T2", "T3", "T4"]
        for i, tname in enumerate(tier_names):
            start = i * tier_size
            end = start + tier_size if i < 3 else n
            tier_teams = sorted_teams[start:end]
            if tier_teams:
                tiers[tname] = tier_teams

        return tiers

    # ── Internal: serialisation ─────────────────────────────────────────────

    def _from_dict(self, data: Dict[str, Any]):
        """Populate instance attributes from a data dict."""
        self._data = data
        self.season = data.get("season", "")
        self.season_id = data.get("season_id", "")
        self.current_matchday = data.get("current_matchday", 0)
        self.generated_at = data.get("generated_at", "")
        self.team_rates = data.get("team_rates", {})
        self.matchup_rates = data.get("matchup_rates", {})
        self.league_averages = data.get("league_averages", {})
        self.tiers_from_data = data.get("tiers_from_data", {})

    def _save(self, path: str = FEATURE_STORE_PATH):
        """Save current data to JSON file."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self._data, f, indent=2)
        logger.info("Feature store saved to %s", path)

    def _empty_result(
        self,
        season_id: str,
        season_name: str,
        match_day: int,
    ) -> Dict[str, Any]:
        """Return an empty but structured result."""
        return {
            "season": season_name or "",
            "season_id": season_id or "",
            "current_matchday": match_day,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "team_rates": {},
            "matchup_rates": {},
            "league_averages": {
                "avg_total_goals": 0.0,
                "over_15_rate": 0.0,
                "under_35_rate": 0.0,
                "home_win_rate": 0.0,
                "draw_rate": 0.0,
                "away_win_rate": 0.0,
                "avg_home_goals": 0.0,
                "avg_away_goals": 0.0,
                "total_matches": 0,
            },
            "tiers_from_data": {
                "T1": ["MANCHESTER BLUE", "LIVERPOOL", "MANCHESTER RED", "CHELSEA"],
                "T2": ["TOTTENHAM", "LONDON GUNS", "ASTON VILLA", "WEST HAM"],
                "T3": ["EVERTON", "BRIGHTON", "LEEDS", "WOLVERHAMPTON"],
                "T4": ["NEWCASTLE", "CRYSTAL PALACE", "FULHAM", "BOURNEMOUTH"],
            },
        }


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="VFL Feature Store — Rolling Metrics Engine"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Query DB + API, compute rates, and save",
    )
    parser.add_argument(
        "--season",
        type=str,
        default=None,
        help="Specific season ID (e.g. vf:season:3091747)",
    )
    parser.add_argument(
        "--season-name",
        type=str,
        default=None,
        help="Specific season name (e.g. VFLM 5105)",
    )
    parser.add_argument(
        "--match-day",
        type=int,
        default=None,
        help="Current match day (if known)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=HISTORY_DB,
        help=f"Path to history.db (default: {HISTORY_DB})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=FEATURE_STORE_PATH,
        help=f"Output path (default: {FEATURE_STORE_PATH})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging",
    )

    args = parser.parse_args()

    log_level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    store = FeatureStore(db_path=args.db)

    if args.refresh:
        data = store.refresh(
            season_id=args.season,
            season_name=args.season_name,
            match_day=args.match_day,
            save_path=args.output,
        )
        print(json.dumps(data, indent=2))
    else:
        success = store.load(path=args.output)
        if not success:
            print(
                "No saved feature store found. Run with --refresh to compute.",
                file=sys.stderr,
            )
            sys.exit(1)
        # Print summary
        print(f"Season: {store.season} ({store.season_id})")
        print(f"Matchday: {store.current_matchday}")
        print(f"Teams: {len(store.team_rates)}")
        print(f"Matchups: {len(store.matchup_rates)}")
        print(f"League avg total goals: {store.league_avg_total_goals}")
        print(f"League O1.5 rate: {store.league_avg_over_15}")
        print(f"League U3.5 rate: {store.league_avg_under_35}")
        print(f"Generated: {store.generated_at}")


if __name__ == "__main__":
    main()
