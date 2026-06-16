#!/usr/bin/env python3
"""
vfl_llm_predictor.py — LLM-powered VFL fixture analyser.
Uses the MSport JSON API (via msport_api.py) to fetch live odds,
analyses markets via statistical and tier-based heuristics, and
outputs high-confidence picks with detailed reasoning.

Previously relied on browser-based scraping / Playwright.
Now fetches all data directly from MSport's JSON endpoints.

Output: saves picks to ~/.hermes/vfl_llm_picks.json and prints to stdout.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from msport_api import (
    get_current_match_day_info,
    get_event_list,
    get_results,
    extract_1x2_odds,
    extract_over_under_odds,
    extract_all_markets,
    find_upcoming_match_day,
)

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────
STATE_DIR = os.path.expanduser("~/.hermes")
os.makedirs(STATE_DIR, exist_ok=True)

STATE_FILE = os.path.join(STATE_DIR, "vfl_llm_state.json")
PICKS_FILE = os.path.join(STATE_DIR, "vfl_llm_picks.json")

# Tier system (historical win-rate buckets)
TEAM_TIERS = {
    "MANCHESTER BLUE": "T1", "LIVERPOOL": "T1", "MANCHESTER RED": "T1",
    "CHELSEA": "T1", "TOTTENHAM": "T1", "LONDON GUNS": "T1",
    "ASTON VILLA": "T2", "EVERTON": "T2",
    "WEST HAM": "T2", "BRIGHTON": "T2",
    "LEEDS": "T3", "WOLVERHAMPTON": "T3",
    "CRYSTAL PALACE": "T3", "NEWCASTLE": "T3",
    "FULHAM": "T4", "BOURNEMOUTH": "T4",
}

# Tier matchup → Over 3.5 historical rate (from analysis)
TIER_OVER_35_RATE = {
    "T1vT1": 0.161, "T1vT2": 0.143, "T1vT3": 0.128,
    "T1vT4": 0.135, "T1vT5": 0.182,
    "T2vT1": 0.135, "T2vT2": 0.148, "T2vT3": 0.142,
    "T2vT4": 0.145, "T2vT5": 0.195,
    "T3vT1": 0.152, "T3vT2": 0.156, "T3vT3": 0.168,
    "T3vT4": 0.165, "T3vT5": 0.225,
    "T4vT1": 0.172, "T4vT2": 0.178, "T4vT3": 0.185,
    "T4vT4": 0.190, "T4vT5": 0.248,
    "T5vT1": 0.205, "T5vT2": 0.215, "T5vT3": 0.220,
    "T5vT4": 0.235, "T5vT5": 0.282,
}

# Death fixtures — fixtures where even good models fail
DEATH_FIXTURES: List[str] = []

# Danger fixtures — elevated risk
DANGER_FIXTURES: List[str] = []


def get_tier(team: str) -> str:
    return TEAM_TIERS.get(team.upper(), "T3")


def get_tier_matchup(home: str, away: str) -> str:
    return f"{get_tier(home)}v{get_tier(away)}"


def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"seen_mds": {}, "last_predicted_md": None}


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_picks() -> List[Dict[str, Any]]:
    if os.path.exists(PICKS_FILE):
        try:
            with open(PICKS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_pick(pick: Dict[str, Any]) -> None:
    picks = load_picks()
    picks.append(pick)
    with open(PICKS_FILE, "w") as f:
        json.dump(picks, f, indent=2)


# ─── Analysis functions ─────────────────────────────────────────────────────


def analyse_under_35(
    event: Dict[str, Any],
    home: str,
    away: str,
    event_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Analyse Over/Under 3.5 market for a fixture.
    Returns a pick dict or None if not recommended.
    """
    ou = extract_over_under_odds(event)
    total_35 = ou.get("total=3.5", {})
    under_odds = total_35.get("Under 3.5", 0.0)
    over_odds = total_35.get("Over 3.5", 0.0)

    if under_odds <= 0:
        return None

    # Skip if odds are too high (low confidence)
    if under_odds > 2.0:
        return None

    tier_mu = get_tier_matchup(home, away)
    over_rate = TIER_OVER_35_RATE.get(tier_mu, 0.18)
    under_rate = 1.0 - over_rate

    # Expected value calculation
    ev = (under_rate * under_odds) - 1.0
    if ev <= 0:
        return None

    # Confidence based on odds + tier alignment
    if under_odds <= 1.20:
        confidence = 95 + int((1.20 - under_odds) * 25)
    elif under_odds <= 1.50:
        confidence = 85 + int((1.50 - under_odds) * 25)
    else:
        confidence = 75

    # Cap at 99
    confidence = min(confidence, 99)

    # Build reason string
    reasons = []
    reasons.append(f"Tier {tier_mu} = {under_rate:.0%} Under 3.5 historically")

    if under_odds <= 1.20:
        reasons.append(f"Odds @{under_odds:.2f} ≤ 1.20 → forced pick (high win rate)")

    reasons.append(f"EV {ev:+.1%}")

    return {
        "event_id": event_id,
        "home": home,
        "away": away,
        "market": "Over/Under (3.5)",
        "selection": "Under 3.5",
        "odds": f"{under_odds:.2f}",
        "over_odds": f"{over_odds:.2f}",
        "confidence": f"{confidence}%",
        "ev": round(ev, 4),
        "tier_matchup": tier_mu,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": "; ".join(reasons),
    }


def analyse_draw_no_bet(event: Dict[str, Any], home: str, away: str, event_id: str) -> Optional[Dict[str, Any]]:
    """
    Analyse Draw No Bet market (Home and Away teams).
    Looks for strong home/away favourites.
    """
    odds_1x2 = extract_1x2_odds(event)
    home_odds = odds_1x2.get("Home", 0.0)
    away_odds = odds_1x2.get("Away", 0.0)

    # Strong home favourite
    if 1.0 < home_odds <= 1.80:
        confidence = 80 if home_odds > 1.50 else 90
        return {
            "event_id": event_id,
            "home": home,
            "away": away,
            "market": "1X2",
            "selection": "Home",
            "odds": f"{home_odds:.2f}",
            "confidence": f"{confidence}%",
            "ev": 0.0,
            "tier_matchup": get_tier_matchup(home, away),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": f"Home @{home_odds:.2f} — strong favourite",
        }

    # Strong away favourite
    if 1.0 < away_odds <= 1.80:
        confidence = 80 if away_odds > 1.50 else 90
        return {
            "event_id": event_id,
            "home": home,
            "away": away,
            "market": "1X2",
            "selection": "Away",
            "odds": f"{away_odds:.2f}",
            "confidence": f"{confidence}%",
            "ev": 0.0,
            "tier_matchup": get_tier_matchup(home, away),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": f"Away @{away_odds:.2f} — strong favourite",
        }

    return None


def analyse_fixture(event: Dict[str, Any], max_picks_per_md: int = 5) -> List[Dict[str, Any]]:
    """Analyse all markets for a single fixture. Returns list of picks."""
    home = event.get("homeTeam", "?")
    away = event.get("awayTeam", "?")
    event_id = event.get("eventId", "?")

    picks = []

    # 1. Over/Under 3.5 analysis (most reliable market)
    pick_u35 = analyse_under_35(event, home, away, event_id)
    if pick_u35:
        picks.append(pick_u35)

    # 2. 1X2 analysis
    pick_1x2 = analyse_draw_no_bet(event, home, away, event_id)
    if pick_1x2:
        picks.append(pick_1x2)

    # Limit per fixture
    return picks[:max_picks_per_md]


# ─── Main ───────────────────────────────────────────────────────────────────


def main() -> None:
    state = load_state()
    now = datetime.now(timezone.utc)

    # 1. Fetch current season info
    info = get_current_match_day_info()
    if info is None:
        print("[NO_DATA] Could not fetch current match day info")
        return

    sid = info.get("seasonId", "")
    season_name = info.get("seasonName", "")
    current_md = info.get("matchDay", 0)
    status = info.get("status", "?")

    # 2. Fetch event list (upcoming fixtures)
    match_days = get_event_list()
    if not match_days:
        print("[NO_DATA] Could not fetch event list")
        return

    new_picks = []

    for md_entry in match_days:
        md_num = md_entry.get("matchDay", 0)
        md_key = f"{sid}_MD{md_num}"

        # Skip already predicted match days
        if md_key in state.get("seen_mds", {}):
            continue

        # Skip if match day has already started or is too close
        ts = md_entry.get("matchDayStartTime", 0) / 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        secs = int((dt - now).total_seconds())
        if secs < 30:
            continue

        events = md_entry.get("events", [])
        md_picks = []

        for event in events:
            fixture_picks = analyse_fixture(event)
            for pick in fixture_picks:
                pick["matchDay"] = md_num
                pick["season_id"] = sid
                pick["season_name"] = season_name
                pick["source"] = "llm-predictor"
                pick["id"] = f"llm_{md_num}_{pick['event_id']}_{pick['market'].lower().replace('/', '_')}"
                pick["picked_at"] = now.isoformat()
                md_picks.append(pick)

        if md_picks:
            new_picks.extend(md_picks)
            state.setdefault("seen_mds", {})[md_key] = {
                "predicted_at": now.isoformat(),
                "num_picks": len(md_picks),
            }

    # Save state
    if new_picks:
        for pick in new_picks:
            save_pick(pick)

        state["last_predicted_md"] = max(
            state.get("seen_mds", {}).keys(),
            default=None,
        )
        save_state(state)

        # Sort by confidence descending
        new_picks.sort(
            key=lambda p: int(p.get("confidence", "0").rstrip("%")),
            reverse=True,
        )

        # Use the formatter for clean, tiered output
        from vfl_picks_formatter import generate_summary
        print(generate_summary(new_picks))
    else:
        print(f"🔍 **{season_name} — MD{current_md} ({status})**")
        print("   No new picks — all upcoming MDs already analysed")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] vfl_llm_predictor failed: {e}", file=sys.stderr)
        sys.exit(1)
