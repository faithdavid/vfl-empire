#!/usr/bin/env python3
"""
vfl_fresh_backtest.py — Rigorous Backtester for Freshest-Table + 1X2/GGNG Logic
================================================================================
Replays using "freshest table at decision time" (via captured_at).
Captures BOTH 1X2 (oracle mechanical + dynamic edge) and GG/NG.
Uses central DB vfl_results_v2 for historical results + timing.

Compares implicitly to old x-2 by using freshest instead.
Reports win rates for 1X2 and GG/NG separately.

Run:
  python3 truth-bot/vfl_fresh_backtest.py --season "VFLM 5345" --start-md 5 --num-mds 20
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timezone

EMPIRE_ROOT = Path("/home/ubuntu/faith-workspace/vfl-empire")
TRUTH_DIR = EMPIRE_ROOT / "truth-bot"
sys.path.insert(0, str(EMPIRE_ROOT / "scripts"))
sys.path.insert(0, str(TRUTH_DIR))

import msport_api

DB_CONFIG = {"dbname": "vfl_empire", "user": "vfl_user", "password": "vfl_pass", "host": "localhost", "port": 5432}

RESULTS_QUERY = """
    SELECT r.home_team, r.away_team, r.home_goals, r.away_goals,
           m.matchday_number AS match_day, r.captured_at
    FROM vfl_results_v2 r
    JOIN vfl_matchdays m ON r.matchday_id = m.id
    JOIN vfl_seasons s ON m.season_id = s.id
"""

def get_db():
    return psycopg2.connect(**DB_CONFIG)

def get_results_as_of(season: str, up_to_md: int, as_of: datetime):
    """Results that would have been available at 'as_of' time."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute(
        RESULTS_QUERY
        + """
        WHERE s.season_name = %s AND m.matchday_number <= %s AND r.captured_at <= %s
        ORDER BY m.matchday_number, r.captured_at
        """,
        (season, up_to_md, as_of),
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def _tier_label(rank: int) -> str:
    if rank < 4:
        return "T1"
    if rank < 8:
        return "T2"
    if rank < 12:
        return "T3"
    return "T4"


def build_freshest_tiers(results):
    """Build tiers from results available at decision time."""
    col = defaultdict(lambda: {"played": 0, "won": 0, "draw": 0, "lost": 0, "gf": 0, "ga": 0})
    for r in results:
        h, a = r["home_team"], r["away_team"]
        hg, ag = r["home_goals"] or 0, r["away_goals"] or 0
        col[h]["played"] += 1
        col[h]["gf"] += hg
        col[h]["ga"] += ag
        col[a]["played"] += 1
        col[a]["gf"] += ag
        col[a]["ga"] += hg
        if hg > ag:
            col[h]["won"] += 1
            col[a]["lost"] += 1
        elif ag > hg:
            col[a]["won"] += 1
            col[h]["lost"] += 1
        else:
            col[h]["draw"] += 1
            col[a]["draw"] += 1
    table = []
    for team, s in col.items():
        gd = s["gf"] - s["ga"]
        pts = s["won"] * 3 + s["draw"]
        table.append({"team": team, "pts": pts, "gd": gd})
    table.sort(key=lambda x: (-x["pts"], -x["gd"]))
    return {t["team"]: _tier_label(i) for i, t in enumerate(table)}


def build_x2_tiers(by_md: dict, target_md: int) -> dict:
    """Match export_locks.py: predict MD N using standings through MD N-2."""
    md_games = by_md.get(target_md, [])
    if target_md <= 2:
        teams = set()
        for r in md_games:
            teams.add(r["home_team"])
            teams.add(r["away_team"])
        return {team: "T0" for team in teams}

    cutoff = target_md - 2
    col = defaultdict(lambda: {"pts": 0, "gd": 0})
    for md in range(1, cutoff + 1):
        for r in by_md.get(md, []):
            h, a = r["home_team"], r["away_team"]
            hg, ag = r["home_goals"] or 0, r["away_goals"] or 0
            col[h]["gd"] += hg - ag
            col[a]["gd"] += ag - hg
            if hg > ag:
                col[h]["pts"] += 3
            elif ag > hg:
                col[a]["pts"] += 3
            else:
                col[h]["pts"] += 1
                col[a]["pts"] += 1

    standings = sorted(col.keys(), key=lambda t: (col[t]["pts"], col[t]["gd"]), reverse=True)
    return {team: _tier_label(i) for i, team in enumerate(standings)}


def dedupe_results_by_md(rows):
    """Keep one result row per matchday/fixture (latest capture)."""
    by_md = defaultdict(dict)
    for r in rows:
        md = r["match_day"]
        key = (r["home_team"], r["away_team"])
        prev = by_md[md].get(key)
        if prev is None or r["captured_at"] >= prev["captured_at"]:
            by_md[md][key] = r
    return {md: list(fixtures.values()) for md, fixtures in by_md.items()}

def compute_simple_1x2_h2h(home, away, results):
    """Simple H2H for 1X2 hit rates from available results."""
    hw = dw = aw = 0
    n = 0
    for r in results:
        if (r["home_team"] == home and r["away_team"] == away) or (r["home_team"] == away and r["away_team"] == home):
            hg, ag = r["home_goals"] or 0, r["away_goals"] or 0
            if hg > ag:
                if r["home_team"] == home: hw += 1
                else: aw += 1
            elif ag > hg:
                if r["home_team"] == home: aw += 1
                else: hw += 1
            else:
                dw += 1
            n += 1
    if n < 3:
        return {"HOME WIN": 42.0, "DRAW": 28.0, "AWAY WIN": 30.0}
    return {
        "HOME WIN": round((hw / n) * 100, 1),
        "DRAW": round((dw / n) * 100, 1),
        "AWAY WIN": round((aw / n) * 100, 1)
    }

def load_season_results(season: str):
    conn = get_db()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute(
        RESULTS_QUERY
        + """
        WHERE s.season_name = %s
        ORDER BY m.matchday_number, r.captured_at
        """,
        (season,),
    )
    rows = cur.fetchall()
    conn.close()
    return dedupe_results_by_md(rows)


def list_seasons_with_results():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT s.season_name
        FROM vfl_seasons s
        JOIN vfl_matchdays m ON m.season_id = s.id
        JOIN vfl_results_v2 r ON r.matchday_id = m.id
        ORDER BY s.season_name
        """
    )
    seasons = [row[0] for row in cur.fetchall()]
    conn.close()
    return seasons


def backtest_freshest(
    season: str,
    start_md: int,
    num_mds: int,
    oracle: dict,
    tier_mode: str = "fresh",
    oracle_only: bool = False,
):
    """Main backtest: freshest or x-2 tiers, optional oracle-only mode."""
    by_md = load_season_results(season)
    all_res = [r for md in sorted(by_md) for r in by_md[md]]

    stats = {
        "season": season,
        "tier_mode": tier_mode,
        "1x2_locks": 0,
        "1x2_wins": 0,
        "oracle_locks": 0,
        "oracle_wins": 0,
        "ggng_locks": 0,
        "ggng_wins": 0,
        "details": [],
    }

    for tmd in range(start_md, start_md + num_mds):
        if tmd not in by_md:
            continue

        if tier_mode == "x2":
            tiers = build_x2_tiers(by_md, tmd)
            available = [r for r in all_res if r["match_day"] <= max(0, tmd - 1)]
        else:
            prev = tmd - 1
            if prev not in by_md:
                continue
            decision_time = max(r["captured_at"] for r in by_md[prev])
            available = [r for r in all_res if r["captured_at"] <= decision_time and r["match_day"] <= prev]
            tiers = build_freshest_tiers(available)

        target_res = by_md.get(tmd, [])
        for res in target_res:
            home = res["home_team"]
            away = res["away_team"]
            hg, ag = res["home_goals"] or 0, res["away_goals"] or 0
            home_t = tiers.get(home, "T0")
            away_t = tiers.get(away, "T0")
            fp = f"MD{tmd} | {home}({home_t}) vs {away}({away_t})"

            if fp in oracle:
                lock_out = oracle[fp]["outcome"]
                actual = "HOME WIN" if hg > ag else ("AWAY WIN" if ag > hg else "DRAW")
                win = lock_out == actual
                stats["oracle_locks"] += 1
                stats["1x2_locks"] += 1
                if win:
                    stats["oracle_wins"] += 1
                    stats["1x2_wins"] += 1
                stats["details"].append(
                    {"md": tmd, "type": "oracle", "fp": fp, "lock": lock_out, "actual": actual, "win": win}
                )

            if oracle_only:
                continue

            # Dynamic 1X2 + GG/NG using freshest data (edge based)
            h2h_1x2 = compute_simple_1x2_h2h(home, away, available)
            total = hg + ag
            is_gg = total >= 2

            # Simple edge for 1X2 (using H2H from available)
            for out, rate in h2h_1x2.items():
                # placeholder implied ~ historical avg
                imp = {"HOME WIN": 42, "DRAW": 28, "AWAY WIN": 30}[out]
                edge = rate - imp
                if edge > 5:
                    actual_out = "HOME WIN" if hg > ag else ("AWAY WIN" if ag > hg else "DRAW")
                    win = (out == actual_out)
                    stats["1x2_locks"] += 1
                    if win:
                        stats["1x2_wins"] += 1
                    stats["details"].append({"md": tmd, "type": "1X2-dynamic", "fp": fp, "lock": out, "actual": actual_out, "win": win, "edge": edge})

            # GG/NG
            gg_rate = sum(1 for r in available if (r["home_team"]==home and r["away_team"]==away) or (r["home_team"]==away and r["away_team"]==home) and (r["home_goals"]+r["away_goals"] >= 2)) / max(1, len([r for r in available if (r["home_team"]==home and r["away_team"]==away) or (r["home_team"]==away and r["away_team"]==home)])) * 100 if any((r["home_team"]==home and r["away_team"]==away) or (r["home_team"]==away and r["away_team"]==home) for r in available) else 52.0
            for mkt in ["GG", "NG"]:
                mkt_rate = gg_rate if mkt == "GG" else (100 - gg_rate)
                # placeholder edge
                if mkt_rate > 55:
                    actual_gg = total >= 2
                    win = (mkt == "GG" and actual_gg) or (mkt == "NG" and not actual_gg)
                    stats["ggng_locks"] += 1
                    if win:
                        stats["ggng_wins"] += 1
                    stats["details"].append({"md": tmd, "type": "GGNG", "fp": fp, "lock": mkt, "actual": "GG" if actual_gg else "NG", "win": win})

    if stats["oracle_locks"]:
        stats["oracle_winrate"] = round(100 * stats["oracle_wins"] / stats["oracle_locks"], 1)
    if stats["1x2_locks"]:
        stats["1x2_winrate"] = round(100 * stats["1x2_wins"] / stats["1x2_locks"], 1)
    if stats["ggng_locks"]:
        stats["ggng_winrate"] = round(100 * stats["ggng_wins"] / stats["ggng_locks"], 1)
    return stats


def backtest_oracle_all_seasons(oracle: dict, start_md: int = 3, end_md: int = 30):
    aggregate = {
        "seasons_tested": 0,
        "oracle_locks": 0,
        "oracle_wins": 0,
        "oracle_misses": [],
        "by_season": {},
    }
    for season in list_seasons_with_results():
        stats = backtest_freshest(
            season,
            start_md,
            end_md - start_md + 1,
            oracle,
            tier_mode="x2",
            oracle_only=True,
        )
        if stats["oracle_locks"] == 0:
            continue
        aggregate["seasons_tested"] += 1
        aggregate["oracle_locks"] += stats["oracle_locks"]
        aggregate["oracle_wins"] += stats["oracle_wins"]
        aggregate["by_season"][season] = {
            "locks": stats["oracle_locks"],
            "wins": stats["oracle_wins"],
            "winrate": stats.get("oracle_winrate", 0),
        }
        for detail in stats["details"]:
            if detail.get("type") == "oracle" and not detail["win"]:
                aggregate["oracle_misses"].append({"season": season, **detail})

    if aggregate["oracle_locks"]:
        aggregate["oracle_winrate"] = round(
            100 * aggregate["oracle_wins"] / aggregate["oracle_locks"], 1
        )
    return aggregate


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--season", default="VFLM 5291")
    p.add_argument("--all-seasons", action="store_true")
    p.add_argument("--start-md", type=int, default=3)
    p.add_argument("--num-mds", type=int, default=28)
    p.add_argument("--tier-mode", choices=["fresh", "x2"], default="x2")
    p.add_argument("--oracle-only", action="store_true")
    args = p.parse_args()

    oracle = (
        json.loads((TRUTH_DIR / "oracle_locks.json").read_text())
        if (TRUTH_DIR / "oracle_locks.json").exists()
        else {}
    )

    if args.all_seasons:
        stats = backtest_oracle_all_seasons(
            oracle, start_md=args.start_md, end_md=args.start_md + args.num_mds - 1
        )
        print("=== ORACLE LOCK BACKTEST (ALL SEASONS, X-2 TIERS) ===")
    else:
        stats = backtest_freshest(
            args.season,
            args.start_md,
            args.num_mds,
            oracle,
            tier_mode=args.tier_mode,
            oracle_only=args.oracle_only,
        )
        print(f"=== BACKTEST ({stats['tier_mode'].upper()} TIERS) ===")

    print(json.dumps({k: v for k, v in stats.items() if k not in ("details", "by_season", "oracle_misses")}, indent=2))
    if stats.get("by_season"):
        top = sorted(stats["by_season"].items(), key=lambda x: x[1]["locks"], reverse=True)[:8]
        print("\nTop seasons by oracle lock volume:")
        for season, row in top:
            print(f"  {season}: {row['wins']}/{row['locks']} ({row['winrate']}%)")
    if stats.get("oracle_misses"):
        print(f"\nOracle misses ({len(stats['oracle_misses'])}):")
        for miss in stats["oracle_misses"][:10]:
            print(f"  {miss['season']} {miss['fp']} locked {miss['lock']} got {miss['actual']}")
    elif stats.get("details"):
        print(f"\nSample details (first 5): {stats['details'][:5]}")
