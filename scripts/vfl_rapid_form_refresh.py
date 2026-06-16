#!/usr/bin/env python3
"""
vfl_rapid_form_refresh.py — 4-Minute Form Freshness Pipeline
=============================================================
Refreshes team form data from only the most recent completed matchday
(~last 4 minutes of match time).  Designed for high-frequency cron runs
or continuous daemon mode.

Output files (under vfl-complete-data/signals/):
  team_features_rapid.json  — latest snapshot of per-team rates
  form_history.json          — time-series history (capped to 100 entries)

Usage:
    python vfl_rapid_form_refresh.py            # single run (same as --once)
    python vfl_rapid_form_refresh.py --once     # single run for cron
    python vfl_rapid_form_refresh.py --daemon   # continuous polling every 60s

Exit codes:
    0 — success OR soft-fail (API unreachable — cron-friendly)
    1 — unexpected error
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ─── Path setup: import msport_api from same directory ────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from msport_api import get_current_match_day_info, get_results, get_season_list

# ─── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = "/home/ubuntu/faith-workspace/vfl-complete-data"
OUTPUT_FILE = os.path.join(BASE_DIR, "signals", "team_features_rapid.json")
HISTORY_FILE = os.path.join(BASE_DIR, "signals", "form_history.json")

POLL_INTERVAL = 60  # seconds for --daemon mode
HISTORY_CAP = 100   # max entries in form_history.json


# ─── Team name helpers ────────────────────────────────────────────────────────
# Use msport_api's normalisation if available, otherwise fallback to title case.
def _normalise_team_name(name: str) -> str:
    """Normalise a team name to a canonical form."""
    n = name.strip()
    if not n:
        return n
    # Try msport_api's normaliser first
    try:
        from msport_api import _normalise_team_name as api_normalise
        return api_normalise(name)
    except (ImportError, AttributeError):
        pass
    # Fallback: basic title case
    return n.title()


# ─── Core computation ─────────────────────────────────────────────────────────


def compute_team_rates(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Compute per-team rates from a single matchday's result list.

    Returns dict keyed by normalised team name, each entry containing:
        over_1_5_rate, under_3_5_rate, btts_rate, avg_total_goals, matches_analyzed
    """
    # Accumulator: team -> total_goals[], btts_count, match_count
    team_data: Dict[str, Dict[str, Any]] = {}

    for r in results:
        home = _normalise_team_name(r.get("homeTeam", ""))
        away = _normalise_team_name(r.get("awayTeam", ""))
        ft = r.get("fullTime", "0:0")
        try:
            hg, ag = map(int, str(ft).split(":"))
        except (ValueError, AttributeError):
            continue
        if not home or not away:
            continue

        tg = hg + ag  # total goals in this match

        # Each team's perspective
        for team, scored, conceded in [(home, hg, ag), (away, ag, hg)]:
            if team not in team_data:
                team_data[team] = {
                    "total_goals": [],
                    "btts": 0,
                    "match_count": 0,
                }
            team_data[team]["total_goals"].append(tg)
            team_data[team]["match_count"] += 1

        # BTTS: both teams scored
        if hg > 0 and ag > 0:
            for team in [home, away]:
                team_data[team]["btts"] += 1

    # Compute rates from accumulated data
    teams: Dict[str, Dict[str, Any]] = {}
    for team, d in team_data.items():
        n = d["match_count"]
        if n == 0:
            continue

        over_1_5 = sum(1 for tg in d["total_goals"] if tg >= 2) / n
        under_3_5 = sum(1 for tg in d["total_goals"] if tg < 4) / n
        btts_rate = d["btts"] / n
        avg_tg = sum(d["total_goals"]) / n

        teams[team] = {
            "over_1_5_rate": round(over_1_5, 4),
            "under_3_5_rate": round(under_3_5, 4),
            "btts_rate": round(btts_rate, 4),
            "avg_total_goals": round(avg_tg, 2),
            "matches_analyzed": n,
        }

    return teams


def compute_form_direction(
    prev_teams: Dict[str, Dict[str, Any]],
    current_teams: Dict[str, Dict[str, Any]],
) -> Dict[str, str]:
    """Determine form direction ('up'/'down'/'flat') for each team.

    Compares a composite form score between the previous snapshot and the
    current one.  The score weights:
      - over_1_5_rate  (40 %)
      - btts_rate      (30 %)
      - inverse of under_3_5_rate (30 %)
    Higher score = more attacking / exciting form.
    """
    directions: Dict[str, str] = {}

    for team, cur in current_teams.items():
        prev = prev_teams.get(team)
        if prev is None:
            directions[team] = "flat"
            continue

        # Composite score (higher = more attacking)
        def _score(d: Dict[str, Any]) -> float:
            o15 = d.get("over_1_5_rate", 0.5)
            u35 = d.get("under_3_5_rate", 0.5)
            btts = d.get("btts_rate", 0.5)
            return o15 * 0.4 + btts * 0.3 + (1.0 - u35) * 0.3

        cur_score = _score(cur)
        prev_score = _score(prev)

        diff = cur_score - prev_score
        if diff > 0.1:
            directions[team] = "up"
        elif diff < -0.1:
            directions[team] = "down"
        else:
            directions[team] = "flat"

    return directions


# ─── Matchday discovery ───────────────────────────────────────────────────────


def find_latest_completed_matchday() -> Optional[Tuple[str, str, int]]:
    """Find the latest completed matchday.

    Returns (season_id, season_name, match_day) if found, else None.
    Uses the current match day info (latest completed = current - 1),
    falling back to the season list API if the current info is unavailable
    or in pre-season.
    """
    info = get_current_match_day_info()
    if info:
        sid = info.get("seasonId", "")
        season_name = info.get("seasonName", "")
        current_md = info.get("matchDay", 0)

        # Ensure current_md is an integer ≥ 1
        if isinstance(current_md, int) and current_md >= 1:
            completed_md = current_md - 1
            if completed_md >= 1:
                return sid, season_name, completed_md
            # MD 1 is the first — no completed matchdays yet
            # Return (sid, name, 0) so caller knows there's nothing to process
            return sid, season_name, 0

    # Fallback: iterate through available seasons
    try:
        seasons = get_season_list()
        if not seasons:
            return None
        valid = [
            s for s in seasons
            if isinstance(s, dict) and s.get("matchDay") and len(s["matchDay"]) > 0
        ]
        if not valid:
            return None
        # Sort by startTime descending, pick latest
        valid.sort(key=lambda s: s.get("startTime", 0), reverse=True)
        latest = valid[0]
        mds = latest.get("matchDay", [])
        max_md = max(mds) if mds else 0
        if max_md >= 1:
            return latest.get("seasonId", ""), latest.get("seasonName", "?"), max_md
    except Exception:
        pass

    return None


# ─── Persistence ──────────────────────────────────────────────────────────────


def save_snapshot(
    season_id: str,
    match_day: int,
    teams: Dict[str, Dict[str, Any]],
) -> None:
    """Write the current snapshot to team_features_rapid.json."""
    timestamp = datetime.now(timezone.utc).isoformat()
    output = {
        "season_id": season_id,
        "match_day": match_day,
        "captured_at": timestamp,
        "teams": teams,
    }
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)


def append_to_history(
    season_id: str,
    match_day: int,
    teams: Dict[str, Dict[str, Any]],
    match_count: int,
) -> None:
    """Append a time-series entry to form_history.json (capped to 100 entries)."""
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = {
        "season_id": season_id,
        "match_day": match_day,
        "captured_at": timestamp,
        "team_count": len(teams),
        "match_count": match_count,
        "teams": teams,
    }

    history: List[Dict[str, Any]] = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, OSError):
            history = []

    history.append(entry)

    # Cap to HISTORY_CAP entries (oldest first)
    if len(history) > HISTORY_CAP:
        history = history[-HISTORY_CAP:]

    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def load_previous_teams() -> Dict[str, Dict[str, Any]]:
    """Load the teams dict from the previous snapshot, or empty dict."""
    if not os.path.exists(OUTPUT_FILE):
        return {}
    try:
        with open(OUTPUT_FILE) as f:
            prev = json.load(f)
        return prev.get("teams", {})
    except (json.JSONDecodeError, OSError):
        return {}


# ─── Single run ───────────────────────────────────────────────────────────────


def run_once() -> bool:
    """Execute a single form-refresh cycle.

    Returns True if data was refreshed successfully.
    Returns False on soft failure (API unreachable, no data) — the caller
    should exit 0 in this case for cron compatibility.
    """
    # 1. Discover latest completed matchday
    result = find_latest_completed_matchday()
    if result is None:
        print("[NO_DATA] MSport API unreachable")
        return False

    season_id, season_name, match_day = result

    if match_day <= 0:
        print(f"[NO_DATA] No completed matchdays yet for {season_name}")
        return False

    # 2. Fetch results for that matchday
    results = get_results(season_id, match_day)
    if not results or not isinstance(results, list):
        print("[NO_DATA] MSport API unreachable")
        return False

    if len(results) == 0:
        print(f"[NO_DATA] No results available for MD{match_day}")
        return False

    # 3. Compute per-team rates
    teams = compute_team_rates(results)
    if not teams:
        print(f"[NO_DATA] No team data extracted from MD{match_day}")
        return False

    # 4. Load previous snapshot for form_direction comparison
    prev_teams = load_previous_teams()

    # 5. Compute form direction
    directions = compute_form_direction(prev_teams, teams)
    for team in teams:
        teams[team]["form_direction"] = directions.get(team, "flat")

    # 6. Persist snapshot
    save_snapshot(season_id, match_day, teams)

    # 7. Append to history
    append_to_history(season_id, match_day, teams, len(results))

    # 8. Print status line
    timestamp = datetime.now(timezone.utc).isoformat()
    print(
        f"Form refreshed: {len(teams)} teams, {len(results)} matches, "
        f"MD{match_day}, {timestamp}"
    )
    return True


# ─── Main entry ───────────────────────────────────────────────────────────────


def main() -> int:
    args = set(sys.argv[1:])

    is_daemon = "--daemon" in args
    is_once = "--once" in args or not is_daemon  # default to single-run

    if is_daemon:
        # Continuous polling mode
        while True:
            success = run_once()
            interval = POLL_INTERVAL if success else 10  # shorter wait on failure
            time.sleep(interval)
        # (never reached)
    else:
        # Single run mode (--once or no args)
        success = run_once()
        if not success:
            # Soft fail for cron — exit 0 so cron doesn't alert
            sys.exit(0)
        return 0


if __name__ == "__main__":
    sys.exit(main())
