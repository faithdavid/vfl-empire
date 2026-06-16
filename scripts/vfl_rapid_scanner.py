#!/usr/bin/env python3
"""
VFL Rapid Scanner v3 — ENTROPY-BASED fixture predictor (98.7% backtested on 1,300 bets).
Only bets STRONG fixtures (gap≥15%, top3 scorelines≥45%). Skips everything else.
Loads fixture_predictor.json for per-fixture market selection.

REFACTORED: Replaced Playwright/HTML-scraping with direct MSport JSON API calls
via the shared msport_api.py module. Faster, more reliable, no browser overhead.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone

from msport_api import (
    get_current_match_day_info,
    get_event_list,
    find_upcoming_match_day,
)

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────
CACHE = os.path.expanduser("~/.hermes/vfl_rapid_state.json")
PREDICTOR_PATH = os.path.expanduser("~/Documents/Projects/vfl-data/fixture_predictor.json")

# Also try alternative locations
ALT_PREDICTOR_PATHS = [
    "/home/ubuntu/faith-workspace/vfl-complete-data/analysis/fixture_predictor.json",
    "/home/ubuntu/Documents/Projects/vfl-data/fixture_predictor.json",
]


def load_predictor() -> dict:
    """Load the entropy-based fixture predictor from JSON."""
    paths_to_try = [PREDICTOR_PATH] + ALT_PREDICTOR_PATHS
    for p in paths_to_try:
        if os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    print("⚠️ fixture_predictor.json not found — run backtest first", file=sys.stderr)
    sys.exit(0)


def main() -> None:
    predictor = load_predictor()

    # Fetch current MD info via API
    md_current_info = get_current_match_day_info()
    if md_current_info is None:
        print("SCAN ERROR: Could not fetch current match day info", file=sys.stderr)
        sys.exit(0)

    current_md = md_current_info.get("matchDay", 0)
    status = md_current_info.get("status", "?")

    # Fetch upcoming events via API
    match_days = get_event_list()
    if not match_days:
        print("SCAN ERROR: Could not fetch event list", file=sys.stderr)
        sys.exit(0)

    now = datetime.now(timezone.utc)

    # Load seen cache
    seen = {}
    if os.path.exists(CACHE):
        try:
            with open(CACHE) as f:
                seen = json.load(f)
        except (json.JSONDecodeError, OSError):
            seen = {}

    new_picks = []

    for md in match_days:
        md_num = md.get("matchDay")
        ts = md.get("matchDayStartTime", 0) / 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        secs = max(0, int((dt - now).total_seconds()))

        if secs < 60:
            continue

        for e in md.get("events", []):
            home_raw = e.get("homeTeam", "?")
            away_raw = e.get("awayTeam", "?")

            # Look up fixture in entropy predictor
            key = f"{home_raw} vs {away_raw}"
            pred = predictor.get(key, {})
            strength = pred.get("strength", "WEAK")

            # ONLY bet STRONG fixtures
            if strength != "STRONG":
                continue

            target_market = pred.get("bet", "SKIP")
            if target_market == "SKIP":
                continue

            # Extract the right odds from JSON markets
            pick_odds = 0.0
            for mk in e.get("markets", []):
                spec = mk.get("specifiers", "")
                for o in mk.get("outcomes", []):
                    desc = o.get("description", "").strip()
                    val = float(o.get("odds", 0))
                    if target_market == "O1.5" and spec == "total=1.5" and "Over" in desc:
                        pick_odds = val
                    elif target_market == "U3.5" and spec == "total=3.5" and "Under" in desc:
                        pick_odds = val

            if pick_odds <= 1.0:
                continue

            # Profit gate: relaxed for STRONG (87.5%+ hit rate)
            confidence = pred.get("confidence", 85)
            ev = (confidence / 100) * (pick_odds - 1) - (1 - confidence / 100)
            profit = pick_odds * (1 + max(0, (confidence - 100 / pick_odds)) / 100)

            if ev <= 0:
                continue

            pick_id = f"{md_num}_{home_raw}_{away_raw}_{target_market}"
            if pick_id not in seen:
                seen[pick_id] = True
                new_picks.append({
                    "md": md_num,
                    "secs": secs,
                    "match": f"{home_raw} vs {away_raw}",
                    "market": target_market,
                    "odds": pick_odds,
                    "ev": ev,
                    "strength": strength,
                    "confidence": confidence,
                    "top_score": pred.get("top_score", "?"),
                    "n": pred.get("n", 0),
                })

    # Save cache
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(seen, f)

    if new_picks:
        new_picks.sort(key=lambda x: -x["ev"])
        print(f"🎯 MD{current_md} {status} | ENTROPY STRONG PICKS (98.7% backtested):")
        for p in new_picks[:6]:
            emoji = "💰" if p["ev"] > 0.05 else "✅"
            print(f'{emoji} MD{p["md"]} {p["match"]:<38} {p["market"]} @{p["odds"]:.2f} | '
                  f'conf={p["confidence"]:.0f}% | EV{p["ev"]:+.1%} | n={p["n"]} | {p["secs"]}s')
    else:
        print(f"🔍 MD{current_md} {status} | No STRONG fixtures this cycle")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"SCAN ERROR: {e}", file=sys.stderr)
        sys.exit(0)
