#!/usr/bin/env python3
"""
vfl_rapid_daemon.py — Real-time VFLM Betting Daemon
=====================================================
Polls MSport API every 60s, detects new events + results,
places bets automatically (1 best pick per matchday cycle),
handles overlapping MD cycles, tracks league table.

Architecture:
  - Continuous loop with 60s sleep between cycles
  - State persisted in signals/rapid_state.json
  - Bankroll tracked in signals/bankroll.json
  - Uses MSport API (no browser) for polling
  - Uses browser_bet_placer.py via subprocess for actual placement
  - Prediction Gate (run_all_gates) as quality filter
  - Finite State Space filter (pre-filter) blocks known trap pairs
  - Only ONE bet per matchday cycle (highest H2H confidence)

Usage:
    python vfl_rapid_daemon.py              # Start continuous loop
    python vfl_rapid_daemon.py --once       # Run single cycle (verification)
    python vfl_rapid_daemon.py --dry-run    # Analyze without placing bets

Author: VFL Engineering Team
"""

import json
import logging
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Multi-market pair betting analysis (per-pair Poisson-based rules)
from pair_betting_rules import get_best_market_for_pair, load_finite_state_data, analyze_all_pairs

# ──────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
EMPIRE_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
SERVICES_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/services")
SCRIPTS_DIR = EMPIRE_DIR
BET_PLACER = SCRIPTS_DIR / "browser_bet_placer.py"

# Add to sys.path for direct imports
for p in [str(EMPIRE_DIR), str(SERVICES_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# State files
STATE_FILE = BASE_DIR / "signals" / "rapid_state.json"
BANKROLL_FILE = BASE_DIR / "signals" / "bankroll.json"
LEDGER_FILE = BASE_DIR / "signals" / "bet_ledger.json"

# Logging
LOG_FILE = "/tmp/vfl_rapid_daemon.log"

# Constants
POLL_INTERVAL = 60  # seconds
FLAT_STAKE = 50.0   # Naira per bet
PLACER_TIMEOUT = 120  # seconds for browser bet placement
RECOVERY_THRESHOLD = 300.0  # Naira stop-loss threshold for recovery mode

# Pause file
PAUSED_FILE = BASE_DIR / "signals" / "PAUSED.json"

# ──────────────────────────────────────────────────────────────────────
# LOGGING SETUP
# ──────────────────────────────────────────────────────────────────────
def setup_logging():
    """Configure dual logging: file + stdout."""
    logger = logging.getLogger("vfl_rapid_daemon")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler (always)
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Stdout handler → change to STDERR so log noise doesn't pollute Discord output
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


log = setup_logging()

# ──────────────────────────────────────────────────────────────────────
# MULTI-MARKET RULES CACHE
# ──────────────────────────────────────────────────────────────────────
_MULTI_MARKET_RULES_CACHE: Optional[Dict] = None  # Lazy-loaded cache

def _get_multi_market_rules() -> dict:
    """Load and cache the per-pair multi-market betting rules (240 pairs).

    Returns dict of 'Home vs Away' -> rule_data, or empty dict on failure.
    Caches after first load for efficiency across fixture evaluations.
    """
    global _MULTI_MARKET_RULES_CACHE
    if _MULTI_MARKET_RULES_CACHE is not None:
        return _MULTI_MARKET_RULES_CACHE
    try:
        data = load_finite_state_data()
        rules, _ = analyze_all_pairs(data)
        _MULTI_MARKET_RULES_CACHE = rules
        log.info(f"Multi-market rules loaded: {len(rules)} fixture pairs across all tiers")
    except Exception as e:
        log.warning(f"Could not load multi-market rules: {e}")
        _MULTI_MARKET_RULES_CACHE = {}
    return _MULTI_MARKET_RULES_CACHE


def _build_market_odds_for_multi(odds_dict: dict) -> dict:
    """Map daemon odds keys → market names expected by get_best_market_for_pair.

    Maps o15→O1.5, o25→O2.5, u35→U3.5, gg→GG, ng→NG, dnb_home→DNB_Home.
    Only includes valid odds (>1.0).
    """
    mapping = {
        "O1.5": odds_dict.get("o15"),
        "O2.5": odds_dict.get("o25"),
        "U3.5": odds_dict.get("u35"),
        "GG": odds_dict.get("gg"),
        "NG": odds_dict.get("ng"),
        "DNB_Home": odds_dict.get("dnb_home"),
    }
    return {k: v for k, v in mapping.items() if v is not None and v > 1.0}


# ──────────────────────────────────────────────────────────────────────
# MARKETS WE TRACK (all 6)
# ──────────────────────────────────────────────────────────────────────
# Each market: (canonical_key, display_name, odds_extraction_info)
ALL_MARKETS = [
    ("O1.5", "Over 1.5 Goals"),
    ("O2.5", "Over 2.5 Goals"),
    ("U2.5", "Under 2.5 Goals"),
    ("U3.5", "Under 3.5 Goals"),
    ("GG", "Goal-Goal (BTTS Yes)"),
    ("NG", "No Goal (BTTS No)"),
    ("DNB", "Draw No Bet (Home)"),
]


# ──────────────────────────────────────────────────────────────────────
# STATE MANAGEMENT
# ──────────────────────────────────────────────────────────────────────

DEFAULT_STATE = {
    "known_event_ids": [],
    "pending_season_id": None,
    "last_poll_time": None,
    "placed_bet_ids": [],
    "placed_bet_events": {},  # event_id -> {market, odds, stake, matchday, season_id, placed_at}
    "matchday_status": {},
    "seen_finished_event_ids": [],
    "cycle_count": 0,
}


def load_state() -> dict:
    """Load state from rapid_state.json, creating default if missing."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            # Ensure all keys exist
            for k, v in DEFAULT_STATE.items():
                if k not in data:
                    data[k] = v
            return data
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Could not load state file: {e}. Creating new state.")
    return dict(DEFAULT_STATE)


def save_state(state: dict):
    """Persist state to rapid_state.json."""
    state["last_poll_time"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def load_bankroll() -> dict:
    """Load bankroll or create default."""
    defaults = {
        "active_base": FLAT_STAKE * 5,  # Start with enough for a few bets
        "reserve": 50.0,
        "total": FLAT_STAKE * 5 + 50.0,
        "profit_locked": 0.0,
        "cycle": 1,
        "wins_in_cycle": 0,
        "net_profit": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": None,
    }
    if BANKROLL_FILE.exists():
        try:
            with open(BANKROLL_FILE) as f:
                data = json.load(f)
            for k, v in defaults.items():
                if k not in data:
                    data[k] = v
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return dict(defaults)


def save_bankroll(bankroll: dict):
    """Persist bankroll."""
    bankroll["updated_at"] = datetime.now(timezone.utc).isoformat()
    bankroll["total"] = round(
        bankroll.get("active_base", 0) + bankroll.get("reserve", 0) + bankroll.get("profit_locked", 0), 2
    )
    BANKROLL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BANKROLL_FILE, "w") as f:
        json.dump(bankroll, f, indent=2)


def load_ledger() -> list:
    """Load bet ledger. Returns list of bet entries."""
    if LEDGER_FILE.exists():
        try:
            with open(LEDGER_FILE) as f:
                data = json.load(f)
            # Support both list format and {bets: [...]} format
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                bets = data.get("bets", data.get("entries", []))
                if isinstance(bets, list):
                    return bets
            return []
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_ledger(ledger: list):
    """Save bet ledger entry."""
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Preserve existing format: {bets: [...], bankroll: {...}}
    existing = {}
    if LEDGER_FILE.exists():
        try:
            with open(LEDGER_FILE) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    if isinstance(existing, dict) and "bets" in existing:
        existing["bets"] = ledger
        with open(LEDGER_FILE, "w") as f:
            json.dump(existing, f, indent=2, default=str)
    else:
        with open(LEDGER_FILE, "w") as f:
            json.dump(ledger, f, indent=2, default=str)


# ──────────────────────────────────────────────────────────────────────
# STATE PRUNING & SEASON DETECTION
# ──────────────────────────────────────────────────────────────────────

def prune_old_events(state: dict):
    """Remove stale event_ids from tracking containers.

    Caps list-based containers at 500 entries (implicitly pruning the
    oldest IDs).  For placed_bet_events (which carry timestamps) entries
    older than 24 hours are removed explicitly.
    """
    now = datetime.now(timezone.utc)
    max_items = 500

    # Cap plain-ID lists (oldest entries drop off naturally)
    for key in ("known_event_ids", "placed_bet_ids", "seen_finished_event_ids"):
        lst = state.get(key, [])
        if len(lst) > max_items:
            state[key] = lst[-max_items:]

    # Prune placed_bet_events by age (these have placed_at timestamps)
    placed_events = state.get("placed_bet_events", {})
    pruned = {}
    for eid, info in placed_events.items():
        placed_at = info.get("placed_at")
        if placed_at:
            try:
                placed_time = datetime.fromisoformat(placed_at)
                if (now - placed_time).total_seconds() < 86400:
                    pruned[eid] = info
            except (ValueError, TypeError):
                pruned[eid] = info  # keep if date is unparseable
        else:
            pruned[eid] = info  # keep if no timestamp
    state["placed_bet_events"] = pruned

    log.info(
        f"Pruned state: known={len(state.get('known_event_ids', []))}, "
        f"placed_ids={len(state.get('placed_bet_ids', []))}, "
        f"seen_finished={len(state.get('seen_finished_event_ids', []))}, "
        f"placed_events={len(state['placed_bet_events'])}"
    )


def detect_new_season(state: dict, current_season_id: Optional[str]) -> bool:
    """Detect when season_id changes and clear all event tracking for the old season.

    Returns True if a season change was detected and tracking was cleared.
    """
    old_season = state.get("pending_season_id")
    if old_season and current_season_id and old_season != current_season_id:
        log.info(
            f"Season change detected: {old_season} -> {current_season_id}. "
            "Clearing event tracking sets."
        )
        state["known_event_ids"] = []
        state["placed_bet_ids"] = []
        state["placed_bet_events"] = {}
        state["seen_finished_event_ids"] = []
        state["matchday_status"] = {}
        state["pending_season_id"] = current_season_id
        log.info(f"Event tracking cleared for new season {current_season_id}")
        return True
    return False


# ──────────────────────────────────────────────────────────────────────
# MSport API INTEGRATION
# ──────────────────────────────────────────────────────────────────────

def fetch_events() -> Optional[List[Dict]]:
    """Fetch matchdays from MSport API via shared client."""
    try:
        from common.msport_client import get_event_list
        data = get_event_list()
        if data is None:
            log.warning("MSport API returned None")
            return None
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Try various response wrappers
            return data.get("matchDays") or data.get("list") or data.get("records") or []
        log.warning(f"Unexpected MSport API response type: {type(data)}")
        return None
    except Exception as e:
        log.error(f"Failed to fetch events from MSport API: {e}")
        return None


def extract_odds(event: dict) -> Dict[str, Optional[float]]:
    """Extract all relevant odds from a MSport event's markets.

    Actual MSport API format (from get_event_list()):
      Market: name="Over/Under", specifiers="total=1.5"/"total=2.5"/"total=3.5"
              outcomes: {"description": "Over 1.5"/"Under 1.5"/..., "odds": "1.35"}
      Market: name="GG/NG", specifiers=""
              outcomes: {"description": "Yes"/"No", "odds": "1.55"}

    Returns dict with keys: o15, o25, u25, u35, gg, ng
    Missing markets get None values.
    """
    odds: Dict[str, Optional[float]] = {
        "o15": None, "o25": None, "u25": None,
        "u35": None, "gg": None, "ng": None,
        "dnb_home": None, "dnb_away": None,
    }
    markets = event.get("markets") or []

    for mk in markets:
        name = mk.get("name") or ""
        spec = mk.get("specifiers") or ""
        outcomes = mk.get("outcomes") or []

        for o in outcomes:
            desc = (o.get("description") or o.get("name") or "").strip()
            raw_val = o.get("odds") or o.get("price")
            if raw_val is None:
                continue
            try:
                val = float(raw_val)
            except (ValueError, TypeError):
                continue
            if val <= 1.0:
                continue

            if name == "Over/Under":
                if spec == "total=1.5":
                    if desc == "Over 1.5":
                        odds["o15"] = val
                elif spec == "total=2.5":
                    if desc == "Over 2.5":
                        odds["o25"] = val
                    elif desc == "Under 2.5":
                        odds["u25"] = val
                elif spec == "total=3.5":
                    if desc == "Under 3.5":
                        odds["u35"] = val
            elif name == "GG/NG":
                if desc == "Yes":
                    odds["gg"] = val
                elif desc == "No":
                    odds["ng"] = val
            elif name == "DNB":
                if desc == "Home" or o.get("id") in (4, "4"):
                    odds["dnb_home"] = val
                elif desc == "Away" or o.get("id") in (5, "5"):
                    odds["dnb_away"] = val

    return odds



# ──────────────────────────────────────────────────────────────────────
# FIXTURE ANALYSIS ENGINE
# ──────────────────────────────────────────────────────────────────────

def analyze_fixture(home: str, away: str, odds_dict: Dict[str, float],
                    league_table: Optional[List[Dict]] = None,
                    season_id: Optional[str] = None) -> Dict[str, Any]:
    """Run full analysis on a fixture: cluster + H2H + all 6 markets.

    Returns ranked picks with all analysis data.
    """
    result = {
        "home": home,
        "away": away,
        "odds": odds_dict,
        "cluster": None,
        "h2h": None,
        "markets": [],
        "best_pick": None,
        "finite_state": None,
        "error": None,
    }

    # 0. Finite State Space filter (trap detection — pre-filter before any analysis)
    try:
        from finite_state_filter import FiniteStateFilter
        fsf = FiniteStateFilter()
        # Check O1.5 as the primary market (most common trap)
        fs_result = fsf.check_pair(home, away, 'O1.5')
        result['finite_state'] = fs_result
        if fs_result['verdict'] == 'FAIL':
            log.warning(f"🚫 TRAP AVOIDED: {home} vs {away} — {fs_result['reason']}")
            result['error'] = f"TRAP: {fs_result['reason']}"
            return result
        log.debug(f"  FiniteState: {home} vs {away} — {fs_result['reason']}")
    except Exception as e:
        result['finite_state'] = {'verdict': 'PASS', 'details': f'Gate error: {e}'}
        log.debug(f"  FiniteState check skipped: {e}")

    # 1. Cluster classification
    try:
        from odds_cluster_classifier import classify_match
        o15 = odds_dict.get("o15")
        o25 = odds_dict.get("o25")
        gg = odds_dict.get("gg")
        u35 = odds_dict.get("u35")
        if all(x is not None and x > 1.0 for x in [o15, o25, gg, u35]):
            cluster_result = classify_match(o15, o25, gg, u35)
            result["cluster"] = cluster_result
        else:
            result["cluster"] = {"cluster_id": -1, "error": "Insufficient odds for classification"}
    except Exception as e:
        result["cluster"] = {"cluster_id": -1, "error": str(e)}

    # 2. H2H analysis for ALL 6 markets
    markets_scored = []
    for mkt_key, mkt_display in ALL_MARKETS:
        # Get the relevant odds for this market
        mkt_odds = None
        if mkt_key == "O1.5":
            mkt_odds = odds_dict.get("o15")
        elif mkt_key == "O2.5":
            mkt_odds = odds_dict.get("o25")
        elif mkt_key == "U2.5":
            mkt_odds = odds_dict.get("u25")
        elif mkt_key == "U3.5":
            mkt_odds = odds_dict.get("u35")
        elif mkt_key == "GG":
            mkt_odds = odds_dict.get("gg")
        elif mkt_key == "NG":
            mkt_odds = odds_dict.get("ng")
        elif mkt_key == "DNB":
            mkt_odds = odds_dict.get("dnb_home")


        if mkt_odds is None or mkt_odds <= 1.0:
            markets_scored.append({
                "market": mkt_key,
                "display": mkt_display,
                "odds": mkt_odds,
                "h2h": None,
                "h2h_status": "NO_ODDS",
                "confidence": 0,
            })
            continue

        # Run H2H gate for this market
        try:
            from prediction_gate import gate_h2h
            h2h_result = gate_h2h(home, away, mkt_key, mkt_odds)
            markets_scored.append({
                "market": mkt_key,
                "display": mkt_display,
                "odds": mkt_odds,
                "h2h": h2h_result,
                "h2h_status": h2h_result.get("status", "ERROR"),
                "n_matches": h2h_result.get("n_matches", 0),
                "hit_rate": _get_h2h_hit_rate(h2h_result, mkt_key),
                "confidence": _compute_market_confidence(h2h_result, mkt_key),
            })
        except Exception as e:
            markets_scored.append({
                "market": mkt_key,
                "display": mkt_display,
                "odds": mkt_odds,
                "h2h": None,
                "h2h_status": "ERROR",
                "error": str(e),
                "confidence": 0,
            })

    result["markets"] = markets_scored

    # 2b. Position-conditional adjustment (if league_table available)
    result["position_adjustment"] = None
    if league_table and season_id:
        try:
            from vfl_positional_integration import get_position_adjustment, apply_position_adjustment
            pos_adj = get_position_adjustment(
                home, away, season_id=season_id, league_table=league_table
            )
            result["position_adjustment"] = pos_adj
            log.debug(f"  Position context: {home}=#{pos_adj.get('home_position','?')} "
                      f"({pos_adj.get('home_zone','?')}), "
                      f"{away}=#{pos_adj.get('away_position','?')} "
                      f"({pos_adj.get('away_zone','?')}) "
                      f"→ {pos_adj.get('zone_matchup','?')} "
                      f"(conf={pos_adj.get('position_confidence',0):.0f})")

            # Apply position adjustment to each market's hit rate & confidence
            if pos_adj.get("position_confidence", 0) >= 30:
                for m in markets_scored:
                    if m.get("h2h") and m.get("h2h_status") == "PASS":
                        adj_h2h = apply_position_adjustment(m["h2h"], pos_adj)
                        if adj_h2h.get("position_applied"):
                            # Update hit rate with adjusted value
                            mkt_key = m["market"]
                            if mkt_key == "O1.5" and "adjusted_o1_5_rate" in adj_h2h:
                                m["hit_rate"] = adj_h2h["adjusted_o1_5_rate"] / 100.0
                            elif mkt_key == "O2.5" and "adjusted_o2_5_rate" in adj_h2h:
                                m["hit_rate"] = adj_h2h["adjusted_o2_5_rate"] / 100.0
                            elif mkt_key == "U2.5" and "adjusted_o2_5_rate" in adj_h2h:
                                # Invert for under
                                m["hit_rate"] = 1.0 - (adj_h2h["adjusted_o2_5_rate"] / 100.0)
                            elif mkt_key == "GG" and "adjusted_gg_rate" in adj_h2h:
                                m["hit_rate"] = adj_h2h["adjusted_gg_rate"] / 100.0
                            elif mkt_key == "NG" and "adjusted_gg_rate" in adj_h2h:
                                m["hit_rate"] = 1.0 - (adj_h2h["adjusted_gg_rate"] / 100.0)
                            elif mkt_key == "U3.5":
                                # Use avg_total_goals proxy - same logic as before but with position
                                avg = adj_h2h.get("avg_total_goals", 2.5)
                                if avg <= 2.0:
                                    m["hit_rate"] = 0.85
                                elif avg <= 2.5:
                                    m["hit_rate"] = 0.75
                                elif avg <= 3.0:
                                    m["hit_rate"] = 0.60
                                else:
                                    m["hit_rate"] = 0.40
                            m["position_adjusted"] = True
                            m["position_confidence"] = pos_adj.get("position_confidence", 0)
        except ImportError:
            pass  # Position module not available
        except Exception as e:
            log.debug(f"Position adjustment error: {e}")

    # 3. Rank by H2H hit rate (higher = more likely to win)
    scored_markets = [m for m in markets_scored if m.get("confidence", 0) > 0]
    scored_markets.sort(key=lambda m: (
        m.get("confidence", 0),
        1.0 / m.get("odds", 100) if m.get("odds") and m["odds"] > 0 else 0,
    ), reverse=True)

    if scored_markets:
        result["best_pick"] = scored_markets[0]

    # ── 4. Multi-Market Arbitrator ────────────────────────────────────
    # Calls get_best_market_for_pair() which uses Poisson-modelled probabilities
    # for all 14 markets per pair. When live odds are available it computes
    # true EV. If the recommended market has positive EV (or elite probability)
    # AND passes H2H, it overrides the H2H-based best_pick.
    # ──────────────────────────────────────────────────────────────────
    result["multi_market"] = None
    try:
        all_rules = _get_multi_market_rules()
        if not all_rules:
            log.debug("  Multi-Market: no rules available (cache empty)")
        else:
            # Build market_odds dict for EV computation (only live odds)
            mkt_odds_map = _build_market_odds_for_multi(odds_dict)
            if mkt_odds_map:
                mm_result = get_best_market_for_pair(
                    home, away, all_rules=all_rules, market_odds=mkt_odds_map
                )
            else:
                # No live odds — get highest-probability recommendation
                mm_result = get_best_market_for_pair(
                    home, away, all_rules=all_rules, market_odds=None
                )
            result["multi_market"] = mm_result

            if mm_result.get("found") and scored_markets:
                mm_market = mm_result["best_market"]
                mm_ev = mm_result.get("best_ev")
                mm_prob = mm_result.get("best_prob", 0)
                mm_verdict = mm_result.get("best_verdict", "?")
                mm_all_evs = mm_result.get("all_evs", {})

                # ── Log the selection ──
                if mm_ev is not None:
                    all_ev_log = " | ".join(
                        f"{k}:{v:+.4f}" for k, v in sorted(mm_all_evs.items())
                    )
                    log.info(
                        f"  🎯 Multi-Market: {home} vs {away} → {mm_market} "
                        f"(EV={mm_ev:+.4f}, {mm_verdict}) [{all_ev_log}]"
                    )
                else:
                    log.info(
                        f"  🎯 Multi-Market: {home} vs {away} → {mm_market} "
                        f"({mm_prob*100:.1f}% prob, {mm_verdict})"
                    )

                # ── Decision: adopt or not ──
                mm_in_scored = [m for m in scored_markets if m["market"] == mm_market]
                if mm_in_scored:
                    mm_entry = mm_in_scored[0]
                    h2h_ok = mm_entry.get("h2h_status") == "PASS"
                    conf_ok = mm_entry.get("confidence", 0) > 0

                    should_adopt = False
                    reason = ""

                    # Condition A: Positive EV + H2H passed → automatic adoption
                    if mm_ev is not None and mm_ev > 0 and h2h_ok:
                        should_adopt = True
                        reason = f"positive EV ({mm_ev:+.4f}) + H2H pass"
                    # Condition B: Elite probability (>=80%) + H2H passed
                    elif mm_prob >= 0.80 and h2h_ok:
                        should_adopt = True
                        reason = f"elite prob ({mm_prob*100:.1f}%) + H2H pass"
                    # Condition C: Positive EV even without H2H if no other pick
                    elif mm_ev is not None and mm_ev > 0 and not scored_markets:
                        should_adopt = True
                        reason = f"positive EV ({mm_ev:+.4f}) — only available pick"
                    # Condition D: Good prob (>=70%) + H2H passed + market confidence > 50
                    elif mm_prob >= 0.70 and h2h_ok and mm_entry.get("confidence", 0) > 50:
                        should_adopt = True
                        reason = f"good prob ({mm_prob*100:.1f}%) + H2H pass (conf={mm_entry['confidence']:.0f})"

                    if should_adopt and conf_ok:
                        old_conf = mm_entry.get("confidence", 0)
                        mm_entry["confidence"] = max(old_conf, 90.0)
                        mm_entry["multi_market_ev"] = mm_ev
                        mm_entry["multi_market_selected"] = True
                        scored_markets.sort(
                            key=lambda m: m.get("confidence", 0), reverse=True
                        )
                        result["best_pick"] = scored_markets[0]
                        result["multi_market_adopted"] = True
                        log.info(
                            f"    ✅ Adopted: {mm_market} ({reason})"
                            f" — confidence {old_conf:.0f}→{mm_entry['confidence']:.0f}"
                        )
                    elif should_adopt and not conf_ok:
                        log.info(
                            f"    ⚠️ Would adopt {mm_market} ({reason}) "
                            f"but H2H confidence is 0 (H2H status={mm_entry.get('h2h_status')})"
                        )
                    else:
                        log.info(
                            f"    ℹ️ {mm_market} not adopted "
                            f"(EV={mm_ev}, prob={mm_prob*100:.1f}%, "
                            f"H2H={'PASS' if h2h_ok else mm_entry.get('h2h_status', '?')})"
                        )
                else:
                    log.info(
                        f"    ℹ️ Multi-Market recommends '{mm_market}' but this market "
                        f"is not in daemon's tracked set. "
                        f"Scored: {[m['market'] for m in scored_markets]}"
                    )
            elif mm_result.get("found"):
                log.debug(f"  Multi-Market: no H2H-scored markets to evaluate")
            else:
                log.debug(f"  Multi-Market: no rules for {home} vs {away}")
    except Exception as e:
        log.debug(f"  Multi-Market analysis skipped: {e}")
        result["multi_market"] = {"error": str(e)}

    return result


def _get_h2h_hit_rate(h2h_result: dict, market_key: str) -> float:
    """Extract the relevant hit rate from H2H result based on market."""
    if not h2h_result:
        return 0.0
    if market_key == "O1.5":
        return h2h_result.get("o1_5_rate", 0) / 100.0
    elif market_key == "O2.5":
        return h2h_result.get("o2_5_rate", 0) / 100.0
    elif market_key == "U2.5":
        u2_5_rate = 100.0 - h2h_result.get("o2_5_rate", 100)
        return u2_5_rate / 100.0
    elif market_key == "U3.5":
        # Use avg_total_goals as proxy
        avg = h2h_result.get("avg_total_goals", 0)
        if avg is None:
            return 0.0
        # Rough: lower avg goals = higher U3.5 rate
        if avg <= 2.0:
            return 0.85
        elif avg <= 2.5:
            return 0.75
        elif avg <= 3.0:
            return 0.60
        else:
            return 0.40
    elif market_key == "GG":
        return h2h_result.get("gg_rate", 0) / 100.0
    elif market_key == "NG":
        ng_rate = 100.0 - h2h_result.get("gg_rate", 100)
        return ng_rate / 100.0
    elif market_key == "DNB":
        h_rate = h2h_result.get("home_win_rate", 0)
        a_rate = h2h_result.get("away_win_rate", 0)
        if h_rate + a_rate > 0:
            return h_rate / (h_rate + a_rate)
        return 0.0
    return 0.0



def _compute_market_confidence(h2h_result: dict, market_key: str) -> float:
    """Compute a confidence score (0-100) for a market based on H2H data."""
    if not h2h_result:
        return 0.0
    status = h2h_result.get("status", "INSUFFICIENT_DATA")
    n = h2h_result.get("n_matches", 0)

    if status == "FAIL":
        return 0.0
    if status == "INSUFFICIENT_DATA" or n < 5:
        return 0.0  # Need at least 5 H2H meetings
    if status != "PASS":
        return 0.0

    # Base confidence from sample size
    sample_conf = min(n / 20.0, 1.0) * 30  # 0-30 points from sample size

    # Hit rate confidence
    hit_rate = _get_h2h_hit_rate(h2h_result, market_key)
    hit_conf = hit_rate * 70  # 0-70 points from hit rate

    total = sample_conf + hit_conf
    return min(total, 100.0)


# ──────────────────────────────────────────────────────────────────────
# PREDICTION GATE VERIFICATION
# ──────────────────────────────────────────────────────────────────────

def verify_pick(home: str, away: str, market: str, odds: float,
                odds_dict: Dict[str, float]) -> Dict[str, Any]:
    """Run prediction_gate.run_all_gates to verify a pick.

    Returns the full gate result with verdict PASS/FAIL.
    """
    try:
        from prediction_gate import run_all_gates
        result = run_all_gates(
            home_team=home,
            away_team=away,
            market=market,
            odds=odds,
            confidence=None,
            o15=odds_dict.get("o15"),
            o25=odds_dict.get("o25"),
            gg=odds_dict.get("gg"),
            u35=odds_dict.get("u35"),
        )
        return result
    except Exception as e:
        log.error(f"Gate verification error for {home} vs {away} {market}: {e}")
        return {"verdict": "ERROR", "error": str(e)}


# ──────────────────────────────────────────────────────────────────────
# BET PLACEMENT
# ──────────────────────────────────────────────────────────────────────

def call_bet_placer(home: str, away: str, market: str, odds: float,
                    stake: float, matchday: Optional[int] = None) -> Dict[str, Any]:
    """Call browser_bet_placer.py via subprocess to place a single bet.

    Returns parsed JSON result from the placer.
    """
    # Build input JSON matching browser_bet_placer.py's expected format
    fixture_data = {
        "home": home,
        "away": away,
        "market": market,
        "odds": odds,
        "stake": stake,
    }
    if matchday is not None:
        fixture_data["matchday"] = matchday

    input_json = json.dumps(fixture_data)

    cmd = [
        sys.executable or "python3",
        str(BET_PLACER),
        "bet",
        input_json,
    ]

    try:
        log.info(f"Placing bet via browser: {home} vs {away} -> {market} @{odds} (₦{stake}) MD{matchday}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=PLACER_TIMEOUT,
        )

        if result.returncode != 0:
            log.warning(f"Bet placer exited code {result.returncode}: {result.stderr[:200]}")
            # Try to parse any partial JSON in stdout
            if result.stdout.strip():
                try:
                    return json.loads(result.stdout.strip())
                except json.JSONDecodeError:
                    pass
            return {"success": False, "error": f"Exit code {result.returncode}: {result.stderr[:200]}"}

        # Parse JSON output
        if result.stdout.strip():
            try:
                return json.loads(result.stdout.strip())
            except json.JSONDecodeError:
                log.warning(f"Non-JSON output from bet placer: {result.stdout[:200]}")
                return {"success": False, "error": f"Non-JSON response: {result.stdout[:200]}"}

        return {"success": False, "error": "Empty response from bet placer"}

    except subprocess.TimeoutExpired:
        log.error(f"Bet placer timed out after {PLACER_TIMEOUT}s")
        return {"success": False, "error": f"Timeout after {PLACER_TIMEOUT}s"}
    except Exception as e:
        log.error(f"Bet placer error: {e}")
        return {"success": False, "error": str(e)}


# ──────────────────────────────────────────────────────────────────────
# LEAGUE TABLE UPDATE
# ──────────────────────────────────────────────────────────────────────

def update_league_table(season_id: str) -> Optional[List[Dict]]:
    """Call season_tracker.TeamTracker.build_league_table to get updated standings.

    Returns the sorted league table.
    """
    try:
        from season_tracker import TeamTracker
        tracker = TeamTracker()
        table = tracker.build_league_table(season_id)
        tracker.close()
        log.info(f"League table updated: {len(table)} teams for season {season_id}")
        return table
    except Exception as e:
        log.error(f"Failed to build league table: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────
# RESULT DETECTION
# ──────────────────────────────────────────────────────────────────────

def detect_results(state: dict, match_days: List[Dict]) -> List[Dict]:
    """Find events that have transitioned to finished (status=3).

    Returns list of newly finished events.
    """
    newly_finished = []
    seen_ids = set(state.get("seen_finished_event_ids", []))

    for md in match_days:
        for event in md.get("events", []):
            event_id = event.get("eventId") or event.get("id")
            status = event.get("status")

            if not event_id:
                continue

            if status == 3 and event_id not in seen_ids:
                newly_finished.append(event)
                seen_ids.add(event_id)

    state["seen_finished_event_ids"] = list(seen_ids)
    return newly_finished


def settle_bet(event_id: str, event_data: dict, state: dict, bankroll: dict, ledger: list):
    """Settle a bet when its event finishes.

    Updates bankroll and ledger based on outcome.
    """
    placed = state.get("placed_bet_events", {}).get(event_id)
    if not placed:
        return  # Not a bet we placed (or not tracked)

    market = placed.get("market", "")
    odds = placed.get("odds", 0)
    stake = placed.get("stake", FLAT_STAKE)

    # Extract match result from event or DB
    home_goals = event_data.get("homeScore") or event_data.get("homeGoals")
    away_goals = event_data.get("awayScore") or event_data.get("awayGoals")

    if home_goals is None or away_goals is None:
        # Try DB lookup
        try:
            import sqlite3
            conn = sqlite3.connect(str(BASE_DIR / "databases" / "vfl_results.db"))
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT home_goals, away_goals, total_goals FROM results WHERE event_id = ?",
                (event_id,)
            )
            row = cur.fetchone()
            conn.close()
            if row:
                home_goals = row["home_goals"]
                away_goals = row["away_goals"]
        except Exception as e:
            log.warning(f"Cannot look up result for {event_id}: {e}")

    if home_goals is None or away_goals is None:
        log.warning(f"Cannot settle {event_id}: no result data")
        return

    total_goals = home_goals + away_goals

    # Determine if bet won
    won = False
    is_push = False
    if market == "Over 1.5 Goals" or market == "O1.5":
        won = total_goals > 1.5
    elif market == "Over 2.5 Goals" or market == "O2.5":
        won = total_goals > 2.5
    elif market == "Under 2.5 Goals" or market == "U2.5":
        won = total_goals < 2.5
    elif market == "Under 3.5 Goals" or market == "U3.5":
        won = total_goals < 3.5
    elif market == "Goal-Goal (BTTS Yes)" or market == "GG":
        won = home_goals > 0 and away_goals > 0
    elif market == "No Goal (BTTS No)" or market == "NG":
        won = home_goals == 0 or away_goals == 0
    elif market in ("Draw No Bet (Home)", "Draw No Bet", "DNB"):
        if home_goals > away_goals:
            won = True
        elif home_goals == away_goals:
            is_push = True

    # Calculate P&L
    status = "won" if won else "push" if is_push else "lost"
    profit = 0.0

    if status == "won":
        profit = round(stake * (odds - 1), 2)
        bankroll["active_base"] = round(bankroll.get("active_base", 0) + profit, 2)
        bankroll["wins_in_cycle"] = bankroll.get("wins_in_cycle", 0) + 1
        bankroll["net_profit"] = round(bankroll.get("net_profit", 0) + profit, 2)
        log.info(f"✅ BET WON: {event_id} -> ₦{profit} profit (odds={odds})")
    elif status == "push":
        profit = 0.0
        bankroll["pushes_in_cycle"] = bankroll.get("pushes_in_cycle", 0) + 1
        log.info(f"🤝 BET PUSH: {event_id} -> stake returned (odds={odds})")
    else:
        loss = stake
        profit = -loss
        bankroll["active_base"] = round(bankroll.get("active_base", 0) - loss, 2)
        bankroll["net_profit"] = round(bankroll.get("net_profit", 0) - loss, 2)
        log.info(f"❌ BET LOST: {event_id} -> ₦{loss} loss")

    # Record in ledger
    entry = {
        "event_id": event_id,
        "home": event_data.get("homeTeam", ""),
        "away": event_data.get("awayTeam", ""),
        "market": market,
        "odds": odds,
        "stake": stake,
        "won": won,
        "status": status,
        "profit": profit,
        "score": f"{home_goals}-{away_goals}",
        "settled_at": datetime.now(timezone.utc).isoformat(),
    }

    ledger.append(entry)

    # Remove from placed_bet_events
    placed_events = state.get("placed_bet_events", {})
    if event_id in placed_events:
        del placed_events[event_id]

    save_bankroll(bankroll)
    save_ledger(ledger)
    save_state(state)


def detect_and_process_results(state: dict, match_days: List[Dict], bankroll: dict, ledger: list):
    """Detect newly finished events and process settlements + recalculations."""
    newly_finished = detect_results(state, match_days)

    if not newly_finished:
        return

    log.info(f"Detected {len(newly_finished)} newly finished event(s)")

    for event in newly_finished:
        event_id = event.get("eventId") or event.get("id")
        log.info(f"Event finished: {event_id} - {event.get('homeTeam')} vs {event.get('awayTeam')}")

        # Settle any bets on this event
        settle_bet(event_id, event, state, bankroll, ledger)

    # After processing results, update league table
    season_id = state.get("pending_season_id")
    if season_id and newly_finished:
        log.info(f"Updating league table for season {season_id}...")
        table = update_league_table(season_id)
        if table:
            # Log top 5
            for i, t in enumerate(table[:5], 1):
                log.info(f"  {i}. {t['team']}: {t['points']}pts ({t['played']}P {t['wins']}W {t['draws']}D {t['losses']}L)")
            # Persist table snapshot
            table_file = BASE_DIR / "signals" / "rapid_league_table.json"
            with open(table_file, "w") as f:
                json.dump(table, f, indent=2, default=str)
            log.info(f"League table saved to {table_file}")
        save_state(state)


# ──────────────────────────────────────────────────────────────────────
# TEAM NAME NORMALIZATION
# ──────────────────────────────────────────────────────────────────────

# Map from MSport API names to prediction_gate expected names
TEAM_NAME_MAP = {
    "Manchester Red": "Manchester Red",
    "Manchester Blue": "Manchester Blue",
    "London Guns": "London Guns",
    "Chelsea": "Chelsea",
    "Liverpool": "Liverpool",
    "Aston Villa": "Aston Villa",
    "Tottenham": "Tottenham",
    "Everton": "Everton",
    "Wolverhampton": "Wolverhampton",
    "Newcastle": "Newcastle",
    "Leeds": "Leeds",
    "Fulham": "Fulham",
    "West Ham": "West Ham",
    "Bournemouth": "Bournemouth",
    "Brighton": "Brighton",
    "Crystal Palace": "Crystal Palace",
}

# Reverse aliases (case-insensitive)
TEAM_ALIASES = {}
for k, v in TEAM_NAME_MAP.items():
    TEAM_ALIASES[k.lower()] = v
    # Strip "FC", "City", "United" variants might appear
    TEAM_ALIASES[k.lower().replace(" ", "")] = v

# Also add known variants
TEAM_ALIASES.update({
    "arsenal": "London Guns",
    "man city": "Manchester Blue",
    "manchester city": "Manchester Blue",
    "man united": "Manchester Red",
    "manchester united": "Manchester Red",
    "spurs": "Tottenham",
    "wolves": "Wolverhampton",
    "toon": "Newcastle",
    "magpies": "Newcastle",
    "hammers": "West Ham",
    "villans": "Aston Villa",
    "reds": "Liverpool",
    "blues": "Chelsea",
    "eagles": "Crystal Palace",
    "seagulls": "Brighton",
    "cherries": "Bournemouth",
    "whites": "Leeds",
    "cottagers": "Fulham",
    "toffees": "Everton",
    "gunners": "London Guns",
})


def normalize_team(name: str) -> Optional[str]:
    """Normalize a team name to canonical form. Returns None if unknown."""
    if not name:
        return None
    clean = name.strip()
    # Direct match
    if clean in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[clean]
    # Case-insensitive lookup
    low = clean.lower()
    if low in TEAM_ALIASES:
        return TEAM_ALIASES[low]
    # Partial match
    for alias, canonical in TEAM_ALIASES.items():
        if low in alias or alias in low:
            return canonical
    # Try prediction_gate's validate_team as fallback
    try:
        from prediction_gate import validate_team
        validated = validate_team(clean)
        if validated:
            return validated
    except Exception:
        pass
    return clean  # Return as-is as last resort


# ──────────────────────────────────────────────────────────────────────
# DISCORD SUMMARY OUTPUT
# ──────────────────────────────────────────────────────────────────────

def print_discord_summary(placed_ids: list, placed_events: dict,
                         matchday_statuses: dict, season_id: str) -> None:
    """Print a clean Discord-formatted summary of new activity to stdout.

    Only called when there are new events or new bets this cycle.
    Output goes to stdout → captured by cron → delivered to Discord.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md_active = sum(1 for s in matchday_statuses.values() if s in ("upcoming", "live"))
    md_settled = sum(1 for s in matchday_statuses.values() if s == "settled")
    bets_placed = len(placed_ids)

    lines = []
    lines.append(f"👑 **VFLM Rapid Daemon** — {now} 👑")
    if season_id:
        sid_short = season_id.replace("vf:season:", "S")
        lines.append(f"📌 Season **{sid_short}** | {md_active} active MDs | {md_settled} settled")

    if bets_placed > 0:
        lines.append("")
        lines.append(f"**🎯 {bets_placed} Bet(s) Tracked**")
        for eid, bet in sorted(placed_events.items()):
            h = bet.get("home", "?")
            a = bet.get("away", "?")
            m = bet.get("market_key", "?")
            o = bet.get("odds", "?")
            s = bet.get("stake", "?")
            md = bet.get("matchday", "?")
            lines.append(f"• **MD{md}** {h} vs {a} → {m} @{o} (₦{s})")

    lines.append("")
    lines.append(f"_⏱ Next poll in 60s | Position-adjusted | Dry-run_")
    lines.append("")

    print("\n".join(lines))


def print_settlement_summary(ledger: list, new_settlements: list = None) -> None:
    """Print a clean Discord-formatted summary of bet settlements to stdout.

    If new_settlements is provided, only those recent settlements are printed.
    Otherwise, the last 10 entries from the ledger are displayed.
    Output goes to stdout → captured by cron → delivered to Discord settlements channel.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    entries = new_settlements if new_settlements else ledger[-20:] if ledger else []

    if not entries:
        print(f"🧾 **VFLM Settlements** — {now}")
        print("_No settlement activity recorded yet._")
        print("")
        return

    def _is_won(e: dict) -> bool:
        if e.get("won") is True:
            return True
        if e.get("status") == "won":
            return True
        return False

    def _is_push(e: dict) -> bool:
        if e.get("status") == "push":
            return True
        return False

    def _is_lost(e: dict) -> bool:
        if e.get("status") == "push":
            return False
        if e.get("won") is False:
            return True
        if e.get("status") == "lost":
            return True
        return False

    def _get_teams(e: dict) -> tuple:
        h = e.get("home") or (e.get("match", "").split(" vs ")[0] if " vs " in e.get("match", "") else "?")
        a = e.get("away") or (e.get("match", "").split(" vs ")[1] if " vs " in e.get("match", "") else "?")
        return h, a

    def _get_score(e: dict) -> str:
        sc = e.get("score", "")
        if sc and sc != "?-?":
            return sc
        hs = e.get("home_score")
        a_s = e.get("away_score")
        if hs is not None and a_s is not None:
            return f"{hs}-{a_s}"
        result = e.get("result", "")
        if result and result != "?-?":
            return result.replace(":", "-")
        return "?-?"

    def _get_pnl(e: dict) -> float:
        pnl = e.get("profit", 0)
        if isinstance(pnl, (int, float)):
            return float(pnl)
        return 0.0

    lines = []
    lines.append(f"🧾 **VFLM Bet Settlements** — {now} 🧾")
    lines.append("")

    # Separate into won/lost/push
    settled = [e for e in entries if e.get("settled", False) or e.get("won") is not None or e.get("status") in ("won", "lost", "push")]
    pending = [e for e in entries if not e.get("settled", True) and e.get("status") not in ("won", "lost", "push") and e.get("won") is None]

    wins = [e for e in settled if _is_won(e)]
    pushes = [e for e in settled if _is_push(e)]
    losses = [e for e in settled if _is_lost(e)]

    if wins:
        for e in wins[-10:]:  # max 10
            h, a = _get_teams(e)
            m = e.get("market", "?")
            sc = _get_score(e)
            pnl = _get_pnl(e)
            lines.append(f"✅ **WON** — {h} vs {a}")
            lines.append(f"   Market: {m} | Score: {sc} | P&L: **+₦{pnl:+.2f}**")
    if pushes:
        for e in pushes[-10:]:
            h, a = _get_teams(e)
            m = e.get("market", "?")
            sc = _get_score(e)
            lines.append(f"🤝 **PUSH** — {h} vs {a}")
            lines.append(f"   Market: {m} | Score: {sc} | P&L: **₦0.00** (stake returned)")
    if losses:
        for e in losses[-10:]:
            h, a = _get_teams(e)
            m = e.get("market", "?")
            sc = _get_score(e)
            pnl = _get_pnl(e)
            lines.append(f"❌ **LOST** — {h} vs {a}")
            lines.append(f"   Market: {m} | Score: {sc} | P&L: {pnl:+.2f}")

    # Summary
    if settled:
        total_profit = sum(_get_pnl(e) for e in wins) + sum(_get_pnl(e) for e in losses) + sum(_get_pnl(e) for e in pushes)
        lines.append("")
        lines.append(f"**Summary:** {len(wins)}W / {len(losses)}L / {len(pushes)}P | Net: **₦{total_profit:+.2f}**")

    if pending:
        lines.append("")
        lines.append(f"**⏳ Pending:** {len(pending)} bet(s) awaiting settlement")

    lines.append("")

    print("\n".join(lines))


# ──────────────────────────────────────────────────────────────────────
# POLL & PROCESS
# ──────────────────────────────────────────────────────────────────────

def poll_and_process(state: dict, bankroll: dict, ledger: list,
                    dry_run: bool = False, recovery_mode: bool = False):
    """Single poll cycle: fetch events, detect new + results, analyze, bet."""
    cycle = state.get("cycle_count", 0) + 1
    state["cycle_count"] = cycle
    log.info(f"─── Cycle #{cycle} ───────────────────────────────────────")

    # ── State pruning (always at start of cycle) ──
    prune_old_events(state)

    # ── Recovery-mode check ──
    balance = bankroll.get("active_base", 0)
    if balance < RECOVERY_THRESHOLD:
        recovery_mode = True
        log.warning(
            f"[RECOVERY] Balance ₦{balance:.2f} < ₦{RECOVERY_THRESHOLD:.0f} "
            f"stop-loss — dry-run only"
        )
    elif recovery_mode:
        # Balance recovered — clear recovery mode
        recovery_mode = False
        log.info(
            f"[RECOVERY] Balance ₦{balance:.2f} >= ₦{RECOVERY_THRESHOLD:.0f} "
            f"— recovery mode cleared"
        )

    # 1. Fetch event list from MSport
    match_days = fetch_events()
    if not match_days:
        log.warning("No matchdays returned from MSport API. Skipping cycle.")
        save_state(state)
        return

    log.info(f"Fetched {len(match_days)} matchdays from MSport")

    # Track known event IDs
    known_ids = set(state.get("known_event_ids", []))
    placed_ids = set(state.get("placed_bet_ids", []))
    placed_events = state.get("placed_bet_events", {})

    # 2. Detect & process results FIRST (before new events)
    detect_and_process_results(state, match_days, bankroll, ledger)

    # 3. Detect new events (not in known list)
    new_events = []
    all_current_ids = set()
    active_season_id = state.get("pending_season_id")
    matchday_statuses = state.get("matchday_status", {})

    for md in match_days:
        md_num = md.get("matchDay") or md.get("matchday")
        # Try to detect season info
        season_id = md.get("seasonId") or md.get("season_id")
        if season_id and not active_season_id:
            active_season_id = season_id
            state["pending_season_id"] = season_id
            log.info(f"Active season detected: {season_id}")
        # Check for season change (also: detected_new_season clears tracking)
        if season_id:
            detect_new_season(state, season_id)

        for event in md.get("events", []):
            event_id = event.get("eventId") or event.get("id")
            if not event_id:
                continue
            all_current_ids.add(event_id)

            if event_id not in known_ids:
                new_events.append((md_num, event))

    # Update known IDs
    state["known_event_ids"] = list(all_current_ids | known_ids)

    log.info(f"Total known events: {len(known_ids)} → {len(all_current_ids | known_ids)}")
    log.info(f"New events this cycle: {len(new_events)}")
    log.info(f"Placed bets tracked: {len(placed_ids)}")

    # 4. Process new events
    if new_events:
        # Build league table for positional analysis
        league_table = None
        if active_season_id:
            try:
                league_table = update_league_table(active_season_id)
                if league_table:
                    log.info(f"League table loaded for positional analysis: {len(league_table)} teams")
                else:
                    log.debug("No league table available for positional analysis")
            except Exception as e:
                log.debug(f"Could not build league table: {e}")

        # Group new events by matchday
        new_by_md: Dict[int, List[Tuple[int, dict]]] = {}
        for md_num, event in new_events:
            md_key = md_num if md_num is not None else 0
            if md_key not in new_by_md:
                new_by_md[md_key] = []
            new_by_md[md_key].append((md_num, event))

        log.info(f"New events across {len(new_by_md)} matchdays")

        # Track which matchdays we've already placed a bet for this cycle
        md_bet_placed_this_cycle: Set[int] = set()

        for md_key in sorted(new_by_md.keys()):
            events_list = new_by_md[md_key]
            log.info(f"  Analyzing MD{md_key}: {len(events_list)} new event(s)")

            # Analyze each new event
            analyzed_fixtures = []
            for md_num, event in events_list:
                home_raw = event.get("homeTeam") or event.get("homeName") or "?"
                away_raw = event.get("awayTeam") or event.get("awayName") or "?"
                event_id = event.get("eventId") or event.get("id")

                home = normalize_team(home_raw) or home_raw
                away = normalize_team(away_raw) or away_raw

                odds_dict = extract_odds(event)
                log.info(f"    {home} vs {away} [{event_id}] odds: O1.5={odds_dict['o15']}, O2.5={odds_dict['o25']}, U3.5={odds_dict['u35']}, GG={odds_dict['gg']}")

                # Run full analysis
                analysis = analyze_fixture(home, away, odds_dict,
                                           league_table=league_table,
                                           season_id=active_season_id)
                best = analysis.get("best_pick")

                if best:
                    pos_str = ""
                    if analysis.get("position_adjustment"):
                        pa = analysis["position_adjustment"]
                        pos_str = f" [POS: {pa.get('home_zone','?')} #{pa.get('home_position','?')} vs {pa.get('away_zone','?')} #{pa.get('away_position','?')}, conf={pa.get('position_confidence',0):.0f}]"
                    log.info(f"      Best pick: {best['market']} @{best['odds']} (conf={best['confidence']:.1f}%, H2H={best['h2h_status']}){pos_str}")
                else:
                    log.info(f"      No qualifying pick (all markets failed H2H)")

                analyzed_fixtures.append({
                    "event_id": event_id,
                    "home": home,
                    "away": away,
                    "md": md_num,
                    "analysis": analysis,
                    "best": best,
                })

            # ── Auto-bet: ONE bet per matchday ──
            # Skip if we already placed a bet for this MD in this cycle
            if md_key in md_bet_placed_this_cycle:
                log.info(f"    Already placed bet for MD{md_key} this cycle")
                continue

            # Find the fixture with the highest-confidence best pick
            qualified = []
            for fx in analyzed_fixtures:
                best = fx.get("best")
                if not best or not best.get("odds") or best["odds"] <= 1.0:
                    continue
                if best.get("h2h_status") != "PASS":
                    continue
                if best.get("confidence", 0) < 50:
                    continue

                # Run full prediction gate verification
                is_high_conf = False
                if best.get("market") == "DNB":
                    if best.get("confidence", 0) >= 65.0:
                        is_high_conf = True
                else:
                    if best.get("hit_rate", 0) >= 0.65:
                        is_high_conf = True

                if is_high_conf:
                    # High-confidence pick (H2H >= 65% for DNB, or Hit Rate >= 65% for others): relaxed gate
                    # Only check H2H + odds reasonableness; cluster/regime are advisory
                    from prediction_gate import gate_h2h, gate_odds_reasonableness
                    h2h_check = gate_h2h(fx["home"], fx["away"], best["market"], best["odds"])
                    odds_check = gate_odds_reasonableness(best["market"], best["odds"])
                    h2h_pass = h2h_check.get("status") == "PASS"
                    odds_pass = odds_check.get("status") == "PASS"
                    if h2h_pass and odds_pass:
                        fx["gate_result"] = {"verdict": "PASS", "h2h": h2h_check, "odds": odds_check}
                        qualified.append(fx)
                        log.info(f"      ✅ HIGH-CONF: {fx['home']} vs {fx['away']} -> {best['market']} @{best['odds']} (H2H {best['hit_rate']*100:.0f}%)")
                    else:
                        fails = []
                        if not h2h_pass: fails.append("h2h")
                        if not odds_pass: fails.append("odds")
                        log.info(f"      ❌ FAIL: {fx['home']} vs {fx['away']} -> {best['market']} (reasons: {fails})")

                else:
                    # Low-confidence pick: run full gate
                    gate_result = verify_pick(
                        fx["home"], fx["away"],
                        best["market"], best["odds"],
                        fx["analysis"]["odds"],
                    )
                    if gate_result.get("verdict") == "PASS":
                        fx["gate_result"] = gate_result
                        qualified.append(fx)
                        log.info(f"      ✅ Gate PASS: {fx['home']} vs {fx['away']} -> {best['market']} @{best['odds']}")
                    else:
                        log.info(f"      ❌ Gate FAIL: {fx['home']} vs {fx['away']} -> {best['market']} (reasons: {gate_result.get('failing_gates', '?')})")

            if qualified:
                # Sort by confidence descending, with position confidence as tiebreaker
                qualified.sort(key=lambda f: (
                    f["best"]["confidence"],
                    # Position confidence boost (max +10)
                    ((f.get("analysis") or {}).get("position_adjustment") or {}).get("position_confidence", 0) * 0.1,
                ), reverse=True)
                best_fixture = qualified[0]
                best_pick = best_fixture["best"]

                event_id = best_fixture["event_id"]
                home = best_fixture["home"]
                away = best_fixture["away"]
                market = best_pick["market"]
                odds = best_pick["odds"]
                md_num = best_fixture["md"]

                # Display name for bet placer
                mkt_display = best_pick["display"]

                # Check if we already placed a bet on this event
                if event_id in placed_ids:
                    log.info(f"    Already placed bet on {event_id}, skipping")
                    md_bet_placed_this_cycle.add(md_key)
                    continue

                # Check bankroll
                bankroll_base = bankroll.get("active_base", 0)
                if bankroll_base < FLAT_STAKE:
                    log.warning(f"Insufficient bankroll: ₦{bankroll_base} < ₦{FLAT_STAKE}")
                    continue

                # Place bet (real or dry-run)
                if dry_run:
                    log.info(f"🔍 DRY RUN: Would bet {home} vs {away} -> {mkt_display} @{odds} (₦{FLAT_STAKE}) MD{md_num}")
                    bet_result = {"success": True, "dry_run": True}
                elif recovery_mode:
                    log.info(f"🔄 [RECOVERY] Would bet {home} vs {away} -> {mkt_display} @{odds} (₦{FLAT_STAKE}) MD{md_num} — dry-run only")
                    bet_result = {"success": True, "dry_run": True, "recovery": True}
                else:
                    bet_result = call_bet_placer(
                        home=home,
                        away=away,
                        market=mkt_display,
                        odds=odds,
                        stake=FLAT_STAKE,
                        matchday=md_num,
                    )

                if bet_result.get("success"):
                    # Deduct stake from bankroll
                    bankroll["active_base"] = round(bankroll.get("active_base", 0) - FLAT_STAKE, 2)

                    # Track placement
                    placed_ids.add(event_id)
                    placed_events[event_id] = {
                        "market": mkt_display,
                        "market_key": market,
                        "odds": odds,
                        "stake": FLAT_STAKE,
                        "matchday": md_num,
                        "season_id": active_season_id,
                        "placed_at": datetime.now(timezone.utc).isoformat(),
                        "home": home,
                        "away": away,
                    }

                    state["placed_bet_ids"] = list(placed_ids)
                    state["placed_bet_events"] = placed_events
                    md_bet_placed_this_cycle.add(md_key)

                    save_bankroll(bankroll)
                    save_state(state)

                    log.info(f"✅ BET PLACED: {home} vs {away} -> {mkt_display} @{odds} (₦{FLAT_STAKE}) MD{md_num}")
                else:
                    log.warning(f"❌ BET FAILED: {bet_result.get('error', 'unknown error')}")
            else:
                log.info(f"    No qualified picks for MD{md_key}")

    # 5. Update matchday statuses
    for md in match_days:
        md_num = md.get("matchDay") or md.get("matchday")
        if md_num is None:
            continue
        md_key = str(md_num)
        events = md.get("events", [])
        statuses = set()
        for e in events:
            s = e.get("status")
            if s == 1:
                statuses.add("upcoming")
            elif s == 2:
                statuses.add("live")
            elif s == 3:
                statuses.add("settled")

        if "live" in statuses:
            matchday_statuses[md_key] = "live"
        elif "upcoming" in statuses and "settled" not in statuses:
            matchday_statuses[md_key] = "upcoming"
        elif "settled" in statuses and "upcoming" not in statuses and "live" not in statuses:
            matchday_statuses[md_key] = "settled"

    state["matchday_status"] = matchday_statuses

    # 6. Save state
    save_state(state)
    save_bankroll(bankroll)

    # 7. Output Discord summary if there was activity
    if new_events:
        print_discord_summary(placed_ids, placed_events,
                             matchday_statuses, active_season_id)

    log.info(f"─── Cycle #{cycle} complete ─────────────────────────────")
    return True


# ──────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────

def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="VFLM Real-Time Betting Daemon"
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run a single cycle and exit (for verification)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Analyze without placing real bets"
    )
    parser.add_argument(
        "--interval", type=int, default=POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {POLL_INTERVAL})"
    )
    parser.add_argument(
        "--report-settlements", action="store_true",
        help="Only print settlement results from the bet ledger to stdout"
    )
    parser.add_argument(
        "--clear-pause", action="store_true",
        help="Delete PAUSED.json if it exists (unblock daemon)"
    )
    parser.add_argument(
        "--recover", action="store_true",
        help="Recovery dry-run: analyze + output what would be bet, no browser/betting"
    )
    args = parser.parse_args()

    # ── Clear pause file if requested ──
    if args.clear_pause:
        if PAUSED_FILE.exists():
            PAUSED_FILE.unlink()
            log.info(f"Cleared pause file: {PAUSED_FILE}")
            print(f"✅ Cleared {PAUSED_FILE}")
        else:
            log.info("No PAUSED.json to clear")
            print("ℹ️  No PAUSED.json found — nothing to clear")
        if args.clear_pause and not (args.once or args.dry_run or args.report_settlements or args.recover):
            return

    # ── Recovery dry-run mode ──
    if args.recover:
        log.info("Running in RECOVERY dry-run mode (no bets placed)...")
        state = load_state()
        bankroll = load_bankroll()
        ledger = load_ledger()

        log.info(f"Bankroll: active_base=₦{bankroll.get('active_base', 0):.2f}, "
                 f"reserve=₦{bankroll.get('reserve', 0):.2f}, "
                 f"net_profit=₦{bankroll.get('net_profit', 0):.2f}")

        try:
            poll_and_process(state, bankroll, ledger,
                             dry_run=True, recovery_mode=True)
        except Exception as e:
            log.error(f"Recovery cycle failed: {e}")
            log.debug(traceback.format_exc())

        # Output summary of what would have happened
        print("\n📊 **Recovery Dry-Run Summary**")
        print(f"   Bankroll: ₦{bankroll.get('active_base', 0):.2f}")
        print(f"   Reserve: ₦{bankroll.get('reserve', 0):.2f}")
        print(f"   Net P&L: ₦{bankroll.get('net_profit', 0):.2f}")
        placed = len(state.get("placed_bet_ids", []))
        known = len(state.get("known_event_ids", []))
        print(f"   Events analyzed: {known}")
        print(f"   Bets that would have been placed: {placed}")
        print("   (No browser/betting code was touched)")
        print("")
        log.info("Recovery dry-run complete.")
        return

    # ── Settlements-only mode ──────────────────────────────────────
    if args.report_settlements:
        log.info("Running in settlements-report mode...")
        # Run a single cycle to pick up any new settlements
        state = load_state()
        bankroll = load_bankroll()
        ledger = load_ledger()

        # Run the poll cycle (which calls detect_and_process_results)
        try:
            poll_and_process(state, bankroll, ledger, dry_run=args.dry_run)
        except Exception as e:
            log.error(f"Cycle failed: {e}")
            log.debug(traceback.format_exc())

        # Re-load ledger to get any new settlements
        ledger = load_ledger()

        # Print existing unsettled bets (pending) and recent settlements
        placed_events = state.get("placed_bet_events", {})
        if placed_events:
            print(f"⏳ **Pending Bets** — {len(placed_events)} bet(s) awaiting settlement")
            print("")
            for eid, bet in sorted(placed_events.items()):
                h = bet.get("home", "?")
                a = bet.get("away", "?")
                m = bet.get("market_key", "?")
                o = bet.get("odds", "?")
                s = bet.get("stake", "?")
                print(f"• {h} vs {a} → {m} @{o} (₦{s}) [{eid}]")
            print("")

        # Print settlement summary from last 20 ledger entries
        recent = ledger[-20:] if ledger else []
        print_settlement_summary(ledger, recent)

        log.info("Settlements report complete.")
        return

    log.info("=" * 60)
    log.info("VFLM Rapid Betting Daemon v1.0")
    log.info(f"State file: {STATE_FILE}")
    log.info(f"Bankroll file: {BANKROLL_FILE}")
    log.info(f"Log file: {LOG_FILE}")
    log.info(f"Poll interval: {args.interval}s")
    log.info(f"Flat stake: ₦{FLAT_STAKE}")
    log.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    log.info(f"Continuous: {'NO (--once)' if args.once else 'YES'}")
    log.info("=" * 60)

    # Load state
    state = load_state()
    bankroll = load_bankroll()
    ledger = load_ledger()

    log.info(f"Bankroll: active_base=₦{bankroll.get('active_base', 0):.2f}, "
             f"reserve=₦{bankroll.get('reserve', 0):.2f}, "
             f"net_profit=₦{bankroll.get('net_profit', 0):.2f}")
    log.info(f"Known event IDs: {len(state.get('known_event_ids', []))}")
    log.info(f"Placed bet IDs: {len(state.get('placed_bet_ids', []))}")
    log.info(f"Matchday statuses: {state.get('matchday_status', {})}")

    if args.once:
        # Single cycle
        log.info("Running single cycle...")
        try:
            poll_and_process(state, bankroll, ledger, dry_run=args.dry_run)
        except Exception as e:
            log.error(f"Cycle failed: {e}")
            log.debug(traceback.format_exc())
        log.info("Single cycle complete.")
        return

    # Continuous loop
    log.info("Starting continuous polling loop...")
    while True:
        cycle_start = time.time()
        try:
            poll_and_process(state, bankroll, ledger, dry_run=args.dry_run)
        except KeyboardInterrupt:
            log.info("Daemon stopped by user.")
            break
        except Exception as e:
            log.error(f"Cycle failed: {e}")
            log.debug(traceback.format_exc())

        elapsed = time.time() - cycle_start
        sleep_time = max(1, args.interval - elapsed)
        log.debug(f"Cycle took {elapsed:.1f}s. Sleeping {sleep_time:.0f}s...")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
