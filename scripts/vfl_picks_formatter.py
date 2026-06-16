#!/usr/bin/env python3
"""
vfl_picks_formatter.py — Formats VFL LLM picks into a clean, action-oriented
Telegram summary with confidence tiers for instant scanning.

Usage:
  python3 vfl_picks_formatter.py                    # reads ~/.hermes/vfl_llm_picks.json, shows latest run only
  python3 vfl_picks_formatter.py --all              # shows ALL picks (not just latest)
  python3 vfl_picks_formatter.py --file <path>      # read a specific picks file
  python3 vfl_picks_formatter.py --stdin            # read from stdin (pipe from predictor)
"""
import json
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

PICKS_FILE = os.path.expanduser("~/.hermes/vfl_llm_picks.json")

# ─── Confidence tiers (for grouping) ───────────────────────────────────────────
TIER_ELITE = (95, 100)    # 🔥 MAX CONFIDENCE — bet now
TIER_STRONG = (90, 94)    # 💎 Very strong
TIER_SOLID = (85, 89)     # ⭐ Solid
TIER_DECENT = (80, 84)    # ✅ Decent / filler

TIER_CONFIG = [
    ("🔥 ELITE", 95, 100),
    ("💎 STRONG", 90, 94),
    ("⭐ SOLID", 85, 89),
    ("✅ DECENT", 80, 84),
]


def get_tier(confidence: int) -> Tuple[str, str]:
    """Returns (emoji_badge, tier_name) for a confidence score."""
    if confidence >= 95:
        return ("🔥", "ELITE")
    elif confidence >= 90:
        return ("💎", "STRONG")
    elif confidence >= 85:
        return ("⭐", "SOLID")
    else:
        return ("✅", "DECENT")


def format_ev(ev: float) -> str:
    """Format EV nicely — only show if positive & meaningful."""
    if ev is None or ev <= 0:
        return ""
    return f"EV {ev:+.1%}"


def format_market_short(market: str, selection: str, odds: str) -> str:
    """Short market representation for one-line display."""
    if "over/under" in market.lower() or "over_under" in market.lower():
        return f"**U3.5** @{odds}"
    elif "1x2" in market.lower():
        sel_short = selection[:1]  # H, A, or D
        return f"**{sel_short}** @{odds}"
    return f"**{selection}** @{odds}"


def format_pick_line(pick: Dict[str, Any]) -> str:
    """Single-line pick representation."""
    home = pick.get("home", "?")
    away = pick.get("away", "?")
    selection = pick.get("selection", "?")
    odds = pick.get("odds", "?")
    conf_raw = pick.get("confidence", "80%")
    confidence = int(conf_raw.rstrip("%"))
    ev = pick.get("ev", 0.0)
    md = pick.get("matchDay", "?")

    market = pick.get("market", "")
    market_short = format_market_short(market, selection, odds)

    ev_str = format_ev(ev)
    ev_part = f" | {ev_str}" if ev_str else ""

    badge, _ = get_tier(confidence)

    return f"{badge} MD{md} {home} vs {away} → {market_short} ({conf_raw}){ev_part}"


def format_section_header(tier_name: str, count: int) -> str:
    if count == 0:
        return ""
    return f"\n**{tier_name}** — {count} pick{'s' if count != 1 else ''}"


def generate_summary(picks: List[Dict[str, Any]]) -> str:
    """Generate a clean, tiered summary for Telegram."""
    if not picks:
        return "🔍 No picks available."

    # Group by season
    by_season: Dict[str, List[Dict]] = defaultdict(list)
    for p in picks:
        season = p.get("season_name", "Unknown")
        by_season[season].append(p)

    lines = []

    for season_name, season_picks in sorted(by_season.items()):
        # Group by matchday within each season
        by_md: Dict[int, List[Dict]] = defaultdict(list)
        for p in season_picks:
            by_md[p.get("matchDay", 0)].append(p)

        for md in sorted(by_md.keys()):
            md_picks = by_md[md]

            # Sort by confidence desc, then EV desc
            md_picks.sort(
                key=lambda p: (
                    -int(p.get("confidence", "80%").rstrip("%")),
                    -p.get("ev", 0.0),
                )
            )

            # Count tiers
            tier_counts = []
            for _, lo, hi in TIER_CONFIG:
                count = sum(
                    1 for p in md_picks
                    if lo <= int(p.get("confidence", "80%").rstrip("%")) <= hi
                )
                if count:
                    tier_counts.append(count)

            total = len(md_picks)

            # ── Header ──
            lines.append(
                f"👑 **VFLM {season_name.replace('VFLM ', '')} — "
                f"Matchday {md}** 👑"
            )

            # Tier summary line
            tier_labels = []
            tiers = TIER_CONFIG
            for i, (emoji_tier, lo, hi) in enumerate(tiers):
                count = sum(
                    1 for p in md_picks
                    if lo <= int(p.get("confidence", "80%").rstrip("%")) <= hi
                )
                if count:
                    tier_labels.append(f"{emoji_tier} {count}")
            if tier_labels:
                lines.append("━━━ " + " · ".join(tier_labels) + " ━━━")

            lines.append("")

            # ── Picks grouped by tier ──
            for emoji_badge, lo, hi in tiers:
                tier_picks = [
                    p for p in md_picks
                    if lo <= int(p.get("confidence", "80%").rstrip("%")) <= hi
                ]
                if not tier_picks:
                    continue
                tier_name = emoji_badge
                lines.append(f"**{tier_name}**")
                for pick in tier_picks:
                    line = format_pick_line(pick)
                    lines.append(f"  {line}")
                lines.append("")

            lines.append("")  # spacing between matchdays

    # Edge case: picks JSON has no picks at all
    lines.append(f"📊 **Total: {len(picks)} active picks**")

    return "\n".join(lines).strip()


def load_latest_picks(filepath: str) -> List[Dict[str, Any]]:
    """Load picks and return only the latest batch (same picked_at timestamp)."""
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath) as f:
            picks: List[Dict] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    if not picks:
        return []

    # Find the latest picked_at timestamp
    latest_ts = max(p.get("picked_at", "") for p in picks)
    return [p for p in picks if p.get("picked_at", "") == latest_ts]


def load_all_picks(filepath: str) -> List[Dict[str, Any]]:
    """Load all picks from file."""
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def main() -> None:
    show_all = "--all" in sys.argv
    stdin_mode = "--stdin" in sys.argv
    file_path = None

    for i, arg in enumerate(sys.argv):
        if arg == "--file" and i + 1 < len(sys.argv):
            file_path = sys.argv[i + 1]

    if stdin_mode:
        raw = sys.stdin.read()
        picks = json.loads(raw)
    elif file_path:
        picks = load_all_picks(file_path) if show_all else load_latest_picks(file_path)
    else:
        picks = load_all_picks(PICKS_FILE) if show_all else load_latest_picks(PICKS_FILE)

    if not picks:
        print("🔍 No picks found.")
        return

    print(generate_summary(picks))


if __name__ == "__main__":
    main()
