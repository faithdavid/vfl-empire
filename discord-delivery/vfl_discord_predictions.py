#!/usr/bin/env python3
"""
vfl_discord_predictions.py — VFL All-Markets Prediction Delivery
================================================================

Rewritten to predict ALL 6 markets (O1.5, O2.5, U2.5, U3.5, GG, NG)
for EVERY fixture in live_test_predictions.json. Uses H2H historical
hit rates + cluster fingerprint to rank markets by edge. Highlights
the BEST pick per fixture with confidence badges.

Architecture:
  - classify_match() from odds_cluster_classifier → cluster fingerprint
  - gate_h2h() from prediction_gate → H2H rates (called ONCE per fixture)
  - Derive u2_5_rate = 100 - o2_5_rate, ng_rate = 100 - gg_rate
  - u3_5 uses cluster hit_rate or 75% default
  - All 6 markets sorted by edge (hit_rate - implied_prob)
  - Top market = BEST BET with ★

Run directly:  python vfl_discord_predictions.py
Cron: every 3 min via vfl_cron_wrapper.sh (reads live_test_predictions.json)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
PREDICTIONS_FILE = BASE_DIR / "signals" / "predictions_latest.json"

sys.path.insert(0, str(SCRIPTS_DIR))

# Import VFL modules
from odds_cluster_classifier import classify_match
from prediction_gate import gate_h2h

# ── Market definitions ─────────────────────────────────────────────────
# (short_key, json_odds_key)
ALL_MARKETS = [
    ("O1.5", "over_1.5"),
    ("O2.5", "over_2.5"),
    ("U2.5", "under_2.5"),
    ("U3.5", "under_3.5"),
    ("GG",   "gg"),
    ("NG",   "ng"),
]

# Human-readable display names
MARKET_DISPLAY = {
    "O1.5": "Over 1.5 Goals",
    "O2.5": "Over 2.5 Goals",
    "U2.5": "Under 2.5 Goals",
    "U3.5": "Under 3.5 Goals",
    "GG":   "Both Teams to Score",
    "NG":   "No Goal (BTTS No)",
}

# Cluster display profiles (based on centroid analysis)
CLUSTER_PROFILES = [
    "NG profile",
    "NG profile",
    "GG profile (low)",
    "GG profile",
    "O2.5 profile",
    "U2.5 profile",
    "GG profile",
    "GG profile ★",
]


def confidence_badge(hit_rate: float) -> str:
    """Map H2H hit rate to a confidence badge label."""
    if hit_rate >= 75:
        return "HIGH CONFIDENCE"
    elif hit_rate >= 65:
        return "GOOD"
    elif hit_rate >= 55:
        return "DECENT"
    else:
        return "LOW CONFIDENCE"


def load_predictions():
    """Load predictions from PREDICTIONS_FILE, returning its content."""
    try:
        with open(PREDICTIONS_FILE) as f:
            data = json.load(f)
        
        # After loading, print the season, matchday, and first 3 fixtures from the fixtures array in the JSON structure
        matchdays = data.get("matchdays", [])
        if matchdays:
            first_md = matchdays[0]
            season = first_md.get("season", "Unknown Season")
            matchday = first_md.get("matchday", "Unknown Matchday")
            fixtures = first_md.get("fixtures", [])
            print(f"Season: {season}, Matchday: {matchday}")
            print("First 3 fixtures:")
            for fx in fixtures[:3]:
                print(f"  - {fx.get('home')} vs {fx.get('away')}")
                
        return data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"⚠ Error loading {PREDICTIONS_FILE}: {e}", file=sys.stderr)
        return None


def get_h2h_rates(home: str, away: str):
    """Call gate_h2h() ONCE per fixture to extract all H2H rates.

    Also queries DB directly for U3.5 rate (not provided by gate_h2h).

    Returns:
        (h2h_dict, n_matches, avg_total_goals, u3_5_rate)
    """
    import sqlite3

    RESULTS_DB = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db"
    u3_5_rate = None

    # Query U3.5 rate directly from DB
    try:
        conn = sqlite3.connect(RESULTS_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """SELECT
                COUNT(*) as n,
                SUM(CASE WHEN total_goals < 3.5 THEN 1 ELSE 0 END) * 1.0
                    / MAX(COUNT(*), 1) as u3_5_rate
            FROM results
            WHERE status = 3
              AND ((home_team = ? AND away_team = ?) OR (home_team = ? AND away_team = ?))""",
            (home, away, away, home),
        )
        row = cursor.fetchone()
        if row and row["n"] >= 5 and row["u3_5_rate"] is not None:
            u3_5_rate = round(float(row["u3_5_rate"]) * 100, 1)
        conn.close()
    except Exception:
        pass

    try:
        # market_key and odds are dummy — we only read the returned stats
        result = gate_h2h(home, away, "O1.5", 1.01)
    except Exception as e:
        return None, 0, None, u3_5_rate

    if not result or result.get("status") in ("INSUFFICIENT_DATA", "ERROR", None):
        n = result.get("n_matches", 0) if result else 0
        avg = result.get("avg_total_goals") if result else None
        return None, n, avg, u3_5_rate

    n = result.get("n_matches", 0)
    avg = result.get("avg_total_goals")
    return result, n, avg, u3_5_rate


def analyze_fixture(home: str, away: str, odds: dict):
    """Analyze ALL 6 markets for a single fixture.

    Steps:
      1. Classify odds fingerprint → cluster info
      2. Get H2H rates (once)
      3. For each market: compute implied_prob, look up hit_rate, compute edge
      4. Sort by hit rate descending (most likely to win first), then edge

    Returns:
        (ranked_markets, cluster_id, cluster_label, cluster_hit_rate, n_matches)
    """
    # ── 1. Cluster fingerprint ────────────────────────────────────
    o15_odds = odds.get("over_1.5", 0)
    o25_odds = odds.get("over_2.5", 0)
    gg_odds = odds.get("gg", 0)
    u35_odds = odds.get("under_3.5", 0)

    cluster = {"cluster_id": -1, "hit_rate": 0.0, "label": "No data", "rec_bet": ""}
    if all(v > 1.0 for v in [o15_odds, o25_odds, gg_odds, u35_odds]):
        try:
            cluster = classify_match(o15_odds, o25_odds, gg_odds, u35_odds)
        except Exception:
            cluster = {"cluster_id": -1, "hit_rate": 0.0, "label": "Error", "rec_bet": ""}

    cluster_id = cluster.get("cluster_id", -1)
    cluster_hit_rate = cluster.get("hit_rate", 0.0)  # decimal (e.g. 0.585)
    cluster_hit_pct = cluster_hit_rate * 100           # percentage
    cluster_rec_bet = cluster.get("rec_bet", "")
    cluster_label = cluster.get("label", "")
    cluster_profile = CLUSTER_PROFILES[cluster_id] if 0 <= cluster_id < len(CLUSTER_PROFILES) else "Unknown"

    # ── 2. H2H rates (once) ───────────────────────────────────────
    h2h, n_matches, avg_total, u3_5_h2h = get_h2h_rates(home, away)

    # Extract/derive all 6 H2H hit rates (as percentages 0–100)
    if h2h and n_matches >= 5:
        o1_5_rate = h2h.get("o1_5_rate") or 0.0
        o2_5_rate = h2h.get("o2_5_rate") or 0.0
        gg_rate = h2h.get("gg_rate") or 0.0
        ng_rate = h2h.get("ng_rate") or (100.0 - gg_rate)
        u2_5_rate = 100.0 - o2_5_rate
        # U3.5: use actual H2H query if available, else estimate from o2_5_rate
        if u3_5_h2h is not None:
            u3_5_rate = u3_5_h2h
        else:
            # Rough estimate: if o2_5_rate is X%, u3_5_rate ≈ 100 - X*0.7
            u3_5_rate = max(65.0, 100.0 - (o2_5_rate * 0.7))
    else:
        # No H2H data — fall back to cluster + defaults
        o1_5_rate = cluster_hit_pct if cluster_rec_bet == "O1.5" else 70.0
        o2_5_rate = cluster_hit_pct if cluster_rec_bet == "O2.5" else 50.0
        gg_rate = cluster_hit_pct if cluster_rec_bet == "GG" else 50.0
        ng_rate = cluster_hit_pct if cluster_rec_bet == "NG" else 50.0
        u2_5_rate = cluster_hit_pct if cluster_rec_bet == "U2.5" else 50.0
        u3_5_rate = 70.0  # VFL baseline: ~70% of games under 3.5 goals

    hit_rates = {
        "O1.5": o1_5_rate,
        "O2.5": o2_5_rate,
        "U2.5": u2_5_rate,
        "U3.5": u3_5_rate,
        "GG":   gg_rate,
        "NG":   ng_rate,
    }

    # ── 3. Analyze each market ─────────────────────────────────────
    results = []
    for mkt_key, odds_key in ALL_MARKETS:
        odds_val = odds.get(odds_key, 0)
        if odds_val is None or odds_val <= 0:
            continue

        implied_prob = (1.0 / odds_val) * 100
        hit_rate = hit_rates.get(mkt_key, 50.0)

        # If no H2H data, use cluster hit rate as a general guide
        if (not h2h or n_matches < 5) and cluster_hit_pct > 0:
            hit_rate = max(hit_rate, cluster_hit_pct)

        edge = hit_rate - implied_prob

        results.append({
            "market": mkt_key,
            "odds": odds_val,
            "implied_prob": round(implied_prob, 1),
            "hit_rate": round(min(hit_rate, 99.9), 1),
            "edge": round(edge, 1),
            "n_matches": n_matches,
            "avg_total": avg_total,
        })

    # ── 4. Sort by hit rate descending (most likely to win first), then edge ──
    results.sort(key=lambda x: (x["hit_rate"], x["edge"]), reverse=True)

    return results, cluster_id, cluster_label, cluster_profile, cluster_hit_pct, n_matches, avg_total


def format_market_detail(r: dict, is_best: bool = False) -> str:
    """Format a single market line for Discord output."""
    mkt = r["market"]
    hit = r["hit_rate"]
    edge = r["edge"]
    conf = confidence_badge(hit)

    edge_str = f"+{edge}%" if edge >= 0 else f"{edge}%"

    if is_best:
        return (
            f"  ★ BEST BET: {mkt} — {conf} ({hit}% H2H hit rate)\n"
            f"    Edge: {edge_str} | Implied prob: {r['implied_prob']}%"
        )
    else:
        return f"  ● {mkt} — {conf} ({hit}% H2H rate, edge {edge_str})"


def format_output(data: dict) -> str:
    """Build the full Discord-formatted output string."""
    regime = data.get("regime", "STANDARD")
    regime_note = data.get("regime_note", "")
    current_md = data.get("current_matchday", {})
    season = current_md.get("season", "VFLM")
    matchday = current_md.get("matchday", "?")

    lines = []
    total_best_bets = {}
    total_fixtures = 0

    # ── Header ─────────────────────────────────────────────────────
    lines.append(f"👑 {season} — MD{matchday}+ 👑")
    lines.append(f"🔥 {regime} regime | ALL 6 markets per fixture")
    if regime_note:
        # Trim long notes
        note = regime_note if len(regime_note) < 100 else regime_note[:97] + "..."
        lines.append(f"📌 {note}")
    lines.append("")

    # ── Per-matchday processing ────────────────────────────────────
    for md_group in data.get("matchdays", []):
        fixtures = md_group.get("fixtures", [])
        md_num = md_group.get("matchday", "?")
        season_name = md_group.get("season_name", season)

        if not fixtures:
            continue

        lines.append("━" * 45)
        lines.append(f"🔥 MATCHDAY {md_num} — {len(fixtures)} FIXTURES")
        lines.append("━" * 45)
        lines.append("")

        for fixture in fixtures:
            home = fixture.get("home", "?")
            away = fixture.get("away", "?")
            odds = fixture.get("odds", {})

            total_fixtures += 1

            # Analyze this fixture
            results, cid, c_label, c_profile, c_hit_pct, n_matches, avg_total = \
                analyze_fixture(home, away, odds)

            if not results:
                continue

            best = results[0]
            best_mkt = best["market"]
            total_best_bets[best_mkt] = total_best_bets.get(best_mkt, 0) + 1

            # ── Fixture block ──────────────────────────────────────
            lines.append(f"🏆 {home} vs {away}")

            # Context line: cluster + H2H meetings
            context_parts = []
            if cid >= 0:
                context_parts.append(f"Cluster C{cid} {c_profile}")
            if n_matches >= 5:
                context_parts.append(f"H2H: {n_matches} meetings")
                if avg_total is not None:
                    context_parts.append(f"Avg {avg_total} goals")
            if context_parts:
                lines.append(f"  ┃ {' | '.join(context_parts)}")

            # Best bet (prominent, multi-line)
            lines.append(format_market_detail(best, is_best=True))

            # Remaining markets
            for r in results[1:]:
                lines.append(format_market_detail(r))

            lines.append("")

    # ── Summary ────────────────────────────────────────────────────
    lines.append("━" * 45)
    lines.append("📊 SUMMARY")
    lines.append("━" * 45)
    lines.append(f"Total fixtures: {total_fixtures}")

    if total_best_bets:
        # Show breakdown in order of prevalence
        summary_parts = []
        for mkt in ["O1.5", "O2.5", "U2.5", "U3.5", "GG", "NG"]:
            count = total_best_bets.get(mkt, 0)
            if count > 0:
                summary_parts.append(f"{count}× {mkt}")
        lines.append(f"BEST BETS: {' | '.join(summary_parts)}")
    else:
        lines.append("No best bets found")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"⏰ Updated: {now}")

    return "\n".join(lines)


def main():
    """Main entry point."""
    data = load_predictions()
    if not data:
        sys.exit(0)

    output = format_output(data)
    print(output)
    
    try:
        from hermes_notifier import notify
        notify(output)
        print("Predictions successfully delivered to Discord via Hermes.")
    except Exception as e:
        print(f"Failed to deliver to Discord: {e}")


if __name__ == "__main__":
    main()
