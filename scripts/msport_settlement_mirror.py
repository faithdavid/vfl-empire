#!/usr/bin/env python3
"""
msport_settlement_mirror.py — VFL Settlement Mirror
====================================================
Mirrors MSport's bet settlement engine to auto-settle all vfl_bets and
vfl_predictions using actual results from the MSport API.

Runs as a cron every ~60 seconds during active matchdays.

Settlement Logic (mirrors MSport):
  1. For each unsettled bet/prediction → resolve season_name → fetch results
  2. Apply _determine_outcome() to each leg/market
  3. Mark won/lost, update bankroll, log P&L

Author: VFL Engineering — Lord FaithDavid's Empire
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Tuple

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))
from common.db_manager import get_db, fetch_all
from common.msport_client import (
    get_results,
    get_season_list,
    get_match_day_info,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SETTLER] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/ubuntu/faith-workspace/vfl-empire/logs/settlement_mirror.log"),
    ]
)
log = logging.getLogger("settler")

# ── Season name resolution cache ─────────────────────────────────────────────
_season_cache: Dict[str, str] = {}   # name → vf:season:XXXXX
_season_cache_loaded = False

def _load_season_cache():
    global _season_cache, _season_cache_loaded
    if _season_cache_loaded:
        return
    try:
        seasons = get_season_list() or []
        for s in seasons:
            name = s.get("seasonName", "")
            sid = s.get("seasonId", "")
            if name and sid:
                _season_cache[name] = sid
        _season_cache_loaded = True
        log.info(f"Loaded {len(_season_cache)} seasons into cache")
    except Exception as e:
        log.warning(f"Failed to load season cache: {e}")

def _resolve_season_id(season_name: Optional[str], matchday: Optional[int]) -> Optional[str]:
    """Resolve season_name → vf:season:XXXXX. Falls back to DB lookup."""
    _load_season_cache()

    if season_name and season_name in _season_cache:
        return _season_cache[season_name]

    # Try DB lookup via vfl_matchdays
    if matchday is not None:
        try:
            with get_db() as cur:
                cur.execute("""
                    SELECT s.season_id, s.season_name
                    FROM vfl_matchdays m
                    JOIN vfl_seasons s ON m.season_id = s.id
                    WHERE m.matchday_number = %s
                    ORDER BY m.id DESC LIMIT 1
                """, (matchday,))
                row = cur.fetchone()
                if row:
                    sid, sname = row[0], row[1]
                    if sname:
                        _season_cache[sname] = sid
                    return sid
        except Exception as e:
            log.warning(f"DB season lookup failed: {e}")

    # Fall back to current live season from MSport
    try:
        info = get_match_day_info()
        if info:
            return info.get("seasonId")
    except Exception:
        pass
    return None

# ── Results cache (avoid hammering API) ─────────────────────────────────────
_results_cache: Dict[Tuple, List] = {}   # (season_id, matchday) → results list
_results_cache_time: Dict[Tuple, float] = {}
RESULTS_TTL = 90  # seconds

def _get_results_cached(season_id: str, matchday: int) -> List[Dict]:
    key = (season_id, matchday)
    now = time.time()
    if key in _results_cache and (now - _results_cache_time.get(key, 0)) < RESULTS_TTL:
        return _results_cache[key]
    try:
        results = get_results(season_id, matchday) or []
        _results_cache[key] = results
        _results_cache_time[key] = now
        return results
    except Exception as e:
        log.warning(f"get_results({season_id}, {matchday}) failed: {e}")
        return []

def _normalize_team(name: str) -> str:
    """Normalise team name for matching."""
    aliases = {
        "manchester red": "manchester red",
        "manchester city": "manchester blue",
        "manchester blue": "manchester blue",
        "man city": "manchester blue",
        "man red": "manchester red",
        "man utd": "manchester red",
        "london guns": "london guns",
        "arsenal": "london guns",
        "wolves": "wolverhampton",
        "wolverhampton wanderers": "wolverhampton",
    }
    n = name.strip().lower()
    return aliases.get(n, n)

def _find_result(results: List[Dict], home: str, away: str) -> Optional[Dict]:
    """Match a fixture string against API results."""
    hn = _normalize_team(home)
    an = _normalize_team(away)
    for r in results:
        rh = _normalize_team(r.get("homeTeam", "") or r.get("home_team", "") or "")
        ra = _normalize_team(r.get("awayTeam", "") or r.get("away_team", "") or "")
        if rh == hn and ra == an:
            return r
    return None

def _parse_score(result: Dict) -> Optional[Tuple[int, int]]:
    """Extract (home_goals, away_goals) from result dict."""
    # Try fullTime field first
    ft = result.get("fullTime") or result.get("full_time") or result.get("score", "")
    if ft and ":" in str(ft):
        try:
            h, a = map(int, str(ft).split(":"))
            return h, a
        except Exception:
            pass
    # Try direct fields
    h = result.get("homeScore") or result.get("home_goals") or result.get("homeGoals")
    a = result.get("awayScore") or result.get("away_goals") or result.get("awayGoals")
    if h is not None and a is not None:
        try:
            return int(h), int(a)
        except Exception:
            pass
    return None

def _determine_outcome(market: str, home_score: int, away_score: int) -> Optional[bool]:
    """
    Mirrors MSport settlement logic exactly.
    Returns True=won, False=lost, None=push/void.
    """
    total = home_score + away_score
    m = market.strip().lower()

    # ── Over / Under ─────────────────────────────────────────────────────
    if "over" in m:
        for t in ["4.5", "3.5", "2.5", "1.5", "0.5"]:
            if t in m:
                return total > float(t)
        return total > 1.5  # default
    if "under" in m:
        for t in ["4.5", "3.5", "2.5", "1.5", "0.5"]:
            if t in m:
                return total < float(t)
        return total < 3.5  # default

    # ── Both Teams to Score ───────────────────────────────────────────────
    if "gg" in m or "btts" in m or "both teams" in m:
        return home_score > 0 and away_score > 0
    if "ng" in m or "no goal" in m:
        return home_score == 0 or away_score == 0

    # ── Draw ─────────────────────────────────────────────────────────────
    if m in ("draw", "x", "d") or "draw" in m:
        return home_score == away_score

    # ── DNB ──────────────────────────────────────────────────────────────
    if "dnb" in m:
        if home_score == away_score:
            return None  # Push / refund
        if "home" in m or m.endswith("1"):
            return home_score > away_score
        if "away" in m or m.endswith("2"):
            return away_score > home_score

    # ── 1X2 ──────────────────────────────────────────────────────────────
    if m in ("home win", "1", "h", "home") or "home win" in m:
        return home_score > away_score
    if m in ("away win", "2", "a", "away") or "away win" in m:
        return away_score > home_score

    return None

# ═══════════════════════════════════════════════════════════════════════════════
# SETTLE VFL_PREDICTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def settle_predictions() -> Dict:
    """Settle all unsettled rows in vfl_predictions table."""
    log.info("Settling vfl_predictions...")
    settled = won = lost = push = 0

    try:
        with get_db() as cur:
            cur.execute("""
                SELECT id, season, match_day, home_team, away_team, prediction
                FROM vfl_predictions
                WHERE settled = 0
                  AND home_team IS NOT NULL AND away_team IS NOT NULL
                ORDER BY id
            """)
            rows = cur.fetchall()
            log.info(f"Found {len(rows)} unsettled predictions")

            # Group by (season, match_day) to batch API calls
            batches: Dict[Tuple, List] = {}
            for row in rows:
                pid, season, md, home, away, pred = row
                season_id = _resolve_season_id(season, md)
                if not season_id:
                    continue
                key = (season_id, md or 0)
                batches.setdefault(key, []).append(row)

            for (season_id, md), preds in batches.items():
                results = _get_results_cached(season_id, md)
                if not results:
                    log.debug(f"No results yet for {season_id} MD{md}")
                    continue

                for (pid, season, match_day, home, away, pred) in preds:
                    r = _find_result(results, home, away)
                    if not r:
                        continue
                    score = _parse_score(r)
                    if not score:
                        continue
                    hg, ag = score

                    outcome = _determine_outcome(pred or "", hg, ag)
                    if outcome is None:
                        result_str = "push"
                    elif outcome:
                        result_str = "won"
                    else:
                        result_str = "lost"

                    cur.execute("""
                        UPDATE vfl_predictions
                        SET settled=1, result=%s, actual_h=%s, actual_a=%s
                        WHERE id=%s
                    """, (result_str, hg, ag, pid))

                    if outcome is True:
                        won += 1
                    elif outcome is False:
                        lost += 1
                    else:
                        push += 1
                    settled += 1

        log.info(f"Predictions settled: {settled} (W:{won} L:{lost} P:{push})")
        return {"settled": settled, "won": won, "lost": lost, "push": push}

    except Exception as e:
        log.error(f"settle_predictions failed: {e}", exc_info=True)
        return {"error": str(e)}

# ═══════════════════════════════════════════════════════════════════════════════
# SETTLE VFL_BETS
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_legs(match_str: str, market_str: str, bet_type: str) -> List[Tuple[str, str, str]]:
    """
    Returns list of (home, away, market) tuples from a bet's match + market fields.
    Handles both single and parlay bets.
    """
    legs = []
    if not match_str:
        return legs

    fixtures = [f.strip() for f in match_str.split(",") if " vs " in f]
    markets_list = [m.strip() for m in market_str.split(",")] if market_str else []

    for i, fixture in enumerate(fixtures):
        parts = fixture.split(" vs ")
        if len(parts) != 2:
            continue
        home, away = parts[0].strip(), parts[1].strip()

        if bet_type == "single":
            market = market_str or "Over 1.5 Goals"
        else:
            market = markets_list[i] if i < len(markets_list) else "Over 1.5 Goals"
            if market.lower() in ("parlay", ""):
                market = "Over 1.5 Goals"

        legs.append((home, away, market))

    return legs

def settle_bets() -> Dict:
    """Settle all unsettled rows in vfl_bets using MSport API results."""
    log.info("Settling vfl_bets...")
    settled = won = lost = push = 0
    total_profit = 0.0

    try:
        with get_db() as cur:
            cur.execute("""
                SELECT id, match, market, odds, stake, matchday,
                       season_name, event_id, bet_type, confidence
                FROM vfl_bets
                WHERE settled = False
                ORDER BY id
            """)
            rows = cur.fetchall()
            log.info(f"Found {len(rows)} unsettled bets")

            # Group by (season_id, matchday)
            batches: Dict[Tuple, List] = {}
            for row in rows:
                bid, match, market, odds, stake, md, season_name, event_id, bet_type, conf = row
                season_id = _resolve_season_id(season_name, md)
                if not season_id:
                    # Try current season if matchday is recent
                    try:
                        info = get_match_day_info()
                        if info:
                            season_id = info.get("seasonId")
                    except Exception:
                        pass
                if not season_id:
                    continue
                key = (season_id, md or 0)
                batches.setdefault(key, []).append(row)

            for (season_id, md), bets in batches.items():
                results = _get_results_cached(season_id, md)
                if not results:
                    log.debug(f"No results for {season_id} MD{md}")
                    continue

                for (bid, match, market, odds, stake, matchday, season_name,
                     event_id, bet_type, conf) in bets:
                    odds_val = float(odds or 1.0)
                    stake_val = float(stake or 0.0)

                    legs = _parse_legs(match or "", market or "", bet_type or "single")
                    if not legs:
                        continue

                    # Determine outcome for each leg
                    leg_outcomes = []
                    leg_scores = []
                    for (home, away, leg_market) in legs:
                        r = _find_result(results, home, away)
                        if not r:
                            leg_outcomes.append(None)
                            leg_scores.append(None)
                            continue
                        score = _parse_score(r)
                        if not score:
                            leg_outcomes.append(None)
                            leg_scores.append(None)
                            continue
                        hg, ag = score
                        leg_scores.append((hg, ag))
                        outcome = _determine_outcome(leg_market, hg, ag)
                        leg_outcomes.append(outcome)

                    # Can't settle if any leg result is missing
                    if any(o is None and s is None for o, s in zip(leg_outcomes, leg_scores)):
                        continue

                    # Parlay: one loss = all lost
                    if any(o is False for o in leg_outcomes):
                        status = "lost"
                        profit = -stake_val
                        payout = 0.0
                    elif all(o is True for o in leg_outcomes):
                        status = "won"
                        payout = round(stake_val * odds_val, 2)
                        profit = round(payout - stake_val, 2)
                    else:
                        # Pushes — refund
                        status = "push"
                        payout = stake_val
                        profit = 0.0

                    # Get actual scores for logging (first leg)
                    first_score = leg_scores[0] if leg_scores else None
                    hg_log = first_score[0] if first_score else None
                    ag_log = first_score[1] if first_score else None

                    cur.execute("""
                        UPDATE vfl_bets
                        SET settled=True, status=%s, payout=%s, profit=%s,
                            home_score=%s, away_score=%s,
                            result_at=NOW()
                        WHERE id=%s
                    """, (status, payout, profit, hg_log, ag_log, bid))

                    # Update bankroll if payout
                    if payout > 0:
                        cur.execute("""
                            UPDATE bankroll
                            SET current_balance = current_balance + %s,
                                updated_at = NOW()
                        """, (payout,))

                    total_profit += profit
                    if status == "won":
                        won += 1
                    elif status == "lost":
                        lost += 1
                    else:
                        push += 1
                    settled += 1

        log.info(f"Bets settled: {settled} (W:{won} L:{lost} P:{push}) profit={total_profit:+.2f}")
        return {
            "settled": settled,
            "won": won,
            "lost": lost,
            "push": push,
            "total_profit": round(total_profit, 2),
        }

    except Exception as e:
        log.error(f"settle_bets failed: {e}", exc_info=True)
        return {"error": str(e)}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def run_once():
    log.info("=== Settlement Mirror Cycle ===")
    t = time.time()
    br = settle_bets()
    pr = settle_predictions()
    elapsed = time.time() - t
    log.info(f"Cycle complete in {elapsed:.1f}s | bets={br} | predictions={pr}")
    return br, pr

def run_loop(interval: int = 60):
    log.info(f"Settlement Mirror started — interval={interval}s")
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log.info("Stopped by user")
            break
        except Exception as e:
            log.error(f"Loop error: {e}", exc_info=True)
        time.sleep(interval)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    if args.once:
        run_once()
    else:
        run_loop(args.interval)
