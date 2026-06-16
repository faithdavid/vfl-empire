#!/usr/bin/env python3
"""
Onimix VFL Probability Decoder Engine v1.0 (MSport Edition)
============================================================
Complete engine implementing:
  Section A — 6-market odds-based decoder (0–13 score) from MSport API prematch data
  Section B — Yesterday same-slot energy cards (0–14 score) from results history
  Combined analysis with confidence tiers (LOCK / PICK / CONSIDER / SKIP)
  Multi-market edge evaluator (fair odds from Correct Score implied distribution)
  State persistence in /tmp/vfl_state.json
  Fixture discovery and analysis pipeline
  CLI entry point for standalone runs

Engine v3.9 compatible — ONIMIX TECH
MSport API integration — no probability data, odds-based SA scoring
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import sys
import time
import requests
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

SPORT = 'vf:sport:1'
MS_BASE = 'https://www.msport.com/api/ng/facts-center/query/frontend/virtual'

# Sweet spot range for O1.5 odds
SWEET = (1.38, 1.60)

# State file
STATE_FILE = '/tmp/vfl_state.json'

# Hourly VFL times (used for time-slot matching on Section B)
VFL_TIMES_HOURS = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]

# VFL leagues configuration — MSport uses category names for filtering
LEAGUES: Dict[str, Dict[str, Any]] = {
    'spain': {
        'name': 'Spain VFL',
        'catName': 'Spain',
    },
    'germany': {
        'name': 'Germany VFL',
        'catName': 'Germany',
    },
    'england': {
        'name': 'England VFL',
        'catName': 'England',
    },
    'italy': {
        'name': 'Italy VFL',
        'catName': 'Italy',
    },
    'france': {
        'name': 'France VFL',
        'catName': 'France',
    },
}

# HTTP headers for MSport API
HEADERS: Dict[str, str] = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json',
    'operId': '2',
    'clientid': 'wap',
    'platform': 'WAP',
    'Referer': 'https://www.msport.com/ng/virtual/soccer',
}

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
logger = logging.getLogger('onimix_engine')
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ═══════════════════════════════════════════════════════════════════════════
# Section 0: State Persistence  (/tmp/vfl_state.json)
# ═══════════════════════════════════════════════════════════════════════════

_state_cache: Optional[Dict[str, Any]] = None


def _load_state() -> Dict[str, Any]:
    """Load full state dict from /tmp/vfl_state.json (cached in memory)."""
    global _state_cache
    if _state_cache is not None:
        return _state_cache
    try:
        with open(STATE_FILE) as f:
            _state_cache = json.load(f)
        logger.debug("State loaded from %s", STATE_FILE)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _state_cache = {
            'predictions': {},
            'blacklist': {},
            'results': [],
            'sent': {},
            'updated': 0,
        }
        logger.info("New state file created at %s", STATE_FILE)
    # _state_cache is now guaranteed a dict
    assert _state_cache is not None
    return _state_cache


def _save_state() -> None:
    """Persist the in-memory state cache to /tmp/vfl_state.json."""
    global _state_cache
    if _state_cache is None:
        return
    _state_cache['updated'] = time.time()
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(_state_cache, f, separators=(',', ':'))
        logger.debug("State saved to %s", STATE_FILE)
    except OSError as exc:
        logger.error("Failed to save state: %s", exc)


def load_predictions() -> Tuple[Dict[str, Any], str]:
    """Load predictions dict from state."""
    s = _load_state()
    return s.get('predictions', {}), ''


def save_predictions(preds: Dict[str, Any], sha: str = '') -> None:
    """Save predictions dict to state."""
    s = _load_state()
    s['predictions'] = preds
    _save_state()


def load_blacklist() -> Tuple[Dict[str, Any], str]:
    """Load blacklist dict from state."""
    s = _load_state()
    return s.get('blacklist', {}), ''


def save_blacklist(bl: Dict[str, Any], sha: str = '') -> None:
    """Save blacklist dict to state."""
    s = _load_state()
    s['blacklist'] = bl
    _save_state()


def load_results_history() -> Tuple[List[Dict[str, Any]], str]:
    """Load results history list from state."""
    s = _load_state()
    r: Any = s.get('results', [])
    if isinstance(r, dict) and 'results' in r:
        r = r['results']
    return r, ''


def save_results_history(results: List[Dict[str, Any]], sha: str = '') -> None:
    """Save results history list to state."""
    s = _load_state()
    s['results'] = results
    _save_state()


def load_sent() -> Tuple[Dict[str, float], str]:
    """Load sent-dedup dict from state."""
    s = _load_state()
    return s.get('sent', {}), ''


def save_sent(d: Dict[str, float], sha: str = '') -> None:
    """Save sent-dedup dict to state."""
    s = _load_state()
    s['sent'] = d
    _save_state()


def matchup_key(home: str, away: str) -> str:
    """Canonical matchup key (sorted, lowercased)."""
    h = (home or '').strip().lower()
    a = (away or '').strip().lower()
    return '|'.join(sorted([h, a]))


# --------------------------------------------------------------------------
# Dedup: prevent re-sending the same set of picks within 6 hours
# --------------------------------------------------------------------------

def dedup_key(picks: List[Dict[str, Any]]) -> str:
    """Generate a dedup hash from a list of picks (by eventId)."""
    ids = sorted(str(p.get('eid', '')) for p in picks if p.get('eid'))
    return hashlib.md5('|'.join(ids).encode()).hexdigest()


def already_sent(key: str) -> bool:
    """Check if a dedup key was sent within the last 6 hours (21600 s)."""
    d, _ = load_sent()
    now = time.time()
    # Purge expired entries
    d = {k: v for k, v in d.items() if now - v < 21600}
    save_sent(d)
    return key in d


def mark_sent(key: str) -> None:
    """Mark a dedup key as sent (now)."""
    d, _ = load_sent()
    d[key] = time.time()
    save_sent(d)


# ═══════════════════════════════════════════════════════════════════════════
# Section 0.5: MSport API Client (with retries)
# ═══════════════════════════════════════════════════════════════════════════

def _api_get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
    retries: int = 3,
) -> Optional[Dict[str, Any]]:
    """Generic GET request to MSport API with retry logic.

    MSport returns { code: 0, data: { ... } } or directly { data: { ... } }.
    Extracts and returns the 'data' field on success.
    """
    url = f'{MS_BASE}/{path}'
    if params is None:
        params = {}

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if resp.status_code != 200:
                logger.warning("API HTTP %d on attempt %d/%d: %s", resp.status_code, attempt, retries, url[:80])
                if attempt < retries:
                    time.sleep(1.5)
                    continue
                return None
            data = resp.json()
            # MSport may wrap in { data: ... } or { code: 0, data: ... }
            if isinstance(data, dict) and 'data' in data:
                inner = data['data']
                if isinstance(inner, dict):
                    return inner
                return data
            # Some endpoints return the list directly
            if isinstance(data, dict):
                return data
            return None
        except requests.RequestException as exc:
            logger.debug("Request error attempt %d/%d: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(1.5)
                continue
            return None
    return None


# --------------------------------------------------------------------------
# MSport Event List
# --------------------------------------------------------------------------

def fetch_event_list() -> List[Dict[str, Any]]:
    """Fetch all upcoming VFL events from MSport event/list endpoint.

    Returns a flat list of event dicts (pre-match only, status=0).
    """
    params: Dict[str, Any] = {
        'sportId': SPORT,
        'pageSize': 200,
        'pageNum': 1,
    }
    data = _api_get('event/list', params=params, timeout=20)
    if data is None:
        return []

    # Structure: data.matchDays[].events[]
    match_days = data.get('matchDays')
    if isinstance(match_days, list):
        events: List[Dict[str, Any]] = []
        for md in match_days:
            for ev in md.get('events', []):
                if isinstance(ev, dict):
                    events.append(ev)
        return events

    # Fallback: flat list in data
    evts = data.get('events')
    if isinstance(evts, list):
        return evts

    # Fallback: data itself is a list
    if isinstance(data, list):
        return data

    return []


def fetch_event_detail(event_id: str) -> Optional[Dict[str, Any]]:
    """Fetch event detail with full markets from MSport event/detail endpoint.

    Returns None if not found or not pre-match (status != 0).
    """
    data = _api_get('event/detail', params={'eventId': event_id}, timeout=15)
    if data is None:
        return None
    # data is the event dict
    ev = data if isinstance(data, dict) else None
    if ev is None:
        return None
    # Check pre-match status
    status = ev.get('status')
    if status not in (0, None):
        return None
    if not ev.get('homeTeam'):
        return None
    return ev


def fetch_event_detail_unfiltered(event_id: str) -> Optional[Dict[str, Any]]:
    """Fetch event detail without status filter (to check finished matches)."""
    data = _api_get('event/detail', params={'eventId': event_id}, timeout=15)
    if data is None:
        return None
    ev = data if isinstance(data, dict) else None
    if ev is None:
        return None
    return ev


# --------------------------------------------------------------------------
# MSport Results
# --------------------------------------------------------------------------

def _fetch_results_for_date(season_id: str, match_day: int) -> List[Dict[str, Any]]:
    """Fetch VFL results for a specific seasonId and matchDay.

    Returns a list of event dicts (finished matches with scores).
    """
    all_events: List[Dict[str, Any]] = []
    for page in range(1, 6):
        data = _api_get(
            'result',
            params={
                'seasonId': season_id,
                'matchDay': match_day,
                'pageSize': 500,
                'pageNum': page,
            },
            timeout=15,
        )
        if data is None:
            break

        # Try different response shapes
        evts = data.get('events')
        if isinstance(evts, list):
            all_events.extend(evts)
            if len(evts) < 500:
                break
        else:
            break

    return all_events


def fetch_league_results(
    league_key: str,
    hours: int = 4,
) -> List[Dict[str, Any]]:
    """Fetch recent results for a league (used for discovery pattern extraction).

    Uses the event list to find finished events for this league's category.
    """
    cfg = LEAGUES.get(league_key)
    if cfg is None:
        return []

    all_events = fetch_event_list()
    cat_name = cfg['catName']
    # Filter by category name and finished status
    filtered = [
        ev for ev in all_events
        if ev.get('category') == cat_name and ev.get('status') == 3
    ]
    return filtered


# ═══════════════════════════════════════════════════════════════════════════
# Section 0.75: Utility helpers
# ═══════════════════════════════════════════════════════════════════════════

def sum_score(desc: str) -> int:
    """Parse a 'x:y' score description and return x + y."""
    try:
        parts = desc.replace(' ', '').split(':')
        return int(parts[0]) + int(parts[1])
    except (ValueError, IndexError, AttributeError):
        return 0


def parse_set_score(score_str: str) -> Tuple[int, int]:
    """Parse 'x:y' or 'x-y' score string into (home_goals, away_goals)."""
    try:
        score_str = str(score_str).replace('-', ':')
        parts = score_str.split(':')
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError, AttributeError):
        return 0, 0


def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely parse a value to float (handles strings like '1.60')."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ═══════════════════════════════════════════════════════════════════════════
# Section A: MSport Odds-Based Pre-match Decoder (6 markets)
# ═══════════════════════════════════════════════════════════════════════════
#
# MSport has NO probability data — all outcomes have probability: "0.0000".
# Scoring is based on odds thresholds.
#
# Markets (in order):
#   Market 18 (O/U)  → Over 1.5 odds, Over 2.5 odds
#   Market 19 (Home O/U) → Over 0.5 odds
#   Market 20 (Away O/U) → Over 0.5 odds
#   Market 29 (GG/NG) → "Yes" odds
#   Market 68 (1st Half O/U) → Over 0.5 odds
#   Market 199 (CS) → Edge evaluator only (optional bonus)
#
# Scoring thresholds (based on odds):
#   O1.5 odds ≤ 1.60 → +3, ≤ 1.80 → +1
#   O2.5 odds ≤ 2.20 → +2, ≤ 2.80 → +1
#   Home O0.5 odds ≤ 1.40 → +2, ≤ 1.60 → +1
#   Away O0.5 odds ≤ 1.40 → +2, ≤ 1.60 → +1
#   GG odds ≤ 1.80 → +2, ≤ 2.20 → +1
#   1st Half O0.5 odds ≤ 1.50 → +2, ≤ 1.70 → +1
#
# Max score: 3+2+2+2+2+2 = 13
# ═══════════════════════════════════════════════════════════════════════════

def sec_a(event: Dict[str, Any]) -> Dict[str, Any]:
    """Decode 6 markets from the MSport event JSON using odds-based scoring.

    Markets (in order):
        OU(18)     → Over 1.5, Over 2.5
        HOU(19)    → Home Over 0.5
        AOU(20)    → Away Over 0.5
        FH(68)     → 1st Half Over 0.5
        GG(29)     → GG/NG
        CS(199)    → Correct Score (edge analysis)

    Returns a dict with:
        sc, mx, pct, ou15_odds, ou15_prob, ou15_oid,
        sweet, fp11, sig, conf
    """
    mkts = event.get('markets', [])

    # Storage for odds values
    ou15_odds: float = 0.0
    ou15_oid: str = ''
    ou25_odds: float = 0.0
    home_ou05_odds: float = 0.0
    away_ou05_odds: float = 0.0
    gg_odds: float = 0.0
    fh_ou05_odds: float = 0.0

    # CS market data for edge analysis
    cs_outcomes: Optional[Dict[str, float]] = None  # desc -> odds

    for m in mkts:
        mid = m.get('id')
        outcomes = m.get('outcomes', [])

        if mid == 199:
            # Correct Score — store odds for edge analysis
            parsed: Dict[str, float] = {}
            for o in outcomes:
                if o.get('isActive') not in (1, '1', True):
                    continue
                desc = o.get('description', o.get('desc', ''))
                od = safe_float(o.get('odds', 0))
                if desc and od > 0:
                    parsed[desc] = od
            if parsed:
                cs_outcomes = parsed

        elif mid == 18:
            # Over/Under — multiple entries distinguished by description
            for o in outcomes:
                if o.get('isActive') not in (1, '1', True):
                    continue
                desc = o.get('description', o.get('desc', ''))
                od = safe_float(o.get('odds', 0))
                oid = o.get('id', '')
                if desc.startswith('Over 1.5') and od > 0:
                    ou15_odds = od
                    ou15_oid = str(oid)
                elif desc.startswith('Over 2.5') and od > 0:
                    ou25_odds = od

        elif mid == 19:
            # Home O/U
            for o in outcomes:
                if o.get('isActive') not in (1, '1', True):
                    continue
                desc = o.get('description', o.get('desc', ''))
                od = safe_float(o.get('odds', 0))
                if desc.startswith('Over 0.5') and od > 0:
                    home_ou05_odds = od

        elif mid == 20:
            # Away O/U
            for o in outcomes:
                if o.get('isActive') not in (1, '1', True):
                    continue
                desc = o.get('description', o.get('desc', ''))
                od = safe_float(o.get('odds', 0))
                if desc.startswith('Over 0.5') and od > 0:
                    away_ou05_odds = od

        elif mid == 68:
            # 1st Half O/U
            for o in outcomes:
                if o.get('isActive') not in (1, '1', True):
                    continue
                desc = o.get('description', o.get('desc', ''))
                od = safe_float(o.get('odds', 0))
                if desc.startswith('Over 0.5') and od > 0:
                    fh_ou05_odds = od

        elif mid == 29:
            # GG/NG
            for o in outcomes:
                if o.get('isActive') not in (1, '1', True):
                    continue
                desc = o.get('description', o.get('desc', ''))
                od = safe_float(o.get('odds', 0))
                if desc == 'Yes' and od > 0:
                    gg_odds = od

    sc = 0      # score accumulator
    mx = 0      # max possible score
    sig: Dict[str, Any] = {}

    # -- Market 18: O/U 1.5 odds-based scoring --
    mx += 3
    sig['ou15_odds'] = ou15_odds
    if ou15_odds > 0:
        if ou15_odds <= 1.60:
            sc += 3
        elif ou15_odds <= 1.80:
            sc += 1

    # -- Market 18: O/U 2.5 odds-based scoring --
    mx += 2
    sig['ou25_odds'] = ou25_odds
    if ou25_odds > 0:
        if ou25_odds <= 2.20:
            sc += 2
        elif ou25_odds <= 2.80:
            sc += 1

    # -- Market 19: Home O/U 0.5 odds-based scoring --
    mx += 2
    sig['home_ou05_odds'] = home_ou05_odds
    if home_ou05_odds > 0:
        if home_ou05_odds <= 1.40:
            sc += 2
        elif home_ou05_odds <= 1.60:
            sc += 1

    # -- Market 20: Away O/U 0.5 odds-based scoring --
    mx += 2
    sig['away_ou05_odds'] = away_ou05_odds
    if away_ou05_odds > 0:
        if away_ou05_odds <= 1.40:
            sc += 2
        elif away_ou05_odds <= 1.60:
            sc += 1

    # -- Market 29: GG odds-based scoring --
    mx += 2
    sig['gg_odds'] = gg_odds
    if gg_odds > 0:
        if gg_odds <= 1.80:
            sc += 2
        elif gg_odds <= 2.20:
            sc += 1

    # -- Market 68: 1st Half O/U 0.5 odds-based scoring --
    mx += 2
    sig['fh_ou05_odds'] = fh_ou05_odds
    if fh_ou05_odds > 0:
        if fh_ou05_odds <= 1.50:
            sc += 2
        elif fh_ou05_odds <= 1.70:
            sc += 1

    pct = round(sc / mx * 100) if mx > 0 else 0
    sweet = SWEET[0] <= ou15_odds <= SWEET[1] if ou15_odds > 0 else False

    # fp11 flag: detect 1:1 fingerprint from CS odds if available
    fp11_flag = False
    if cs_outcomes:
        for desc, od in cs_outcomes.items():
            if desc.replace(' ', '') == '1:1' and od < 10.0:
                fp11_flag = True
                break
    sig['fp11'] = fp11_flag

    # Confidence based on pct (since no probability data)
    if pct >= 75:
        conf = 'HIGH'
    elif pct >= 50:
        conf = 'MEDIUM'
    else:
        conf = 'LOW'

    # CS edge analysis bonus
    if cs_outcomes:
        # Compute implied probabilities from odds for CS
        total_implied = sum(1.0 / od for od in cs_outcomes.values() if od > 0)
        if total_implied > 0:
            o15p = sum(
                1.0 / od for desc, od in cs_outcomes.items()
                if od > 0 and sum_score(desc) >= 2
            ) / total_implied
            sig['cs_o15'] = round(o15p, 4)

            # 1:1 fingerprint probability
            fp11_prob = 0.0
            for desc, od in cs_outcomes.items():
                if desc.replace(' ', '') == '1:1' and od > 0:
                    fp11_prob = (1.0 / od) / total_implied
                    break
            sig['fp11_prob'] = round(fp11_prob, 4)

    return {
        'sc': sc,
        'mx': mx,
        'pct': pct,
        'ou15_odds': ou15_odds,
        'ou15_prob': 0.0,  # MSport has no probability data
        'ou15_oid': ou15_oid,
        'sweet': sweet,
        'fp11': fp11_flag,
        'sig': sig,
        'conf': conf,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Section B: Yesterday Same-Slot Energy Cards
# ═══════════════════════════════════════════════════════════════════════════

def find_slot(
    history: List[Dict[str, Any]],
    target_est: int,
) -> List[Dict[str, Any]]:
    """Find yesterday's matches in the same time slot (+/- 10 min).

    *target_est* is the startTime (epoch ms) of the target event.
    Returns a list of result dicts for the closest matching slot.
    """
    target_dt = datetime.fromtimestamp(target_est / 1000, tz=timezone.utc)
    target_min = target_dt.hour * 60 + target_dt.minute

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    yest_start_ts = yesterday_start.timestamp()
    today_start_ts = today_start.timestamp()

    # Collect results from yesterday UTC
    yesterday_results: List[Dict[str, Any]] = []
    for r in history:
        ts = r.get('timestamp', 0)
        if ts > 1000000000000:
            ts = ts / 1000
        if yest_start_ts <= ts < today_start_ts:
            yesterday_results.append(r)

    if not yesterday_results:
        return []

    # Group by start time
    slots: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in yesterday_results:
        st = r.get('start', 0)
        if st > 0:
            slots[st].append(r)

    # Find closest slot within 10 minutes
    best: Optional[int] = None
    best_diff = 999
    for t in slots:
        dt = datetime.fromtimestamp(
            t / 1000 if t > 1000000000000 else t,
            tz=timezone.utc,
        )
        slot_min = dt.hour * 60 + dt.minute
        diff = abs(slot_min - target_min)
        if diff < best_diff:
            best_diff = diff
            best = t

    if best is not None and best_diff <= 10:
        return slots[best]
    return []


def energy(
    slot: List[Dict[str, Any]],
    home: str,
    away: str,
) -> Dict[str, Any]:
    """Build energy card from a list of same-slot results.

    Returns:
        sf: Same fixture result dict {hs, as, t} or None
        h:  Home team stats  {s, c, t}  (scored, conceded, total)
        a:  Away team stats  {s, c, t}
        n:  Number of matches in the slot
    """
    sf: Optional[Dict[str, int]] = None
    hd: Dict[str, int] = {'s': 0, 'c': 0, 't': 0}
    ad: Dict[str, int] = {'s': 0, 'c': 0, 't': 0}

    for m in slot:
        h = m.get('home', '')
        a = m.get('away', '')
        hs = m.get('home_goals')
        aws = m.get('away_goals')

        if hs is None or aws is None:
            continue

        hs_int = int(hs)
        aws_int = int(aws)

        # Same fixture
        if h == home and a == away:
            sf = {'hs': hs_int, 'as': aws_int, 't': hs_int + aws_int}

        # Home team stats
        if h == home:
            hd = {'s': hs_int, 'c': aws_int, 't': hs_int + aws_int}
        elif a == home:
            hd = {'s': aws_int, 'c': hs_int, 't': hs_int + aws_int}

        # Away team stats
        if h == away:
            ad = {'s': hs_int, 'c': aws_int, 't': hs_int + aws_int}
        elif a == away:
            ad = {'s': aws_int, 'c': hs_int, 't': hs_int + aws_int}

    return {'sf': sf, 'h': hd, 'a': ad, 'n': len(slot)}


def sec_b(en: Dict[str, Any]) -> Dict[str, Any]:
    """Section B scoring (max 14 points).

    Skip rules (checked first):
        Skip-C: h.total >= 4 AND a.total >= 4  (compression)
        Skip-D: h.total + a.total < 2           (low energy)
        Skip-E: same_fixture.total == 0         (same fix 0-0)

    Scoring rules:
        R1: h.scored >= 1   → +2
        R2: a.scored >= 1   → +2
        R3: sf.total >= 2   → +2
        R4: h.total >= 2    → +2
        R5: a.total >= 2    → +2
        R6: h.total + a.total >= 4  → +1
        R7: both teams scored AND conceded  → +1
            (h.scored>0 and h.conceded>0 and a.scored>0 and a.conceded>0)

    Tiers:
        LOCK     >= 10
        PICK     >=  6
        CONSIDER >=  3
        SKIP     <  3  (or any skip rule triggered)
    """
    h = en['h']
    a = en['a']
    sf = en['sf']

    # -- Skip rules --
    if h['t'] >= 4 and a['t'] >= 4:
        return {
            'skip': True,
            'reason': 'Skip-C: Compression',
            'sc': 0,
            'conf': 'SKIP',
            'reasons': ['Skip-C'],
        }
    if h['t'] + a['t'] < 2:
        return {
            'skip': True,
            'reason': 'Skip-D: Low energy',
            'sc': 0,
            'conf': 'SKIP',
            'reasons': ['Skip-D'],
        }
    if sf is not None and sf['t'] == 0:
        return {
            'skip': True,
            'reason': 'Skip-E: Same fix 0-0',
            'sc': 0,
            'conf': 'SKIP',
            'reasons': ['Skip-E'],
        }

    # -- Scoring --
    pts = 0
    reasons: List[str] = []

    if h['s'] >= 1:
        pts += 2
        reasons.append(f"R1:H scored {h['s']}(+2)")
    if a['s'] >= 1:
        pts += 2
        reasons.append(f"R2:A scored {a['s']}(+2)")
    if sf and sf['t'] >= 2:
        pts += 2
        reasons.append(f"R3:Fix {sf['hs']}-{sf['as']}(+2)")
    if h['t'] >= 2:
        pts += 2
        reasons.append(f"R4:H total {h['t']}>=2(+2)")
    if a['t'] >= 2:
        pts += 2
        reasons.append(f"R5:A total {a['t']}>=2(+2)")
    if h['t'] + a['t'] >= 4:
        pts += 1
        reasons.append(f"R6:Comb {h['t'] + a['t']}>=4(+1)")
    if h['s'] > 0 and h['c'] > 0 and a['s'] > 0 and a['c'] > 0:
        pts += 1
        reasons.append("R7:Both S&C(+1)")

    if pts >= 10:
        conf = 'LOCK'
    elif pts >= 6:
        conf = 'PICK'
    elif pts >= 3:
        conf = 'CONSIDER'
    else:
        conf = 'SKIP'

    return {
        'skip': conf == 'SKIP',
        'reason': '' if conf != 'SKIP' else f'B:{pts}<3',
        'sc': pts,
        'conf': conf,
        'reasons': reasons,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Multi-Market Edge Evaluator
# ═══════════════════════════════════════════════════════════════════════════
#
# MSport has NO probability data — we compute implied probabilities from odds.
# Implied probability = 1/odds, then normalize to remove overround.
# ═══════════════════════════════════════════════════════════════════════════

def compute_fair_odds_from_cs(cs_odds: Dict[str, float]) -> Dict[str, Any]:
    """Compute fair odds for 1X2 from the Correct Score odds distribution.

    Given CS outcomes with odds values, calculates implied probabilities
    by normalizing 1/odds to remove bookmaker overround.

    Returns:
        home_win_prob, draw_prob, away_win_prob, fair odds for each,
        ov05_prob, ov15_prob, fair odds for O/U lines
    """
    # Compute implied probabilities
    implied: Dict[str, float] = {}
    total_implied = 0.0
    for desc, od in cs_odds.items():
        if od <= 0:
            continue
        imp = 1.0 / od
        implied[desc] = imp
        total_implied += imp

    if total_implied <= 0:
        return {
            'available': False,
        }

    # Normalize to remove overround
    home_win_prob = 0.0
    draw_prob = 0.0
    away_win_prob = 0.0
    ov05_prob = 0.0
    ov15_prob = 0.0

    for desc, imp in implied.items():
        prob = imp / total_implied
        try:
            parts = desc.replace(' ', '').split(':')
            home_goals = int(parts[0])
            away_goals = int(parts[1])
        except (ValueError, IndexError):
            continue

        total = home_goals + away_goals
        if total >= 1:
            ov05_prob += prob
        if total >= 2:
            ov15_prob += prob
        if home_goals > away_goals:
            home_win_prob += prob
        elif home_goals == away_goals:
            draw_prob += prob
        else:
            away_win_prob += prob

    return {
        'available': True,
        'home_win_prob': round(home_win_prob, 4),
        'draw_prob': round(draw_prob, 4),
        'away_win_prob': round(away_win_prob, 4),
        'fair_odds_home': round(1.0 / home_win_prob, 4) if home_win_prob > 0 else 0,
        'fair_odds_draw': round(1.0 / draw_prob, 4) if draw_prob > 0 else 0,
        'fair_odds_away': round(1.0 / away_win_prob, 4) if away_win_prob > 0 else 0,
        'ov05_prob': round(ov05_prob, 4),
        'ov15_prob': round(ov15_prob, 4),
        'fair_odds_ov05': round(1.0 / ov05_prob, 4) if ov05_prob > 0 else 0,
        'fair_odds_ov15': round(1.0 / ov15_prob, 4) if ov15_prob > 0 else 0,
    }


def compute_edge(market_odds: float, fair_odds: float) -> float:
    """Compute edge % = (market_odds / fair_odds) - 1.
    Positive means the market odds are better than fair odds.
    """
    if fair_odds <= 0:
        return 0.0
    return (market_odds / fair_odds) - 1.0


def multi_market_edge_analysis(event: Dict[str, Any]) -> Dict[str, Any]:
    """Full multi-market edge analysis for a given event.

    Extracts MSport markets and compares against fair odds
    derived from the Correct Score distribution (market 199).
    """
    mkts = event.get('markets', [])
    cs_odds: Optional[Dict[str, float]] = None

    for m in mkts:
        mid = m.get('id')
        if mid == 199:
            parsed: Dict[str, float] = {}
            for o in m.get('outcomes', []):
                try:
                    if o.get('isActive') not in (1, '1', True):
                        continue
                    desc = o.get('description', o.get('desc', ''))
                    od = safe_float(o.get('odds', 0))
                    if desc and od > 0:
                        parsed[desc] = od
                except (KeyError, TypeError, ValueError):
                    pass
            cs_odds = parsed
            break

    if not cs_odds:
        return {'available': False, 'fair': {}, 'edges': {}}

    fair = compute_fair_odds_from_cs(cs_odds)
    if not fair.get('available'):
        return {'available': False, 'fair': {}, 'edges': {}}

    # Extract bookmaker odds for 1X2, O/U 0.5, O/U 1.5
    home_odds = 0.0
    draw_odds = 0.0
    away_odds = 0.0
    ov05_odds = 0.0
    ov15_odds = 0.0

    for m in mkts:
        mid = m.get('id')
        outcomes = m.get('outcomes', [])

        # Market 1: 1X2 (if available on MSport)
        if mid == 1:
            for o in outcomes:
                try:
                    desc = o.get('description', o.get('desc', ''))
                    od = safe_float(o.get('odds', 0))
                    if desc == 'Home':
                        home_odds = od
                    elif desc == 'Draw':
                        draw_odds = od
                    elif desc == 'Away':
                        away_odds = od
                except (TypeError, ValueError):
                    pass

        # Market 18: O/U — entries distinguished by description
        elif mid == 18:
            for o in outcomes:
                try:
                    desc = o.get('description', o.get('desc', ''))
                    od = safe_float(o.get('odds', 0))
                    if desc.startswith('Over 0.5'):
                        ov05_odds = od
                    elif desc.startswith('Over 1.5'):
                        ov15_odds = od
                except (TypeError, ValueError):
                    pass

    edges = {}
    if home_odds > 0 and fair.get('fair_odds_home', 0) > 0:
        edges['home_win'] = round(compute_edge(home_odds, fair['fair_odds_home']), 4)
    if draw_odds > 0 and fair.get('fair_odds_draw', 0) > 0:
        edges['draw'] = round(compute_edge(draw_odds, fair['fair_odds_draw']), 4)
    if away_odds > 0 and fair.get('fair_odds_away', 0) > 0:
        edges['away_win'] = round(compute_edge(away_odds, fair['fair_odds_away']), 4)
    if ov05_odds > 0 and fair.get('fair_odds_ov05', 0) > 0:
        edges['ov05'] = round(compute_edge(ov05_odds, fair['fair_odds_ov05']), 4)
    if ov15_odds > 0 and fair.get('fair_odds_ov15', 0) > 0:
        edges['ov15'] = round(compute_edge(ov15_odds, fair['fair_odds_ov15']), 4)

    return {
        'available': True,
        'fair': fair,
        'edges': edges,
        'market_odds': {
            'home_win': home_odds,
            'draw': draw_odds,
            'away_win': away_odds,
            'ov05': ov05_odds,
            'ov15': ov15_odds,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Blacklist System
# ═══════════════════════════════════════════════════════════════════════════

def is_blacklisted(home: str, away: str, blacklist: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if a matchup is blacklisted (>= 2 fails in last 7 days).

    Returns (True, reason) or (False, '').
    """
    mk = matchup_key(home, away)
    entry = blacklist.get(mk)
    if not entry:
        return False, ''
    fails = entry.get('fails', 0)
    last_fail = entry.get('last_fail', 0)
    # Expire after 7 days
    if time.time() - last_fail > 604800:
        return False, ''
    if fails >= 2:
        last_reason = entry.get('history', [{}])[-1].get('reason', '?')
        return True, f'Failed {fails} times (last: {last_reason})'
    return False, ''


def analyze_failure(pred_info: Dict[str, Any], total_goals: int) -> str:
    """Analyze why a prediction failed (for blacklist annotation)."""
    reasons: List[str] = []
    pct = pred_info.get('pct', 0)
    sig = pred_info.get('signals', {})

    if total_goals == 0:
        reasons.append('0-0 dead match')
    elif total_goals == 1:
        reasons.append('Only 1 goal scored')

    if pct < 60:
        reasons.append(f'Low confidence ({pct}%)')

    cs_o15 = sig.get('cs_o15', 0)
    if cs_o15 < 0.50:
        reasons.append(f'Weak CS signal ({cs_o15 * 100:.0f}%)')

    fp11 = sig.get('fp11_prob', 0)
    if fp11 > 0.10:
        reasons.append(f'1:1 fingerprint detected ({fp11 * 100:.1f}%)')

    ou15_prob = sig.get('ou15_odds', 0)
    if ou15_prob > 0 and ou15_prob > 1.80:
        reasons.append(f'High O1.5 odds ({ou15_prob:.2f})')

    gg_odds = sig.get('gg_odds', 0)
    if gg_odds > 0 and gg_odds > 2.20:
        reasons.append(f'High GG odds ({gg_odds:.2f})')

    return '; '.join(reasons) if reasons else 'Unknown'


# ═══════════════════════════════════════════════════════════════════════════
# Past Prediction Checker & Results Accumulator
# ═══════════════════════════════════════════════════════════════════════════

def _match_result(
    pred_info: Dict[str, Any],
    results_cache: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Find the result for a prediction by matching home/away + start time.

    Uses MSport field names (homeTeam, awayTeam, startTime).
    """
    home = (pred_info.get('home') or '').strip().upper()
    away = (pred_info.get('away') or '').strip().upper()
    start = pred_info.get('start', 0)

    # Exact match
    for e in results_cache:
        eh = (e.get('homeTeam') or '').strip().upper()
        ea = (e.get('awayTeam') or '').strip().upper()
        es = e.get('startTime', 0)
        if eh == home and ea == away and abs(es - start) < 300000:
            return e

    # Fuzzy: wider time window
    for e in results_cache:
        eh = (e.get('homeTeam') or '').strip().upper()
        ea = (e.get('awayTeam') or '').strip().upper()
        es = e.get('startTime', 0)
        if eh == home and ea == away and abs(es - start) < 900000:
            return e

    return None


def check_past_predictions() -> Dict[str, Any]:
    """Check results of predicted matches using MSport event detail / result API.

    Returns a summary dict with checked/won/lost/pending counts.
    Also updates blacklist and results_history in state.
    """
    preds, preds_sha = load_predictions()
    blacklist, bl_sha = load_blacklist()
    results_history, rh_sha = load_results_history()
    existing_ids: set = set()
    for r in results_history:
        hk = f"{r.get('home', '')}|{r.get('away', '')}|{r.get('start', 0)}"
        existing_ids.add(hk)

    if not preds:
        return {
            'checked': 0,
            'won': 0,
            'lost': 0,
            'pending': 0,
            'new_blacklist': [],
            'new_results': 0,
            'total_history': len(results_history),
            'win_rate': 0,
        }

    checked = 0
    won = 0
    lost = 0
    pending = 0
    new_blacklist_entries: List[Dict[str, Any]] = []
    new_results_count = 0

    # Filter to unsettled predictions within 48h
    cutoff = time.time() - 172800
    to_check = {
        gid: info
        for gid, info in preds.items()
        if info.get('status') != 'settled' and info.get('timestamp', 0) > cutoff
    }

    if not to_check:
        return {
            'checked': 0,
            'won': 0,
            'lost': 0,
            'pending': 0,
            'new_blacklist': [],
            'new_results': 0,
            'total_history': len(results_history),
            'win_rate': 0,
        }

    logger.info("Checking %d pending predictions...", len(to_check))

    # Fetch event detail for each pending prediction to check result
    results_cache: List[Dict[str, Any]] = []
    for gid, info in to_check.items():
        start_ms = info.get('start', 0)
        if start_ms <= 0:
            pending += 1
            continue
        # Only check if match should be finished (start + 10 min grace)
        match_end_est = start_ms / 1000 + 600
        if time.time() < match_end_est:
            pending += 1
            continue

        # Fetch event detail by eventId (stored as eid in prediction)
        eid = info.get('eid', gid)
        ev = fetch_event_detail_unfiltered(eid)
        if ev is not None and ev.get('status') == 3:
            results_cache.append(ev)

    logger.info("Fetched %d finished events for matching", len(results_cache))

    # Match and settle
    for gid, pred_info in to_check.items():
        start_ms = pred_info.get('start', 0)
        if start_ms <= 0:
            continue
        match_end_est = start_ms / 1000 + 600
        if time.time() < match_end_est:
            continue

        ev = _match_result(pred_info, results_cache)
        if ev is None:
            pending += 1
            continue

        # Extract score from finished event
        # Try multiple score fields
        score = ''
        home_goals = 0
        away_goals = 0

        # Option 1: score/result field
        raw_score = ev.get('score') or ev.get('setScore') or ev.get('result', '')
        if raw_score:
            hg, ag = parse_set_score(str(raw_score))
            if hg > 0 or ag > 0 or str(raw_score) != '':
                home_goals, away_goals = hg, ag
                score = str(raw_score)

        # Option 2: homeScore/awayScore fields
        if home_goals == 0 and away_goals == 0:
            home_goals = int(ev.get('homeScore', 0) or 0)
            away_goals = int(ev.get('awayScore', 0) or 0)
            if home_goals > 0 or away_goals > 0:
                score = f'{home_goals}:{away_goals}'

        # Option 3: Check market 199 (Correct Score) outcomes for resolved result
        if home_goals == 0 and away_goals == 0:
            mkts = ev.get('markets', [])
            for m in mkts:
                if m.get('id') == 199:
                    for o in m.get('outcomes', []):
                        desc = o.get('description', o.get('desc', ''))
                        # Check if this outcome settled (isActive=0 or odds≈1.0)
                        if o.get('isActive') == 0:
                            hg, ag = parse_set_score(desc)
                            if hg > 0 or ag > 0:
                                home_goals, away_goals = hg, ag
                                score = desc
                                break
                    break
            if home_goals > 0 or away_goals > 0:
                score = f'{home_goals}:{away_goals}'

        total_goals = home_goals + away_goals

        # If we couldn't parse a score, skip
        if home_goals == 0 and away_goals == 0 and not score:
            pending += 1
            continue

        checked += 1
        pred_info['actual_score'] = score
        pred_info['total_goals'] = total_goals
        pred_info['status'] = 'settled'
        pred_info['settled_at'] = time.time()

        if total_goals >= 2:
            won += 1
            pred_info['result'] = 'WON'
        else:
            lost += 1
            pred_info['result'] = 'LOST'
            home_name = pred_info.get('home', '')
            away_name = pred_info.get('away', '')
            mk = matchup_key(home_name, away_name)
            if mk not in blacklist:
                blacklist[mk] = {'fails': 0, 'history': []}
            blacklist[mk]['fails'] += 1
            blacklist[mk]['last_fail'] = time.time()
            blacklist[mk]['history'].append({
                'score': score,
                'verdict': pred_info.get('verdict', ''),
                'pct': pred_info.get('pct', 0),
                'odds': pred_info.get('odds', 0),
                'time': time.time(),
                'reason': analyze_failure(pred_info, total_goals),
            })
            new_blacklist_entries.append({
                'match': f'{home_name} v {away_name}',
                'score': score,
                'verdict': pred_info.get('verdict'),
                'reason': analyze_failure(pred_info, total_goals),
            })

        # Accumulate for Section B
        hk = (
            f"{pred_info.get('home', '')}|"
            f"{pred_info.get('away', '')}|"
            f"{pred_info.get('start', 0)}"
        )
        if hk not in existing_ids:
            results_history.append({
                'home': pred_info.get('home', ''),
                'away': pred_info.get('away', ''),
                'score': score,
                'home_goals': home_goals,
                'away_goals': away_goals,
                'total_goals': total_goals,
                'start': pred_info.get('start', 0),
                'timestamp': pred_info.get('timestamp', 0),
                'settled_at': time.time(),
            })
            existing_ids.add(hk)
            new_results_count += 1

    # Prune old predictions (>48h)
    old_cutoff = time.time() - 172800
    for gid in [g for g, info in preds.items() if info.get('timestamp', 0) < old_cutoff]:
        del preds[gid]

    # Prune results older than 3 days
    hist_cutoff = time.time() - 259200
    results_history = [
        r
        for r in results_history
        if r.get('settled_at', r.get('timestamp', 0)) > hist_cutoff
    ]

    save_predictions(preds, preds_sha)
    save_blacklist(blacklist, bl_sha)
    save_results_history(results_history, rh_sha)

    return {
        'checked': checked,
        'won': won,
        'lost': lost,
        'pending': pending,
        'new_blacklist': new_blacklist_entries,
        'win_rate': round(won / checked * 100, 1) if checked > 0 else 0,
        'new_results': new_results_count,
        'total_history': len(results_history),
    }


def harvest_completed_events() -> int:
    """Harvest recent completed events from MSport event list for Section B history.

    Returns the number of newly added events.
    """
    results_history, rh_sha = load_results_history()
    existing_keys: set = set()
    for r in results_history:
        existing_keys.add(
            f"{r.get('home', '')}|{r.get('away', '')}|{r.get('start', '')}"
        )

    try:
        new_count = 0

        # Fetch event list to find finished events
        all_events = fetch_event_list()
        finished_events = [ev for ev in all_events if ev.get('status') == 3]

        for ev in finished_events:
            home = ev.get('homeTeam', '')
            away = ev.get('awayTeam', '')
            start = ev.get('startTime', 0)
            key = f'{home}|{away}|{start}'
            if key in existing_keys:
                continue

            # Extract score
            home_goals = 0
            away_goals = 0
            score = ''

            raw_score = ev.get('score') or ev.get('setScore') or ev.get('result', '')
            if raw_score:
                hg, ag = parse_set_score(str(raw_score))
                home_goals, away_goals = hg, ag
                score = str(raw_score)

            if home_goals == 0 and away_goals == 0:
                home_goals = int(ev.get('homeScore', 0) or 0)
                away_goals = int(ev.get('awayScore', 0) or 0)
                if home_goals > 0 or away_goals > 0:
                    score = f'{home_goals}:{away_goals}'

            if home_goals == 0 and away_goals == 0:
                continue  # No useable score data

            results_history.append({
                'home': home,
                'away': away,
                'score': score,
                'home_goals': home_goals,
                'away_goals': away_goals,
                'total_goals': home_goals + away_goals,
                'start': start,
                'timestamp': (
                    (start / 1000) if start > 1000000000000 else start
                ),
                'settled_at': time.time(),
            })
            existing_keys.add(key)
            new_count += 1

        # If event list didn't have finished events, try the result endpoint
        if new_count == 0 and all_events:
            # Get seasonId and matchDay from first event
            first_ev = all_events[0]
            season_id = first_ev.get('seasonId', '')
            match_day = first_ev.get('matchDay', 0)
            if season_id and match_day:
                for md_offset in range(0, 3):  # Check current and previous matchDays
                    try:
                        md = int(match_day) - md_offset
                        result_events = _fetch_results_for_date(season_id, md)
                        for rev in result_events:
                            home = rev.get('homeTeam', '')
                            away = rev.get('awayTeam', '')
                            start = rev.get('startTime', 0)
                            key = f'{home}|{away}|{start}'
                            if key in existing_keys:
                                continue

                            # Extract score
                            home_goals = int(rev.get('homeScore', 0) or 0)
                            away_goals = int(rev.get('awayScore', 0) or 0)
                            score = f'{home_goals}:{away_goals}'

                            if home_goals == 0 and away_goals == 0:
                                raw = rev.get('score', '')
                                if raw:
                                    hg, ag = parse_set_score(str(raw))
                                    home_goals, away_goals = hg, ag
                                    score = str(raw)

                            if home_goals == 0 and away_goals == 0:
                                continue

                            results_history.append({
                                'home': home,
                                'away': away,
                                'score': score,
                                'home_goals': home_goals,
                                'away_goals': away_goals,
                                'total_goals': home_goals + away_goals,
                                'start': start,
                                'timestamp': (
                                    (start / 1000) if start > 1000000000000 else start
                                ),
                                'settled_at': time.time(),
                            })
                            existing_keys.add(key)
                            new_count += 1
                    except Exception:
                        continue

        if new_count > 0:
            # Prune old
            hist_cutoff = time.time() - 259200
            results_history = [
                r
                for r in results_history
                if r.get('settled_at', r.get('timestamp', 0)) > hist_cutoff
            ]
            save_results_history(results_history, rh_sha)

        return new_count
    except Exception as exc:
        logger.error("Harvest error: %s", exc)
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# Combined Analysis
# ═══════════════════════════════════════════════════════════════════════════

def analyze(
    event: Dict[str, Any],
    blacklist: Dict[str, Any],
    results_history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Combine Section A + Section B + blacklist check for a single event.

    Uses MSport field names: homeTeam, awayTeam, startTime.
    """
    home_name = event.get('homeTeam') or '?'
    away_name = event.get('awayTeam') or '?'
    est = int(event.get('startTime', 0))

    a = sec_a(event)

    slot = find_slot(results_history, est)
    en = energy(slot, home_name, away_name)
    has_section_b = len(slot) > 0

    if has_section_b:
        b = sec_b(en)
        combined = a['sc'] + b['sc']
        cmax = a['mx'] + 14
        cpct = round(combined / cmax * 100) if cmax > 0 else 0

        if b['skip']:
            verdict = 'SKIP'
        elif cpct >= 70:
            verdict = 'LOCK'
        elif cpct >= 50:
            verdict = 'PICK'
        elif cpct >= 35:
            verdict = 'CONSIDER'
        else:
            verdict = 'SKIP'
    else:
        b = {
            'skip': False,
            'reason': 'NO_DATA',
            'sc': 0,
            'conf': 'N/A',
            'reasons': ['No yesterday data'],
        }
        combined = a['sc']
        cmax = a['mx']
        cpct = a['pct']

        if cpct >= 75:
            verdict = 'LOCK'
        elif cpct >= 55:
            verdict = 'PICK'
        elif cpct >= 40:
            verdict = 'CONSIDER'
        else:
            verdict = 'SKIP'

    # Sweet-spot check: O1.5 odds must be within [1.38, 1.60]
    if a['ou15_odds'] > 0 and (
        a['ou15_odds'] < SWEET[0] or a['ou15_odds'] > SWEET[1]
    ):
        verdict = 'SKIP'

    # No O1.5 odds → SKIP
    if a['ou15_odds'] <= 0:
        verdict = 'SKIP'

    # fp11 fingerprint → downgrade
    if a['fp11'] and verdict in ('LOCK', 'PICK'):
        verdict = 'PICK' if verdict == 'LOCK' else 'CONSIDER'

    # Blacklist check
    bl_hit, bl_reason = is_blacklisted(home_name, away_name, blacklist)
    if bl_hit and verdict in ('LOCK', 'PICK', 'CONSIDER'):
        verdict = 'SKIP'

    return {
        'match': f'{home_name} v {away_name}',
        'home': home_name,
        'away': away_name,
        'eid': event.get('eventId', ''),
        'gid': str(event.get('eventId', '')),  # MSport uses eventId as primary key
        'start': est,
        'a': a,
        'b': b,
        'en': en,
        'has_b': has_section_b,
        'combined': combined,
        'cmax': cmax,
        'cpct': cpct,
        'verdict': verdict,
        'ou15_odds': a['ou15_odds'],
        'ou15_oid': a['ou15_oid'],
        'sweet': a['sweet'],
        'fp11': a['fp11'],
        'conf': a['conf'],
        'bl_hit': bl_hit,
        'bl_reason': bl_reason,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Fixture Discovery
# ═══════════════════════════════════════════════════════════════════════════

def discover_all() -> Dict[str, List[Dict[str, Any]]]:
    """Discover upcoming VFL events via MSport event/list API.

    Strategy:
        1. Fetch all events from event/list endpoint.
        2. Group by category name (England, Spain, etc.).
        3. Fetch full event detail (with markets) for each pre-match event.

    Returns a dict keyed by category name, each containing a list of
    event detail dicts with full market data.
    """
    by_league: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    # Fetch all events from the list endpoint
    all_events = fetch_event_list()
    logger.info("  Event list returned %d total events", len(all_events))

    # Group by category
    by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ev in all_events:
        if ev.get('status') != 0:
            continue  # Only pre-match
        cat = ev.get('category', '')
        if cat:
            by_cat[cat].append(ev)

    # Map to our league configs
    for lk, cfg in LEAGUES.items():
        cat_name = cfg['catName']
        events_in_cat = by_cat.get(cat_name, [])
        logger.info("  %s: %d pre-match events from list", cfg['name'], len(events_in_cat))

        if not events_in_cat:
            continue

        # Fetch detail (with markets) for each event in parallel
        eids = [ev['eventId'] for ev in events_in_cat if ev.get('eventId')]
        logger.info("  %s: fetching detail for %d events...", cfg['name'], len(eids))

        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
            details = list(ex.map(_event_detail_wrapper, eids))

        valid = [ev for ev in details if ev is not None]
        logger.info("  %s: got %d valid events with markets", cfg['name'], len(valid))
        if valid:
            by_league[cfg['catName']].extend(valid)

    return dict(by_league)


def _event_detail_wrapper(event_id: str) -> Optional[Dict[str, Any]]:
    """Wrapper for ThreadPoolExecutor mapping — fetch event detail."""
    return fetch_event_detail(event_id)


def discover_via_common_thumbnails() -> Dict[str, List[Dict[str, Any]]]:
    """Alternative discovery: use MSport event/list (same as discover_all).

    This is a compatibility shim — MSport doesn't have a thumbnail endpoint,
    so we use the standard event/list instead.
    """
    return discover_all()


# ═══════════════════════════════════════════════════════════════════════════
# Booking Code Generation (MSport share)
# ═══════════════════════════════════════════════════════════════════════════

def gen_booking(picks: List[Dict[str, Any]]) -> Optional[str]:
    """Generate a booking code for a set of O1.5 picks using MSport.

    MSport booking format uses marketId=18 (O/U), outcomeId, and eventId.
    The endpoint is /orders/share (same concept, MSport implementation).

    Note: MSport may use a different share endpoint. This attempts the
    MSport-compatible booking flow.
    """
    if not picks:
        return None
    outcomes: List[Dict[str, str]] = []
    for p in picks:
        oid = p.get('ou15_oid')
        eid = p.get('eid')
        if not oid or not eid:
            continue
        outcomes.append({
            'eventId': eid,
            'marketId': '18',
            'outcomeId': str(oid),
        })
    if not outcomes:
        return None
    payload = {'selections': outcomes}
    logger.info("Booking %d selections...", len(outcomes))
    try:
        resp = requests.post(
            f'{MS_BASE}/orders/share',
            json=payload,
            headers={**HEADERS, 'Content-Type': 'application/json'},
            timeout=15,
        )
        d = resp.json()
        # MSport may return { code: 0, data: { shareCode: "..." } }
        code = ''
        if isinstance(d, dict):
            data = d.get('data')
            if isinstance(data, dict):
                code = data.get('shareCode', '')
            elif isinstance(data, str):
                code = data
            if not code:
                code = d.get('shareCode', '')
        if code:
            return code
        logger.info("Booking response: %s", json.dumps(d)[:200])
    except Exception as exc:
        logger.error("Booking failed: %s", exc)
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Telegram Output Formatting
# ═══════════════════════════════════════════════════════════════════════════

def format_section(
    picks: List[Dict[str, Any]],
    icon: str,
    label: str,
    code: Optional[str],
    total_odds: float,
) -> List[str]:
    """Format a section of picks (LOCK or PICK) for Telegram message.

    Returns a list of lines.
    """
    if not picks:
        return []
    lines: List[str] = [
        f'{icon} <b>{label} ({len(picks)} sel | {total_odds:.0f}x odds)</b>',
        '',
    ]
    by_time: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for p in picks:
        by_time[p.get('start', 0)].append(p)
    for t in sorted(by_time.keys()):
        dt = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
        lines.append(f'<b>{dt.strftime("%H:%M")} UTC</b>')
        for p in by_time[t]:
            sw = ' [S]' if p['sweet'] else ''
            fp = ' [1:1]' if p['fp11'] else ''
            bconf = p['b']['conf'] if p.get('has_b') else 'N/A'
            bsc = p['b']['sc'] if p.get('has_b') else '-'
            lines.append(
                f'  {icon} {p["match"]} — O1.5 @{p["ou15_odds"]:.2f}{sw}{fp}'
            )
            lines.append(
                f'      A:{p["a"]["pct"]}% B:{bconf}({bsc}/14) C:{p["cpct"]}%'
            )
        lines.append('')

    lines.append(f'<b>ODDS: {total_odds:.0f}x</b>')
    if code:
        lines.append(f'<b>CODE: {code}</b>')
        lines.append(f'msport.com/ng/share/{code}')
    else:
        lines.append('Code: manual entry required')
    return lines


def tg_send(text: str, chat_id: Optional[str] = None, token: Optional[str] = None) -> bool:
    """Send a Telegram message (if token and chat_id are configured).

    This is a passthrough — the calling infrastructure provides credentials.
    Returns True if sent successfully (or if no credentials configured).
    """
    if not token or not chat_id:
        logger.info("Telegram not configured — message would be:\n%s", text[:500])
        return False
    try:
        import requests as req
        api = f'https://api.telegram.org/bot{token}'
        resp = req.post(
            f'{api}/sendMessage',
            json={
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            },
            timeout=15,
        )
        d = resp.json()
        if d.get('ok'):
            return True
        logger.warning("TG error: %s", d.get('description', ''))
    except Exception as exc:
        logger.error("TG send failed: %s", exc)
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Main Scanner / Pipeline
# ═══════════════════════════════════════════════════════════════════════════

def run(
    tg_token: Optional[str] = None,
    tg_chat: Optional[str] = None,
    skip_monitor: bool = False,
    skip_harvest: bool = False,
    discovery_method: str = 'probe',
) -> Dict[str, Any]:
    """Run the full VFL Onimix engine pipeline.

    Phases:
        0. Check past predictions + accumulate results
        0.5. Harvest completed events for Section B
        1. Discover all upcoming VFL events
        2. Analyze each event (Section A + Section B + blacklist)
        3. Sort into tiers (LOCK / PICK / CONSIDER / SKIP)
        4. Generate booking codes
        5. Track predictions for monitoring
        6. Deliver via Telegram (if configured)

    Args:
        tg_token: Telegram bot token (optional).
        tg_chat: Telegram chat ID (optional).
        skip_monitor: Skip Phase 0 (prediction checking).
        skip_harvest: Skip Phase 0.5 (result harvesting).
        discovery_method: 'probe' or 'thumbnail' (both use MSport event/list).

    Returns:
        Summary dict with counts and results.
    """
    scan_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    print('=' * 60)
    print('ONIMIX VFL PROBABILITY DECODER ENGINE v1.0 (MSport)')
    print('Section A (Odds-Based) + Section B + Edge Evaluator + State Persist')
    print(scan_time)
    print('=' * 60)

    print('\n[STATE] /tmp/vfl_state.json')

    # ── PHASE 0: Check past predictions ──
    monitor: Dict[str, Any] = {}
    if not skip_monitor:
        print('\n[PHASE 0] Checking past predictions & accumulating results...')
        monitor = check_past_predictions()
        if monitor.get('checked', 0) > 0:
            print(
                f'  Results: {monitor["checked"]} checked | {monitor["won"]} won | '
                f'{monitor["lost"]} lost | {monitor["win_rate"]}% win rate'
            )
            if monitor.get('new_blacklist'):
                print('  NEW BLACKLIST entries:')
                for bl in monitor['new_blacklist']:
                    print(f'    X {bl["match"]} | {bl["score"]} | {bl["reason"]}')
        else:
            print('  No settled predictions to check yet')
        print(
            f'  Pending: {monitor.get("pending", 0)} | '
            f'New results: {monitor.get("new_results", 0)} | '
            f'Total history: {monitor.get("total_history", 0)}'
        )
    else:
        print('\n[PHASE 0] Skipped')

    # ── PHASE 0.5: Harvest completed events ──
    if not skip_harvest:
        print('\n[PHASE 0.5] Harvesting completed events for Section B...')
        harvested = harvest_completed_events()
        print(f'  Harvested {harvested} new completed events')
    else:
        print('\n[PHASE 0.5] Skipped')
        harvested = 0

    blacklist, _ = load_blacklist()
    results_history, _ = load_results_history()
    bl_count = sum(1 for v in blacklist.values() if v.get('fails', 0) >= 2)
    print(f'  Active blacklist: {bl_count} matchups')
    print(f'  Results history: {len(results_history)} matches available for Section B')

    # ── PHASE 1: Discover events ──
    print('\n[PHASE 1] Discovering all upcoming VFL events...')

    if discovery_method == 'thumbnail':
        all_upcoming = discover_via_common_thumbnails()
    else:
        all_upcoming = discover_all()

    all_results: List[Dict[str, Any]] = []

    for lk, cfg in LEAGUES.items():
        cat_name = cfg['catName']
        events = all_upcoming.get(cat_name, [])
        print(f'\n  {cfg["name"]}: {len(events)} upcoming matches')

        if not events:
            continue

        # Group by round time
        rounds = sorted(set(e['startTime'] for e in events))
        for t in rounds[:5]:
            dt = datetime.fromtimestamp(t / 1000, tz=timezone.utc)
            n = sum(1 for e in events if e['startTime'] == t)
            print(f'    {dt.strftime("%H:%M")} UTC ({n} matches)')
        if len(rounds) > 5:
            print(f'    ... +{len(rounds) - 5} more rounds')

        valid = [e for e in events if e.get('markets')]
        print(f'  Got {len(valid)} valid events with markets')

        for ev in valid:
            r = analyze(ev, blacklist, results_history)
            emoji_map = {'LOCK': 'L', 'PICK': 'P', 'CONSIDER': '?', 'SKIP': 'X'}
            emoji = emoji_map.get(r['verdict'], '?')
            bl = ' [BL]' if r['bl_hit'] else ''
            binfo = (
                f'B:{r["b"]["conf"]}({r["b"]["sc"]})'
                if r['has_b']
                else 'B:N/A'
            )
            print(
                f'  [{emoji}] {r["match"]}: A:{r["a"]["pct"]}% '
                f'{binfo} C:{r["cpct"]}% O1.5@{r["ou15_odds"]:.2f} '
                f'{r["conf"]}{bl}'
            )
            all_results.append(r)

    # ── PHASE 2: Sort and filter ──
    locks = [r for r in all_results if r['verdict'] == 'LOCK']
    picks = [r for r in all_results if r['verdict'] == 'PICK']
    cons = [r for r in all_results if r['verdict'] == 'CONSIDER']
    skips = [r for r in all_results if r['verdict'] == 'SKIP']
    bl_skips = [r for r in all_results if r['bl_hit']]
    b_active = sum(1 for r in all_results if r['has_b'])

    print('\n' + '=' * 60)
    print(
        f'L:{len(locks)} P:{len(picks)} ?:{len(cons)} X:{len(skips)} | '
        f'BL:{len(bl_skips)} | B-active:{b_active}/{len(all_results)}'
    )

    bookable = locks + picks
    if not bookable:
        print('No bookable picks found')
        msg = (
            f'VFL Scan {scan_time}\n'
            f'No bookable picks across {len(all_results)} matches.\n'
            f'Section B: {b_active}/{len(all_results)} active'
        )
        if monitor.get('checked', 0) > 0:
            msg += (
                f'\n\nMonitor: {monitor["won"]}/{monitor["checked"]} '
                f'({monitor["win_rate"]}%)'
            )
        tg_send(msg, tg_chat, tg_token)
        return {
            'status': 'empty',
            'total': len(all_results),
            'locks': 0,
            'picks': 0,
            'b_active': b_active,
            'monitor': monitor,
        }

    dk = dedup_key(bookable)
    if already_sent(dk):
        print('Already sent this exact combo — skipping')
        return {
            'status': 'dedup_skipped',
            'total': len(all_results),
            'locks': len(locks),
            'picks': len(picks),
            'b_active': b_active,
            'monitor': monitor,
        }

    locks.sort(key=lambda x: (x['sweet'], x['cpct']), reverse=True)
    picks.sort(key=lambda x: (x['sweet'], x['cpct']), reverse=True)

    lock_odds = 1.0
    for p in locks:
        lock_odds *= p['ou15_odds']
    pick_odds = 1.0
    for p in picks:
        pick_odds *= p['ou15_odds']

    print(f'\nLOCK ACCA: {len(locks)} @ {lock_odds:.1f}x')
    print(f'PICK ACCA: {len(picks)} @ {pick_odds:.1f}x')

    # ── PHASE 3: Generate booking codes ──
    lock_code = None
    pick_code = None

    if locks:
        print('\nGenerating LOCK booking code...')
        lock_code = gen_booking(locks)
        if lock_code:
            print(f'  LOCK Code: {lock_code}')

    if picks:
        print('\nGenerating PICK booking code...')
        pick_code = gen_booking(picks)
        if pick_code:
            print(f'  PICK Code: {pick_code}')

    # ── PHASE 4: Track predictions for monitoring ──
    preds, preds_sha = load_predictions()
    for p in bookable:
        gid = p['gid']
        preds[gid] = {
            'match': p['match'],
            'home': p['home'],
            'away': p['away'],
            'verdict': p['verdict'],
            'pct': p['cpct'],
            'odds': p['ou15_odds'],
            'signals': p['a']['sig'],
            'conf': p['conf'],
            'start': p['start'],
            'b_score': p['b']['sc'],
            'b_conf': p['b']['conf'],
            'has_b': p['has_b'],
            'eid': p['eid'],
            'timestamp': time.time(),
            'status': 'pending',
        }
    save_predictions(preds, preds_sha)
    print(f'\nTracking {len(bookable)} predictions for monitoring')

    # ── PHASE 5: Telegram delivery ──
    total_sel = len(locks) + len(picks)
    lines: List[str] = [
        '<b>VFL ONIMIX PROBABILITY DECODER (MSport)</b>',
        scan_time,
        f'{total_sel} selections from {len(all_results)} analyzed',
        f'L:{len(locks)} | P:{len(picks)} | Section B: {b_active}/{len(all_results)} active',
    ]

    if monitor.get('checked', 0) > 0:
        lines.append('')
        lines.append(
            f'<b>MONITOR:</b> {monitor["won"]}/{monitor["checked"]} '
            f'({monitor["win_rate"]}%)'
        )
        if monitor.get('new_blacklist'):
            for bl in monitor['new_blacklist'][:3]:
                lines.append(f'  X {bl["match"]} {bl["score"]}')

    lines.append('')

    if locks:
        lines.extend(format_section(locks, 'L', 'LOCK ACCUMULATOR', lock_code, lock_odds))
        lines.append('')

    if picks:
        lines.extend(format_section(picks, 'P', 'PICK ACCUMULATOR', pick_code, pick_odds))
        lines.append('')

    if bl_skips:
        lines.append(f'<i>Blacklisted: {len(bl_skips)} matches skipped</i>')

    lines.extend([
        '',
        '<i>Engine v1.0 (MSport) | A+B Active | Monitor On | /tmp State Persist | ONIMIX TECH</i>',
    ])

    msg = '\n'.join(lines)

    if len(msg) > 4000 and tg_token and tg_chat:
        # Split into two messages
        if locks:
            lock_msg = '\n'.join([
                '<b>VFL ONIMIX (1/2)</b>',
                scan_time,
                '',
            ] + format_section(locks, 'L', 'LOCK ACCUMULATOR', lock_code, lock_odds))
            tg_send(lock_msg, tg_chat, tg_token)
        if picks:
            pick_msg = '\n'.join([
                '<b>VFL ONIMIX (2/2)</b>',
                scan_time,
                '',
            ] + format_section(picks, 'P', 'PICK ACCUMULATOR', pick_code, pick_odds) + [
                '',
                '<i>Engine v1.0 (MSport) | ONIMIX TECH</i>',
            ])
            tg_send(pick_msg, tg_chat, tg_token)
    else:
        tg_send(msg, tg_chat, tg_token)

    mark_sent(dk)
    print('\nScan complete!')

    return {
        'status': 'success',
        'total': len(all_results),
        'locks': len(locks),
        'picks': len(picks),
        'consider': len(cons),
        'skips': len(skips),
        'blacklisted': len(bl_skips),
        'b_active': b_active,
        'lock_odds': round(lock_odds, 2),
        'pick_odds': round(pick_odds, 2),
        'lock_code': lock_code,
        'pick_code': pick_code,
        'monitor': monitor,
        'harvested': harvested,
    }


# ═══════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    """CLI entry point for standalone runs."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Onimix VFL Probability Decoder Engine — Section A + B + Edge Analysis (MSport)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  python vfl_onimix_engine.py\n'
            '  python vfl_onimix_engine.py --no-monitor --discovery thumbnail\n'
            '  python vfl_onimix_engine.py --analyze-event vf:match:1402979759\n'
            '  python vfl_onimix_engine.py --edge-only --event-json event.json\n'
        ),
    )

    parser.add_argument(
        '--no-monitor',
        action='store_true',
        help='Skip Phase 0 (past prediction checking)',
    )
    parser.add_argument(
        '--no-harvest',
        action='store_true',
        help='Skip Phase 0.5 (result harvesting)',
    )
    parser.add_argument(
        '--discovery',
        choices=['probe', 'thumbnail', 'both'],
        default='probe',
        help='Discovery method (default: probe)',
    )
    parser.add_argument(
        '--analyze-event',
        type=str,
        metavar='EVENT_ID',
        help='Analyze a single event by eventId and exit',
    )
    parser.add_argument(
        '--event-json',
        type=str,
        metavar='FILE',
        help='Analyze a single event from a JSON file and exit',
    )
    parser.add_argument(
        '--edge-only',
        action='store_true',
        help='Only run the multi-market edge evaluator (requires --event-json)',
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable debug logging',
    )
    parser.add_argument(
        '--tg-token',
        type=str,
        default=None,
        help='Telegram bot token (overrides env TG_TOKEN)',
    )
    parser.add_argument(
        '--tg-chat',
        type=str,
        default=None,
        help='Telegram chat ID (overrides env TG_CHAT)',
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    tg_token = args.tg_token or os.environ.get('TG_TOKEN')
    tg_chat = args.tg_chat or os.environ.get('TG_CHAT')

    # ── Single-event analysis mode ──
    if args.analyze_event:
        event_id = args.analyze_event
        event = fetch_event_detail(event_id)
        if event is None:
            print(f'Event {event_id} not found or not pre-match')
            sys.exit(1)
        blacklist, _ = load_blacklist()
        results_history, _ = load_results_history()
        result = analyze(event, blacklist, results_history)
        print(json.dumps(result, indent=2, default=str))
        return

    # ── Edge-only analysis mode ──
    if args.edge_only:
        if not args.event_json:
            print('--edge-only requires --event-json')
            sys.exit(1)
        with open(args.event_json) as f:
            event = json.load(f)
        edge_analysis = multi_market_edge_analysis(event)
        print('\n=== Multi-Market Edge Analysis ===')
        print(json.dumps(edge_analysis, indent=2, default=str))
        return

    # ── Single JSON event analysis ──
    if args.event_json:
        with open(args.event_json) as f:
            event = json.load(f)
        blacklist, _ = load_blacklist()
        results_history, _ = load_results_history()
        result = analyze(event, blacklist, results_history)
        print('\n=== Single Event Analysis ===')
        print(json.dumps(result, indent=2, default=str))

        # Also run edge analysis
        edge_analysis = multi_market_edge_analysis(event)
        print('\n=== Multi-Market Edge Analysis ===')
        print(json.dumps(edge_analysis, indent=2, default=str))
        return

    # ── Full pipeline run ──
    skip_monitor = args.no_monitor
    skip_harvest = args.no_harvest
    discovery_method = args.discovery

    # If 'both', try probe first, fall back to thumbnail
    if discovery_method == 'both':
        summary = run(
            tg_token=tg_token,
            tg_chat=tg_chat,
            skip_monitor=skip_monitor,
            skip_harvest=skip_harvest,
            discovery_method='probe',
        )
        if summary.get('total', 0) == 0:
            logger.info("Probe discovery empty, retrying with thumbnail...")
            summary = run(
                tg_token=tg_token,
                tg_chat=tg_chat,
                skip_monitor=skip_monitor,
                skip_harvest=skip_harvest,
                discovery_method='thumbnail',
            )
    else:
        summary = run(
            tg_token=tg_token,
            tg_chat=tg_chat,
            skip_monitor=skip_monitor,
            skip_harvest=skip_harvest,
            discovery_method=discovery_method,
        )

    print('\n=== Summary ===')
    print(json.dumps(summary, indent=2, default=str))


if __name__ == '__main__':
    # Ensure requests is available
    try:
        import requests  # noqa: F401
    except ImportError:
        print("FATAL: 'requests' library is required. Install with: pip install requests")
        sys.exit(1)

    main()
