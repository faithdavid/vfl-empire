#!/usr/bin/env python3
"""
VFL Season Tracker — SQLite-backed season tracking.
====================================================
Queries the existing vfl_results.db and vfl_odds.db databases
for league tables, H2H, team form, and pre-match odds data.

The databases are populated by vfl_season_ingester.py (every 30 min).

Key functions:
  - TeamTracker.get_team_form(team, season_id, last_n=5)
  - TeamTracker.get_team_avg_goals(team, season_id, last_n=5)
  - TeamTracker.get_h2h(team1, team2, season_id)
  - TeamTracker.build_league_table(season_id)
  - TeamTracker.get_pre_odds(event_id) — pre-match odds for a fixture
  - TeamTracker.store_pre_odds(season_id, match_day, fixtures) — capture before MD runs

Usage:
  from season_tracker import TeamTracker
  tracker = TeamTracker()
  table = tracker.build_league_table("vf:season:3091747")
  form = tracker.get_team_form("Liverpool", "vf:season:3091747")
  odds = tracker.get_pre_odds("vf:match:1402891166")
"""

import json
import sqlite3
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
WORKSPACE = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
RESULTS_DB = WORKSPACE / "databases" / "vfl_results.db"
ODDS_DB = WORKSPACE / "databases" / "vfl_odds.db"
PRE_ODDS_CACHE = WORKSPACE / "analysis" / "pre_odds_cache.json"

# ── Team Name Normalisation ───────────────────────────────────────────────────
TEAM_ALIASES = {
    "MANCHESTER RED": "Manchester Red", "MANCHESTER BLUE": "Manchester Blue",
    "MANCHESTER CITY": "Manchester Blue", "MANCHESTER UNITED": "Manchester Red",
    "LONDON GUNS": "London Guns", "LONDON GUNNERS": "London Guns",
    "ARSENAL": "London Guns", "CHELSEA": "Chelsea", "LIVERPOOL": "Liverpool",
    "ASTON VILLA": "Aston Villa", "TOTTENHAM": "Tottenham",
    "EVERTON": "Everton", "WOLVERHAMPTON": "Wolverhampton",
    "NEWCASTLE": "Newcastle", "LEEDS": "Leeds",
    "FULHAM": "Fulham", "WEST HAM": "West Ham",
    "BOURNEMOUTH": "Bournemouth", "BRIGHTON": "Brighton",
    "CRYSTAL PALACE": "Crystal Palace",
}

def normalize(name: str) -> str:
    """Normalise team name."""
    n = name.strip().upper()
    return TEAM_ALIASES.get(n, name.strip().title())


class TeamTracker:
    """Season tracker backed by existing SQLite databases."""

    def __init__(self):
        self._r_conn = None
        self._o_conn = None

    def _r(self):
        if self._r_conn is None:
            self._r_conn = sqlite3.connect(str(RESULTS_DB))
            self._r_conn.row_factory = sqlite3.Row
        return self._r_conn

    def _o(self):
        if self._o_conn is None:
            self._o_conn = sqlite3.connect(str(ODDS_DB))
            self._o_conn.row_factory = sqlite3.Row
        return self._o_conn

    def close(self):
        if self._r_conn: self._r_conn.close()
        if self._o_conn: self._o_conn.close()

    # ── League Table ────────────────────────────────────────────────────────

    def build_league_table(self, season_id: str) -> list:
        """Build sorted league table for a season from results DB."""
        cur = self._r().execute(
            "SELECT * FROM results WHERE season_id = ?", (season_id,)
        )
        rows = cur.fetchall()
        if not rows:
            return []

        teams = {}
        for r in rows:
            for side in ["home_team", "away_team"]:
                t = normalize(r[side])
                if t not in teams:
                    teams[t] = {"team": t, "played": 0, "wins": 0, "draws": 0,
                                "losses": 0, "goals_for": 0, "goals_against": 0,
                                "gd": 0, "points": 0, "form": []}

            home = normalize(r["home_team"])
            away = normalize(r["away_team"])
            hg = r["home_goals"]
            ag = r["away_goals"]

            teams[home]["played"] += 1
            teams[away]["played"] += 1
            teams[home]["goals_for"] += hg
            teams[home]["goals_against"] += ag
            teams[away]["goals_for"] += ag
            teams[away]["goals_against"] += hg

            if hg > ag:
                teams[home]["wins"] += 1
                teams[home]["points"] += 3
                teams[away]["losses"] += 1
                teams[home]["form"].append("W")
                teams[away]["form"].append("L")
            elif ag > hg:
                teams[away]["wins"] += 1
                teams[away]["points"] += 3
                teams[home]["losses"] += 1
                teams[home]["form"].append("L")
                teams[away]["form"].append("W")
            else:
                teams[home]["draws"] += 1
                teams[away]["draws"] += 1
                teams[home]["points"] += 1
                teams[away]["points"] += 1
                teams[home]["form"].append("D")
                teams[away]["form"].append("D")

        table = []
        for t, d in teams.items():
            d["gd"] = d["goals_for"] - d["goals_against"]
            d["form_str"] = "".join(d["form"][-5:])
            d.pop("form", None)
            table.append(d)

        table.sort(key=lambda x: (-x["points"], -x["gd"], -x["goals_for"]))
        return table

    # ── Team Form ──────────────────────────────────────────────────────────

    def get_team_form(self, team: str, season_id: str = None, last_n: int = 5) -> list:
        """Get recent match results for a team.
        If season_id is None, queries across ALL seasons (cross-season mode)."""
        team_n = normalize(team)
        if season_id is None:
            # Cross-season: no season filter
            cur = self._r().execute(
                """SELECT * FROM results 
                   WHERE (home_team = ? OR away_team = ?)
                   ORDER BY captured_at DESC LIMIT ?""",
                (team_n, team_n, last_n)
            )
        else:
            cur = self._r().execute(
                """SELECT * FROM results 
                   WHERE season_id = ? AND (home_team = ? OR away_team = ?)
                   ORDER BY match_day DESC LIMIT ?""",
                (season_id, team_n, team_n, last_n)
            )
        results = []
        for r in cur.fetchall():
            home = normalize(r["home_team"])
            away = normalize(r["away_team"])
            is_home = (home == team_n)
            opponent = away if is_home else home
            hg, ag = r["home_goals"], r["away_goals"]
            if is_home:
                outcome = "W" if hg > ag else ("D" if hg == ag else "L")
                scored, conceded = hg, ag
            else:
                outcome = "W" if ag > hg else ("D" if ag == hg else "L")
                scored, conceded = ag, hg
            results.append({
                "match_day": r["match_day"],
                "opponent": opponent,
                "home": is_home,
                "score": f"{hg}-{ag}",
                "scored": scored,
                "conceded": conceded,
                "outcome": outcome,
            })
        return results

    # ── Mode B: Continuous Cross-Season Form ───────────────────────────────

    def get_team_form_continuous(self, team: str, last_n: int = 15) -> list:
        """Cross-season form — no season_id filter, uses all history.
        Mode B: get_team_form(team, season_id=None, last_n=15) via the existing
        SQL path that omits the season filter when season_id is None."""
        return self.get_team_form(team, None, last_n)

    def get_team_avg_goals_continuous(self, team: str, last_n: int = 15) -> dict:
        """Cross-season avg goals (no season filter)."""
        return self.get_team_avg_goals(team, None, last_n)

    # ── Mode C: Regime-Aware Form ─────────────────────────────────────────

    def classify_current_regime(self, window: int = 500) -> dict:
        """Classify the current VFL engine regime using the last N matches."""
        cur = self._r().execute(
            "SELECT total_goals FROM results WHERE total_goals IS NOT NULL "
            "ORDER BY captured_at DESC LIMIT ?", (window,)
        )
        rows = cur.fetchall()
        n = len(rows)
        if n < 50:
            return {"regime": "STANDARD", "avg_goals": 0, "n": n}
        total = sum(r["total_goals"] for r in rows if r["total_goals"] is not None)
        avg = total / n if n else 0
        if avg < 1.7:
            regime = "DEFENSIVE"
        elif avg >= 2.0:
            regime = "OFFENSIVE"
        else:
            regime = "STANDARD"
        return {"regime": regime, "avg_goals": round(avg, 4), "n": n}

    def _compute_match_regime_labels(self) -> dict:
        """Precompute regime label for every match using a rolling 500-match
        window. Returns dict: event_id -> regime_label."""
        cur = self._r().execute(
            "SELECT event_id, total_goals FROM results "
            "WHERE total_goals IS NOT NULL ORDER BY captured_at ASC"
        )
        all_rows = cur.fetchall()
        labels = {}
        n = len(all_rows)
        if n < 600:
            # Not enough data for rolling window — just use current regime
            cur_reg = self.classify_current_regime()
            label = cur_reg["regime"]
            for r in all_rows:
                labels[r["event_id"]] = label
            return labels

        # Sliding window: for each match at position i (0-indexed),
        # look at the 500 matches BEFORE it (indices max(0,i-500) .. i-1)
        goals = [r["total_goals"] for r in all_rows]
        ids = [r["event_id"] for r in all_rows]

        # Pre-compute prefix sums for O(1) window averages
        prefix = [0]
        for g in goals:
            prefix.append(prefix[-1] + g)

        for i in range(n):
            event_id = ids[i]
            window_start = max(0, i - 500)
            window_size = i - window_start
            if window_size < 50:
                labels[event_id] = "STANDARD"
                continue
            total_g = prefix[i] - prefix[window_start]
            avg = total_g / window_size
            if avg < 1.7:
                labels[event_id] = "DEFENSIVE"
            elif avg >= 2.0:
                labels[event_id] = "OFFENSIVE"
            else:
                labels[event_id] = "STANDARD"
        return labels

    def get_team_form_regime_aware(self, team: str, last_n: int = 15) -> list:
        """Get team form filtered by regime compatibility.
        Mode C: Only matches played under the same engine regime as the current
        matchday are included. Uses rolling 500-match window classification."""
        team_n = normalize(team)

        # Determine current regime
        cur_regime = self.classify_current_regime()
        target_regime = cur_regime["regime"]

        # Precompute regime labels for all matches (cached)
        if not hasattr(self, '_regime_labels'):
            self._regime_labels = self._compute_match_regime_labels()

        # Get ALL matches for this team across all seasons, ordered by recency
        cur = self._r().execute(
            "SELECT * FROM results "
            "WHERE (home_team = ? OR away_team = ?) "
            "ORDER BY captured_at DESC",
            (team_n, team_n)
        )
        all_matches = cur.fetchall()

        # Filter to only matches whose regime matches the current regime
        matching = []
        for r in all_matches:
            label = self._regime_labels.get(r["event_id"], "STANDARD")
            if label == target_regime:
                matching.append(r)
                if len(matching) >= last_n:
                    break

        # Format results identically to get_team_form
        results = []
        for r in matching:
            home = normalize(r["home_team"])
            away = normalize(r["away_team"])
            is_home = (home == team_n)
            opponent = away if is_home else home
            hg, ag = r["home_goals"], r["away_goals"]
            if is_home:
                outcome = "W" if hg > ag else ("D" if hg == ag else "L")
                scored, conceded = hg, ag
            else:
                outcome = "W" if ag > hg else ("D" if ag == hg else "L")
                scored, conceded = ag, hg
            results.append({
                "match_day": r["match_day"],
                "opponent": opponent,
                "home": is_home,
                "score": f"{hg}-{ag}",
                "scored": scored,
                "conceded": conceded,
                "outcome": outcome,
            })
        return results

    def get_team_avg_goals(self, team: str, season_id: str = None, last_n: int = 5) -> dict:
        """Get average goals scored/conceded for a team."""
        form = self.get_team_form(team, season_id, last_n)
        if not form:
            return {"avg_scored": 0, "avg_conceded": 0, "avg_total": 0, "n": 0}
        n = len(form)
        scored = sum(m["scored"] for m in form)
        conceded = sum(m["conceded"] for m in form)
        return {
            "avg_scored": round(scored / n, 2),
            "avg_conceded": round(conceded / n, 2),
            "avg_total": round((scored + conceded) / n, 2),
            "n": n,
        }

    def get_team_performance_summary(self, team: str, season_id: str) -> dict:
        """Full team profile: position, stats, form, avg goals."""
        table = self.build_league_table(season_id)
        team_n = normalize(team)
        pos = next((i+1 for i, t in enumerate(table) if t["team"] == team_n), None)
        row = next((t for t in table if t["team"] == team_n), None)
        goals = self.get_team_avg_goals(team, season_id, 5)
        return {
            "team": team_n,
            "position": pos,
            "stats": row,
            "recent_goals": goals,
            "form": row["form_str"] if row else "",
        }

    # ── H2H ────────────────────────────────────────────────────────────────

    def get_h2h(self, team1: str, team2: str, season_id: str = None) -> dict:
        """Get head-to-head record between two teams."""
        t1, t2 = normalize(team1), normalize(team2)
        query = """SELECT * FROM results 
                   WHERE (home_team = ? AND away_team = ?)
                      OR (home_team = ? AND away_team = ?)"""
        params = [t1, t2, t2, t1]
        if season_id:
            query += " AND season_id = ?"
            params.append(season_id)
        query += " ORDER BY match_day"

        cur = self._r().execute(query, params)
        meetings = []
        for r in cur.fetchall():
            home = normalize(r["home_team"])
            hg, ag = r["home_goals"], r["away_goals"]
            meetings.append({
                "match_day": r["match_day"],
                "season": r["season_name"],
                "home": home,
                "away": normalize(r["away_team"]),
                "home_goals": hg,
                "away_goals": ag,
                "total_goals": hg + ag,
                "outcome": "H" if hg > ag else ("A" if ag > hg else "D"),
                "gg": 1 if (hg > 0 and ag > 0) else 0,
            })

        if not meetings:
            return {"meetings": [], "total": 0, "avg_goals": 0, "btts_pct": 0}

        total_goals = sum(m["total_goals"] for m in meetings)
        btts = sum(m["gg"] for m in meetings)
        return {
            "meetings": meetings,
            "total": len(meetings),
            "avg_goals": round(total_goals / len(meetings), 2),
            "btts_pct": round(btts / len(meetings) * 100, 1),
        }

    # ── Pre-Match Odds ─────────────────────────────────────────────────────

    def store_pre_odds(self, season_id: str, match_day: int, fixtures: list):
        """
        Save pre-match odds for upcoming fixtures.
        Called BEFORE the matchday runs to capture what odds were available.
        fixtures = list of dicts with keys: event_id, home, away, odds dict
        """
        cache = {}
        if PRE_ODDS_CACHE.exists():
            try:
                cache = json.loads(PRE_ODDS_CACHE.read_text())
            except:
                pass

        key = f"{season_id}|MD{match_day}"
        cache[key] = {
            "season_id": season_id,
            "match_day": match_day,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "fixtures": fixtures,
        }
        PRE_ODDS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PRE_ODDS_CACHE.write_text(json.dumps(cache, indent=2, default=str))

    def get_pre_odds(self, event_id: str) -> dict:
        """Get pre-match odds for a specific event from the odds DB."""
        # Check odds_history first
        cur = self._o().execute(
            "SELECT * FROM odds_history WHERE event_id = ? ORDER BY captured_at DESC LIMIT 1",
            (event_id,)
        )
        row = cur.fetchone()
        if row:
            return dict(row)

        # Fall back to deep_markets
        cur = self._o().execute(
            "SELECT * FROM deep_markets WHERE event_id = ?", (event_id,)
        )
        markets = cur.fetchall()
        if markets:
            result = {"event_id": event_id, "markets": []}
            for m in markets:
                result["markets"].append({
                    "market": m["market_name"],
                    "specifier": m["specifiers"],
                    "selection": m["selection_name"],
                    "odds": m["odds"],
                })
            return result

        return {}

    def get_md_pre_odds(self, season_id: str, match_day: int) -> list:
        """Get pre-match odds for an entire matchday from cache."""
        cache = {}
        if PRE_ODDS_CACHE.exists():
            try:
                cache = json.loads(PRE_ODDS_CACHE.read_text())
            except:
                pass
        return cache.get(f"{season_id}|MD{match_day}", {}).get("fixtures", [])

    # ── Historical Query ──────────────────────────────────────────────────

    def get_all_seasons(self) -> list:
        """List all seasons with data."""
        cur = self._r().execute(
            "SELECT DISTINCT season_id, season_name FROM results ORDER BY season_name DESC"
        )
        return [{"id": r["season_id"], "name": r["season_name"]} for r in cur.fetchall()]

    def season_matches(self, season_id: str) -> list:
        """Get all matches for a season."""
        cur = self._r().execute(
            "SELECT * FROM results WHERE season_id = ? ORDER BY match_day",
            (season_id,)
        )
        return [dict(r) for r in cur.fetchall()]


def main():
    """CLI entry: print league table for current season."""
    tracker = TeamTracker()
    seasons = tracker.get_all_seasons()
    if not seasons:
        print("No seasons found in database.")
        return

    latest = seasons[0]
    print(f"📅 {latest['name']} ({latest['id']})")
    table = tracker.build_league_table(latest["id"])

    print(f"\n{'#':<3} {'Team':<22} {'P':<4} {'W':<4} {'D':<4} {'L':<4} "
          f"{'GF':<4} {'GA':<4} {'GD':<5} {'Pts':<5} {'F5':<8}")
    print("-" * 70)
    for i, row in enumerate(table, 1):
        print(f"{i:<3} {row['team']:<22} {row['played']:<4} {row['wins']:<4} "
              f"{row['draws']:<4} {row['losses']:<4} {row['goals_for']:<4} "
              f"{row['goals_against']:<4} {row['gd']:<+4} {row['points']:<5} "
              f"{row.get('form_str', ''):<8}")

    # Show H2H example
    print(f"\n⚔️ H2H Chelsea vs Fulham:")
    h2h = tracker.get_h2h("Chelsea", "Fulham", latest["id"])
    for m in h2h.get("meetings", []):
        print(f"   MD{m['match_day']:>2}: {m['home']} {m['home_goals']}-{m['away_goals']} {m['away']}")

    # Show a team performance
    print(f"\n📊 Top team: {table[0]['team']}")
    form = tracker.get_team_form(table[0]["team"], latest["id"], 5)
    for m in form:
        print(f"   {m['outcome']} vs {m['opponent']} ({m['score']})")

    tracker.close()


if __name__ == "__main__":
    main()
