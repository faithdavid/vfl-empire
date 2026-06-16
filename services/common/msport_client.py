"""MSport API client — shared by all microservices."""
import json, logging, time, uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import Optional, Dict, Any, List

logger = logging.getLogger("msport_client")

BASE_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual"
DEFAULT_TIMEOUT = 15
MAX_RETRIES = 3

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "operId": "2", "operid": "2", "clientid": "wap",
    "platform": "WAP", "apilevel": "2",
    "Referer": "https://www.msport.com/ng/virtual/soccer",
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

def _normalise_team_name(name: str) -> str:
    """Normalise team name to canonical title case form."""
    n = name.strip().upper()
    return TEAM_ALIASES.get(n, name.strip().title())

def _make_headers() -> Dict[str, str]:
    h = dict(DEFAULT_HEADERS)
    h["deviceid"] = str(uuid.uuid4())
    return h

def fetch_json(url: str, headers: Optional[Dict] = None,
               timeout: int = DEFAULT_TIMEOUT, retries: int = MAX_RETRIES) -> Optional[Dict]:
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
                logger.warning(f"API err {biz} on {url[:80]}: {data.get('msg','')}")
                if attempt < retries:
                    time.sleep(1.5)
                    continue
                return None
            return data.get("data") or data
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as e:
            last_error = e
            logger.debug(f"Attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(1.5)
    logger.error(f"All {retries} retries exhausted: {last_error}")
    return None

def get_event_list() -> Optional[List[Dict]]:
    url = f"{BASE_URL}/event/list?sportId=vf:sport:1&pageSize=200&pageNum=1"
    data = fetch_json(url)
    if data and isinstance(data, dict):
        return data.get("matchDays") or data.get("results") or data.get("list") or data.get("records") or []
    return data if isinstance(data, list) else []

def get_event_detail(event_id: str) -> Optional[Dict]:
    url = f"{BASE_URL}/event/detail?eventId={event_id}"
    return fetch_json(url)

def get_match_day_info() -> Optional[Dict]:
    url = f"{BASE_URL}/current/match/day/info"
    return fetch_json(url)

def get_results(season_id: str, match_day: int) -> Optional[List[Dict]]:
    from urllib.parse import quote
    
    # If season_id looks like a name (e.g. VFLM 5145), try to resolve it
    if "VFL" in str(season_id).upper():
        resolved = get_season_id_by_name(season_id)
        if resolved:
            season_id = resolved
            
    url = f"{BASE_URL}/result?seasonId={quote(str(season_id))}&matchDay={match_day}&pageSize=500&pageNum=1"
    data = fetch_json(url)
    if data and isinstance(data, dict):
        return data.get("results") or data.get("list") or []
    return data if isinstance(data, list) else []

def get_season_id_by_name(name: str) -> Optional[str]:
    """Resolve a season name (e.g. 'VFLM 5145') to a season ID."""
    url = f"{BASE_URL}/result/season/selection"
    data = fetch_json(url)
    if not data or not isinstance(data, list):
        return None
    for s in data:
        if s.get("seasonName") == name:
            return s.get("seasonId")
    return None

def get_season_list() -> Optional[List[Dict]]:
    url = f"{BASE_URL}/result/season/selection"
    data = fetch_json(url)
    if data and isinstance(data, dict):
        return data.get("results") or data.get("list") or data.get("records") or []
    return data if isinstance(data, list) else []

def get_standings() -> Optional[Dict]:
    """Fetch the current league table from the API."""
    url = f"{BASE_URL}/table"
    return fetch_json(url)
