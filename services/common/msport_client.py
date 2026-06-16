"""MSport API client — shared by all microservices."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("msport_client")

BASE_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual"
DEFAULT_MARKET_URL = (
    "https://www.msport.com/api/ng/facts-center/query/frontend/default-market-info/v2"
)
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3
DEVICE_ID_FILE = Path(__file__).resolve().parents[2] / ".msport_device_id"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "operId": "2",
    "operid": "2",
    "clientid": "WEB",
    "platform": "WEB",
    "apilevel": "2",
    "network": "4g",
    "screenwh": "1920x1080",
    "devmem": "16",
    "Referer": "https://www.msport.com/ng/web/virtual",
    "Origin": "https://www.msport.com",
}

TEAM_ALIASES = {
    "MANCHESTER RED": "Manchester Red",
    "MANCHESTER CITY": "Manchester Blue",
    "MANCHESTER BLUE": "Manchester Blue",
    "LONDON GUNS": "London Guns",
    "ARSENAL": "London Guns",
    "CHELSEA": "Chelsea",
    "LIVERPOOL": "Liverpool",
    "ASTON VILLA": "Aston Villa",
    "TOTTENHAM": "Tottenham",
    "EVERTON": "Everton",
    "WOLVERHAMPTON": "Wolverhampton",
    "WOLVES": "Wolverhampton",
    "NEWCASTLE": "Newcastle",
    "LEEDS": "Leeds",
    "FULHAM": "Fulham",
    "WEST HAM": "West Ham",
    "BOURNEMOUTH": "Bournemouth",
    "BRIGHTON": "Brighton",
    "CRYSTAL PALACE": "Crystal Palace",
}

_LIST_MARKET_COUNT = 7


def _normalise_team_name(name: str) -> str:
    n = name.strip().upper()
    return TEAM_ALIASES.get(n, name.strip().title())


def _resolve_device_id() -> str:
    env_id = os.environ.get("MSPORT_DEVICE_ID")
    if env_id:
        return env_id
    try:
        if DEVICE_ID_FILE.exists():
            stored = DEVICE_ID_FILE.read_text(encoding="utf-8").strip()
            if stored:
                return stored
    except OSError:
        pass
    new_id = str(uuid.uuid4())
    try:
        DEVICE_ID_FILE.write_text(new_id, encoding="utf-8")
    except OSError:
        logger.debug("Could not persist device id to %s", DEVICE_ID_FILE)
    return new_id


def _make_headers() -> dict[str, str]:
    h = dict(DEFAULT_HEADERS)
    h["deviceid"] = _resolve_device_id()
    return h


def fetch_json(
    url: str,
    headers: Optional[dict] = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = MAX_RETRIES,
) -> Optional[dict]:
    if headers is None:
        headers = _make_headers()
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers=headers)
            resp = urlopen(req, timeout=timeout)
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            biz = data.get("bizCode", 10000)
            if biz != 10000:
                logger.warning(
                    "API err %s on %s: %s", biz, url[:80], data.get("msg", "")
                )
                if attempt < retries:
                    time.sleep(1.5)
                    continue
                return None
            return data.get("data") or data
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as e:
            last_error = e
            logger.debug("Attempt %s/%s failed: %s", attempt, retries, e)
            if attempt < retries:
                time.sleep(1.5)
    logger.error("All %s retries exhausted: %s", retries, last_error)
    return None


def get_event_list() -> Optional[list[dict]]:
    url = f"{BASE_URL}/event/list?sportId=vf:sport:1&pageSize=200&pageNum=1"
    data = fetch_json(url)
    if data and isinstance(data, dict):
        return (
            data.get("matchDays")
            or data.get("results")
            or data.get("list")
            or data.get("records")
            or []
        )
    return data if isinstance(data, list) else []


def get_event_detail(event_id: str) -> Optional[dict]:
    url = f"{BASE_URL}/event/detail?eventId={event_id}"
    return fetch_json(url)


def get_match_day_info() -> Optional[dict]:
    url = f"{BASE_URL}/current/match/day/info"
    return fetch_json(url)


def get_default_market_info(
    sport_id: str = "vf:sport:1", with_others: bool = True
) -> Optional[dict]:
    flag = "1" if with_others else "0"
    url = f"{DEFAULT_MARKET_URL}?sportId={sport_id}&withOthers={flag}"
    return fetch_json(url)


def get_results(season_id: str, match_day: int) -> Optional[list[dict]]:
    from urllib.parse import quote

    if "VFL" in str(season_id).upper():
        resolved = get_season_id_by_name(season_id)
        if resolved:
            season_id = resolved

    url = (
        f"{BASE_URL}/result?seasonId={quote(str(season_id))}"
        f"&matchDay={match_day}&pageSize=500&pageNum=1"
    )
    data = fetch_json(url)
    if data and isinstance(data, dict):
        return data.get("results") or data.get("list") or []
    return data if isinstance(data, list) else []


def get_season_id_by_name(name: str) -> Optional[str]:
    url = f"{BASE_URL}/result/season/selection"
    data = fetch_json(url)
    if not data or not isinstance(data, list):
        return None
    for s in data:
        if s.get("seasonName") == name:
            return s.get("seasonId")
    return None


def get_season_list() -> Optional[list[dict]]:
    url = f"{BASE_URL}/result/season/selection"
    data = fetch_json(url)
    if data and isinstance(data, dict):
        return data.get("results") or data.get("list") or data.get("records") or []
    return data if isinstance(data, list) else []


def get_standings() -> Optional[dict]:
    url = f"{BASE_URL}/table"
    return fetch_json(url)


def unwrap_event_payload(payload: Optional[dict]) -> dict:
    if not isinstance(payload, dict):
        return {}
    if "markets" in payload or "eventId" in payload:
        return payload
    inner = payload.get("data")
    return inner if isinstance(inner, dict) else payload


def markets_from_payload(payload: Optional[dict]) -> list[dict]:
    d = unwrap_event_payload(payload)
    return d.get("markets", []) or (d.get("event") or {}).get("markets", [])


def markets_to_records(
    markets: list[dict],
    *,
    event_id: str,
    season_id: str | None,
    matchday_number: int | None,
    home_team: str | None,
    away_team: str | None,
    source: str = "api",
) -> list[dict[str, Any]]:
    base = {
        "event_id": event_id,
        "season_id": season_id,
        "matchday_number": matchday_number,
        "home_team": home_team,
        "away_team": away_team,
        "source": source,
    }
    records: list[dict[str, Any]] = []
    for mkt in markets:
        mname = mkt.get("name", "")
        spec = mkt.get("specifiers", "") or ""
        for out in mkt.get("outcomes", []):
            if not out.get("isActive", 1):
                continue
            records.append(
                {
                    **base,
                    "market_name": mname,
                    "specifiers": spec,
                    "selection_name": out.get("description", ""),
                    "odds": out.get("odds"),
                    "market_id": mkt.get("id"),
                }
            )
    return records


def records_from_event(
    event: dict,
    *,
    season_id: str | None = None,
    matchday_number: int | None = None,
    source: str = "event_list",
) -> list[dict[str, Any]]:
    eid = event.get("eventId")
    if not eid:
        return []
    return markets_to_records(
        event.get("markets") or [],
        event_id=eid,
        season_id=event.get("seasonId") or season_id,
        matchday_number=matchday_number,
        home_team=_normalise_team_name(event.get("homeTeam", "")),
        away_team=_normalise_team_name(event.get("awayTeam", "")),
        source=source,
    )


def list_market_count(event: dict) -> int:
    return len(event.get("markets") or [])


def needs_detail_fetch(event: dict, min_list_markets: int = _LIST_MARKET_COUNT) -> bool:
    """True when list-embedded markets are incomplete vs browser default set."""
    return list_market_count(event) < min_list_markets


def extract_1x2_odds(event: dict) -> dict[str, float]:
    result = {"Home": 0.0, "Draw": 0.0, "Away": 0.0}
    for market in event.get("markets", []):
        if market.get("id") == 1 or market.get("name") == "1x2":
            for outcome in market.get("outcomes", []):
                desc = outcome.get("description", "").strip()
                try:
                    odds = float(outcome.get("odds", 0))
                except (TypeError, ValueError):
                    odds = 0.0
                if desc in result:
                    result[desc] = odds
            break
    return result