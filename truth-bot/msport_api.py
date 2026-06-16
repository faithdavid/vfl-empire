#!/usr/bin/env python3
"""
msport_api.py — Robust MSport API interaction module.
Provides functions for all known JSON endpoints with error handling,
retry logic, and standardised data extraction.

Endpoints:
  - /virtual/current/match/day/info        (current season info)
  - /virtual/event/list?sportId=vf:sport:1  (upcoming fixtures + odds)
  - /virtual/result?seasonId=X&matchDay=Y   (completed results)
  - /virtual/result/season/selection        (available seasons)
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────
BASE_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual"
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_DELAY = 1.5

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "operId": "2",
    "operid": "2",
    "clientid": "WEB",
    "platform": "WEB",
    "apilevel": "2",
    "Referer": "https://www.msport.com/ng/virtual/soccer",
    "Origin": "https://www.msport.com",
}

# ─── Device ID helpers ────────────────────────────────────────────────────────


def _get_device_id(device_id: Optional[str] = None) -> str:
    """Resolve deviceId: explicit arg > MSPORT_DEVICE_ID env var > random UUID."""
    if device_id:
        return device_id
    env_id = os.environ.get("MSPORT_DEVICE_ID")
    if env_id:
        return env_id
    return str(uuid.uuid4())


# ─── Cookie support for authenticated write operations ────────────────────────

_COOKIE: Optional[str] = None


def set_cookie(cookie: str) -> None:
    """Set the session cookie used for authenticated write requests.

    Call once during application initialisation with a valid ``Cookie``
    header value (e.g. ``'PHPSESSID=abc123; ...'``).  The cookie is then
    attached to every subsequent request made via :func:`fetch_json`.
    """
    global _COOKIE
    _COOKIE = cookie
    logger.info("Session cookie set (%d chars)", len(cookie))


def load_cookie_from_env(var_name: str = "MSPORT_COOKIE") -> Optional[str]:
    """Load and set the session cookie from an environment variable.

    Returns the cookie value (or ``None`` if the variable is not set).
    """
    cookie = os.environ.get(var_name)
    if cookie:
        set_cookie(cookie)
    return cookie

# ─── Core fetch function ────────────────────────────────────────────────────


def _make_headers(
    extra: Optional[Dict[str, str]] = None,
    device_id: Optional[str] = None,
) -> Dict[str, str]:
    """Build request headers with resolved deviceId and optional cookie.

    Parameters
    ----------
    extra : optional
        Additional headers to merge (overrides defaults).
    device_id : optional
        Explicit device ID.  If omitted falls back to the ``MSPORT_DEVICE_ID``
        env var, then to a random UUID.
    """
    h = dict(DEFAULT_HEADERS)
    h["deviceid"] = _get_device_id(device_id)
    if _COOKIE:
        h["Cookie"] = _COOKIE
    if extra:
        h.update(extra)
    return h


def fetch_json(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = MAX_RETRIES,
    device_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetch a URL and parse the JSON response.
    Returns parsed dict on success, None on failure.
    Retries up to `retries` times on transient errors.
    """
    if headers is None:
        headers = _make_headers(device_id=device_id)

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=timeout)
            body = resp.read().decode("utf-8")
            data = json.loads(body)

            # Check bizCode for API-level errors
            biz = data.get("bizCode", 10000)
            if biz != 10000:
                msg = data.get("message", "unknown API error")
                logger.warning("API bizCode=%s msg=%s (attempt %d/%d)", biz, msg, attempt, retries)
                if attempt < retries:
                    time.sleep(RETRY_DELAY)
                    continue
                return None

            return data

        except HTTPError as e:
            last_error = e
            logger.debug("HTTP %d fetching %s (attempt %d/%d)", e.code, url, attempt, retries)
            if e.code in (429, 503, 502, 504) and attempt < retries:
                time.sleep(RETRY_DELAY * attempt)
                continue
            return None

        except (URLError, OSError, json.JSONDecodeError, ConnectionError) as e:
            last_error = e
            logger.debug("Req error fetching %s (attempt %d/%d): %s", url, attempt, retries, e)
            if attempt < retries:
                time.sleep(RETRY_DELAY)
                continue
            return None

    logger.error("All %d retries failed for %s: %s", retries, url, last_error)
    return None


# ─── Endpoint-specific functions ────────────────────────────────────────────


def get_current_match_day_info() -> Optional[Dict[str, Any]]:
    """
    Fetch current match day info.
    Returns dict with keys: seasonId, seasonName, matchDay, status,
    seasonStartTime, seasonEndTime, matchDayStartTime.
    Returns None on failure.
    """
    url = f"{BASE_URL}/current/match/day/info"
    data = fetch_json(url)
    if data is None:
        return None
    return data.get("data")


def get_event_list() -> Optional[List[Dict[str, Any]]]:
    """
    Fetch upcoming events/fixtures with full odds data.
    Returns list of matchDay entries, each containing events with markets.
    Returns None on failure.
    """
    url = f"{BASE_URL}/event/list?sportId=vf:sport:1"
    data = fetch_json(url)
    if data is None:
        return None
    match_days = data.get("data", {}).get("matchDays", [])
    return match_days if match_days else []


def get_results(season_id: str, match_day: int) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch completed results for a given season + match day.
    Returns list of result dicts (each with homeTeam, awayTeam, fullTime, etc.)
    Returns None on failure.
    """
    url = f"{BASE_URL}/result?seasonId={season_id}&matchDay={match_day}"
    data = fetch_json(url)
    if data is None:
        return None
    return data.get("data", {}).get("results")


def get_season_list() -> Optional[List[Dict[str, Any]]]:
    """
    Fetch available seasons (for result browsing).
    Returns list of season dicts.
    """
    url = f"{BASE_URL}/result/season/selection"
    data = fetch_json(url)
    if data is None:
        return None
    raw = data.get("data", [])
    if isinstance(raw, list):
        return raw
    return []


def get_event_detail(event_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch deep market data for a specific event.
    Returns None if not found/available.
    """
    url = f"{BASE_URL}/event/detail?eventId={event_id}"
    data = fetch_json(url)
    if data is None:
        return None
    return data.get("data")


def get_standings() -> Optional[Dict[str, Any]]:
    """
    Fetch the current league table / standings.

    Returns dict with keys: seasonName, matchDay, teams (list of team dicts).
    Returns None on failure.
    """
    url = f"{BASE_URL}/table"
    data = fetch_json(url)
    if data is None:
        return None
    return data.get("data")


# ─── Team name normalisation (TEAM_ALIASES pattern) ─────────────────────────

# Central alias map matching the convention used across the codebase.
TEAM_ALIASES = {
    "MANCHESTER BLUE": "Manchester Blue",
    "MANCHESTER RED": "Manchester Red",
    "LIVERPOOL": "Liverpool",
    "CHELSEA": "Chelsea",
    "LONDON GUNS": "London Guns",
    "TOTTENHAM": "Tottenham",
    "ASTON VILLA": "Aston Villa",
    "WEST HAM": "West Ham",
    "EVERTON": "Everton",
    "WOLVERHAMPTON": "Wolverhampton",
    "BRIGHTON": "Brighton",
    "NEWCASTLE": "Newcastle",
    "LEEDS": "Leeds",
    "CRYSTAL PALACE": "Crystal Palace",
    "FULHAM": "Fulham",
    "BOURNEMOUTH": "Bournemouth",
}


def _normalise_team_name(name: str) -> str:
    """Normalise a team name using the TEAM_ALIASES map."""
    return TEAM_ALIASES.get(name.strip().upper(), name.strip().title())


def extract_standings_table(data: dict) -> list:
    """
    Extract and normalise a sorted standings table from the API data dict.

    Expects ``data`` to be the dict returned by ``get_standings()`` (i.e. the
    ``data`` payload containing *seasonName*, *matchDay*, and *teams*).

    Normalises team names via the ``TEAM_ALIASES`` map, calculates goal
    difference, and returns a list of dicts sorted by rank, each with
    standardised keys::

        teamName, rank, points, won, draw, lost,
        goalsFor, goalsAgainst, goalDifference, rankChange, lastFive

    Returns an empty list on missing/invalid data.
    """
    teams_raw = data.get("teams", []) if isinstance(data, dict) else []
    rows = []
    for t in teams_raw:
        if not isinstance(t, dict):
            continue
        gf = int(t.get("score", 0))
        ga = int(t.get("lostScore", 0))
        rows.append({
            "teamName": _normalise_team_name(t.get("teamName", "")),
            "rank": int(t.get("rank", 0)),
            "points": int(t.get("points", 0)),
            "won": int(t.get("won", 0)),
            "draw": int(t.get("draw", 0)),
            "lost": int(t.get("lost", 0)),
            "goalsFor": gf,
            "goalsAgainst": ga,
            "goalDifference": gf - ga,
            "rankChange": t.get("rankChange", ""),
            "lastFive": t.get("lastFive", []),
        })
    rows.sort(key=lambda r: r["rank"])
    return rows


# ─── Convenience extractors ─────────────────────────────────────────────────


def extract_1x2_odds(event: Dict[str, Any]) -> Dict[str, float]:
    """
    Extract 1X2 (Home/Draw/Away) odds from an event's markets.
    Returns {'Home': float, 'Draw': float, 'Away': float}.
    Missing values default to 0.0.
    """
    result = {"Home": 0.0, "Draw": 0.0, "Away": 0.0}
    for market in event.get("markets", []):
        if market.get("id") == 1:
            for outcome in market.get("outcomes", []):
                desc = outcome.get("description", "").strip()
                odds = float(outcome.get("odds", 0))
                if desc in result:
                    result[desc] = odds
            break
    return result


def extract_over_under_odds(event: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """
    Extract Over/Under odds from an event's markets.
    Returns dict keyed by specifier, e.g.:
    {'total=1.5': {'Over': 1.5, 'Under': 2.1}, 'total=2.5': {...}, 'total=3.5': {...}}
    """
    result = {}
    for market in event.get("markets", []):
        spec = market.get("specifiers", "")
        if not spec.startswith("total="):
            continue
        outcomes = {}
        for outcome in market.get("outcomes", []):
            desc = outcome.get("description", "").strip()
            odds = float(outcome.get("odds", 0))
            outcomes[desc] = odds
        if outcomes:
            result[spec] = outcomes
    return result


def extract_double_chance_odds(event: Dict[str, Any]) -> Dict[str, float]:
    """
    Extract Double Chance odds (HomeOrDraw, HomeOrAway, DrawOrAway).
    Market ID for double chance varies; we search by specifier 'home='.
    Returns dict like {'HomeOrDraw': 1.2, ...}
    """
    result = {}
    for market in event.get("markets", []):
        spec = market.get("specifiers", "")
        if "home=" in spec:
            for outcome in market.get("outcomes", []):
                desc = outcome.get("description", "").strip()
                odds = float(outcome.get("odds", 0))
                result[desc] = odds
    return result


def extract_all_markets(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract ALL markets from an event into a structured dict.
    Useful for comprehensive analysis.
    """
    return {
        "1x2": extract_1x2_odds(event),
        "over_under": extract_over_under_odds(event),
        "double_chance": extract_double_chance_odds(event),
        "event_id": event.get("eventId"),
        "home_team": event.get("homeTeam"),
        "away_team": event.get("awayTeam"),
    }


def find_upcoming_match_day(
    match_days: List[Dict[str, Any]],
    min_seconds: int = 60,
) -> Optional[Dict[str, Any]]:
    """
    Find the next upcoming match day from the event list.
    Filters out match days starting in < `min_seconds`.
    Returns the first suitable matchDay entry or None.
    """
    now = datetime.now(timezone.utc)
    for md in match_days:
        ts = md.get("matchDayStartTime", 0) / 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        secs = int((dt - now).total_seconds())
        if secs >= min_seconds:
            return md
    return None


# ─── Standings / League Table ────────────────────────────────────────────────


def get_standings(season_id: Optional[str] = None, match_day: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch current standings for the active (or given) season.
    
    Args:
        season_id: If provided, fetch standings for that specific season.
                   If None, uses the current active season.
        match_day: If provided, use this match day number instead of
                   fetching from current match day info. Required when
                   the current season is in PRE_SEASON (matchDay=null).
    
    Returns a dict with keys: seasonId, seasonName, matchDay, total_matches,
    standings (list of team dicts sorted by rank).
    """
    # Resolve season / current match day
    if season_id is None:
        info = get_current_match_day_info()
        if not info:
            logger.error("get_standings: could not get current match day info")
            return None
        sid = info.get("seasonId", "")
        season_name = info.get("seasonName", "")
        # When match_day is passed (e.g. X-2 for tier calc), use it as the cutoff.
        current_md = match_day if match_day is not None else info.get("matchDay", 0)
    else:
        sid = season_id
        season_name = sid
        current_md = match_day
        if current_md is None:
            # Try to find the max matchday for this season from the season list
            try:
                seasons = get_season_list() or []
                for s in seasons:
                    if s.get("seasonId") == sid:
                        mds = s.get("matchDay", [])
                        if mds:
                            current_md = max(mds)
                        break
            except Exception:
                pass

    if not sid or current_md is None or current_md == 0:
        logger.error("get_standings: invalid season_id=%s or matchDay=%s", sid, current_md)
        return None

    # Column accumulation per team
    # key: teamName (raw from API), value: stats dict
    from collections import defaultdict
    col = defaultdict(lambda: {
        "played": 0, "won": 0, "draw": 0, "lost": 0,
        "goalsFor": 0, "goalsAgainst": 0,
        "lastFive": []  # list of "W"/"D"/"L" strings
    })

    total_matches = 0
    for md in range(1, current_md + 1):
        results = get_results(sid, md)
        if not results or not isinstance(results, list):
            continue
        total_matches += len(results)
        for r in results:
            home = r.get("homeTeam", "").strip()
            away = r.get("awayTeam", "").strip()
            ft = r.get("fullTime", "0:0")
            try:
                hg, ag = map(int, str(ft).split(":"))
            except (ValueError, AttributeError):
                continue
            if not home or not away:
                continue

            # Home team stats
            col[home]["played"] += 1
            col[home]["goalsFor"] += hg
            col[home]["goalsAgainst"] += ag
            # Away team stats
            col[away]["played"] += 1
            col[away]["goalsFor"] += ag
            col[away]["goalsAgainst"] += hg

            if hg > ag:
                col[home]["won"] += 1
                col[home]["lastFive"].append("W")
                col[away]["lost"] += 1
                col[away]["lastFive"].append("L")
            elif ag > hg:
                col[away]["won"] += 1
                col[away]["lastFive"].append("W")
                col[home]["lost"] += 1
                col[home]["lastFive"].append("L")
            else:
                col[home]["draw"] += 1
                col[home]["lastFive"].append("D")
                col[away]["draw"] += 1
                col[away]["lastFive"].append("D")

    if not col:
        logger.warning("get_standings: no teams accumulated for season %s", sid)
        return None

    # Build and sort standings
    standings_list = []
    for team_name, s in col.items():
        gd = s["goalsFor"] - s["goalsAgainst"]
        pts = s["won"] * 3 + s["draw"]
        standings_list.append({
            "teamName": team_name,
            "points": pts,
            "played": s["played"],
            "won": s["won"],
            "draw": s["draw"],
            "lost": s["lost"],
            "goalsFor": s["goalsFor"],
            "goalsAgainst": s["goalsAgainst"],
            "goalDifference": gd,
            "lastFive": s["lastFive"][-5:],  # keep only last 5
            "form": list(s["lastFive"][-5:]),
        })

    # Sort: points desc, GD desc, GF desc
    standings_list.sort(key=lambda x: (-x["points"], -x["goalDifference"], -x["goalsFor"]))

    # Assign rank
    for i, entry in enumerate(standings_list, 1):
        entry["rank"] = i

    return {
        "seasonId": sid,
        "seasonName": season_name,
        "matchDay": current_md,
        "total_matches": total_matches,
        "standings": standings_list,
    }


def extract_standings_table(
    standings_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Extract the ordered list of team dicts from a get_standings() response."""
    if not isinstance(standings_data, dict):
        return []
    return standings_data.get("standings", [])


# ─── Self-test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("  MSport API Module — Self Test")
    print("=" * 60)

    # 1. Current match day info
    info = get_current_match_day_info()
    if info:
        print(f"\n✅ Current MD: {info.get('matchDay')} | "
              f"Season: {info.get('seasonName')} ({info.get('seasonId')}) | "
              f"Status: {info.get('status')}")
    else:
        print("\n❌ get_current_match_day_info() FAILED")

    # 2. Event list
    events = get_event_list()
    if events:
        total_events = sum(len(md.get("events", [])) for md in events)
        print(f"✅ Event list: {len(events)} match days, {total_events} total events")
        if events and events[0].get("events"):
            sample = events[0]["events"][0]
            m = extract_all_markets(sample)
            print(f"   Sample: {sample.get('homeTeam')} vs {sample.get('awayTeam')}")
            print(f"   1X2: {m['1x2']}")
            print(f"   O/U: {m['over_under']}")
    else:
        print("\n❌ get_event_list() FAILED")

    # 3. Season list
    seasons = get_season_list()
    if seasons:
        print(f"✅ Season list: {len(seasons)} seasons available")
    else:
        print("\n❌ get_season_list() FAILED")

    # 4. League table / standings
    print()
    standings_data = get_standings()
    if standings_data:
        table = extract_standings_table(standings_data)
        season = standings_data.get("seasonName", "?")
        md = standings_data.get("matchDay", "?")
        print(f"✅ League table: {season} | Match Day {md} | {len(table)} teams")
        print(f"   {'Rank':>4} {'Team':<20} {'P':>3} {'W':>3} {'D':>3} {'L':>3} "
              f"{'GF':>3} {'GA':>3} {'GD':>4} {'Form':<10}")
        for row in table:
            form = "".join(row["lastFive"]) if row["lastFive"] else "-"
            print(f"   {row['rank']:>4} {row['teamName']:<20} "
                  f"{row['points']:>3} {row['won']:>3} {row['draw']:>3} {row['lost']:>3} "
                  f"{row['goalsFor']:>3} {row['goalsAgainst']:>3} {row['goalDifference']:>4} "
                  f"{form:<10}")
    else:
        print("\n❌ get_standings() FAILED")
