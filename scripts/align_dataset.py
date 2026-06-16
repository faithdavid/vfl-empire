#!/usr/bin/env python3
"""
Align VFL fixture dataset for mining, backtests, and ML.

Canonical join (matches calculate_cluster_rates / compare_gates_backtest):
  vfl_results_v2 + vfl_matchdays + vfl_seasons
  LEFT JOIN best vfl_odds_v2 row per fixture on:
    (season_id, matchday_number, home_team, away_team)

Default scope: seasons where every MD has >=8 results AND >=8 normal odds rows.

Outputs:
  - Postgres tables: vfl_fixture_aligned, vfl_aligned_seasons
  - data/aligned/vfl_fixture_unified.csv
  - data/aligned/dataset_manifest.json
  - data/aligned/complete_seasons.txt

Usage:
  python3 scripts/align_dataset.py --refresh
  python3 scripts/align_dataset.py --refresh --export
  python3 scripts/align_dataset.py --validate
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EMPIRE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE_ROOT / "services"))
sys.path.insert(0, str(EMPIRE_ROOT / "scripts"))

from common.db_manager import get_db

OUT_DIR = EMPIRE_ROOT / "data" / "aligned"
SQL_DDL = EMPIRE_ROOT / "sql" / "vfl_fixture_aligned.sql"

COMPLETE_SEASON_QUERY = """
WITH latest_odds AS (
    SELECT DISTINCT ON (o.event_id)
        o.event_id,
        o.season_id,
        o.matchday_number,
        o.home_team,
        o.away_team,
        o.o15, o.o25, o.u25, o.u35, o.gg, o.ng,
        o.captured_at
    FROM vfl_odds_v2 o
    ORDER BY o.event_id, o.captured_at DESC
),
season_base AS (
    SELECT s.id, s.season_id AS msport_id, s.season_name
    FROM vfl_seasons s
    WHERE s.season_name LIKE 'VFLM%%'
),
per_md AS (
    SELECT
        sb.season_name,
        sb.msport_id,
        md.id AS matchday_id,
        md.matchday_number,
        COUNT(r.id) AS results,
        COUNT(lo.event_id) AS odds_rows
    FROM season_base sb
    JOIN vfl_matchdays md ON md.season_id = sb.id
    LEFT JOIN vfl_results_v2 r ON r.matchday_id = md.id
    LEFT JOIN latest_odds lo
        ON lo.season_id = sb.msport_id
       AND lo.matchday_number = md.matchday_number
    GROUP BY sb.season_name, sb.msport_id, md.id, md.matchday_number
),
season_agg AS (
    SELECT
        season_name,
        msport_id,
        COUNT(*) AS mds,
        COUNT(*) FILTER (WHERE results >= 8 AND odds_rows >= 8) AS mds_both
    FROM per_md
    GROUP BY season_name, msport_id
)
SELECT season_name, msport_id, mds
FROM season_agg
WHERE mds_both = mds AND mds >= %(min_mds)s
ORDER BY season_name
"""

ALIGN_INSERT = """
WITH best_odds AS (
    SELECT DISTINCT ON (season_id, matchday_number, home_team, away_team)
        season_id,
        matchday_number,
        home_team,
        away_team,
        o15, o25, u25, u35, gg, ng,
        captured_at
    FROM vfl_odds_v2
    WHERE season_id IN (
        SELECT season_id FROM vfl_seasons WHERE season_name = ANY(%(seasons)s)
    )
    ORDER BY
        season_id,
        matchday_number,
        home_team,
        away_team,
        (o15 IS NOT NULL AND o25 IS NOT NULL AND u35 IS NOT NULL AND gg IS NOT NULL) DESC,
        captured_at DESC
),
snapshot_md AS (
    SELECT matchday_id
    FROM vfl_league_snapshots
    GROUP BY matchday_id
    HAVING COUNT(DISTINCT team_name) >= 16
)
INSERT INTO vfl_fixture_aligned (
    result_id, season_name, season_id, matchday_id, matchday_number,
    event_id, home_team, away_team, home_goals, away_goals, total_goals,
    o15, o25, u25, u35, gg, ng, odds_captured_at,
    has_core_odds, has_league_snapshot,
    over_15, over_25, under_25, under_35, gg_yes, ng_yes,
    home_win, draw, away_win, aligned_at
)
SELECT
    r.id,
    s.season_name,
    s.season_id,
    m.id,
    m.matchday_number,
    COALESCE(NULLIF(r.event_id, ''), fem.event_id),
    r.home_team,
    r.away_team,
    r.home_goals,
    r.away_goals,
    r.total_goals,
    o.o15, o.o25, o.u25, o.u35, o.gg, o.ng,
    o.captured_at,
    (o.o15 IS NOT NULL AND o.o25 IS NOT NULL AND o.u35 IS NOT NULL AND o.gg IS NOT NULL),
    (snap.matchday_id IS NOT NULL),
    (r.total_goals > 1),
    (r.total_goals > 2),
    (r.total_goals < 3),
    (r.total_goals < 4),
    (r.home_goals > 0 AND r.away_goals > 0),
    (r.home_goals = 0 OR r.away_goals = 0),
    (r.home_goals > r.away_goals),
    (r.home_goals = r.away_goals),
    (r.home_goals < r.away_goals),
    now()
FROM vfl_results_v2 r
JOIN vfl_matchdays m ON r.matchday_id = m.id
JOIN vfl_seasons s ON m.season_id = s.id
LEFT JOIN fixture_event_map fem
    ON fem.season_id = s.season_id
   AND fem.matchday_number = m.matchday_number
   AND fem.home_team = r.home_team
   AND fem.away_team = r.away_team
LEFT JOIN best_odds o
    ON o.season_id = s.season_id
   AND o.matchday_number = m.matchday_number
   AND o.home_team = r.home_team
   AND o.away_team = r.away_team
LEFT JOIN snapshot_md snap ON snap.matchday_id = m.id
WHERE s.season_name = ANY(%(seasons)s)
ON CONFLICT (result_id) DO UPDATE SET
    season_name = EXCLUDED.season_name,
    season_id = EXCLUDED.season_id,
    matchday_id = EXCLUDED.matchday_id,
    matchday_number = EXCLUDED.matchday_number,
    event_id = EXCLUDED.event_id,
    home_team = EXCLUDED.home_team,
    away_team = EXCLUDED.away_team,
    home_goals = EXCLUDED.home_goals,
    away_goals = EXCLUDED.away_goals,
    total_goals = EXCLUDED.total_goals,
    o15 = EXCLUDED.o15,
    o25 = EXCLUDED.o25,
    u25 = EXCLUDED.u25,
    u35 = EXCLUDED.u35,
    gg = EXCLUDED.gg,
    ng = EXCLUDED.ng,
    odds_captured_at = EXCLUDED.odds_captured_at,
    has_core_odds = EXCLUDED.has_core_odds,
    has_league_snapshot = EXCLUDED.has_league_snapshot,
    over_15 = EXCLUDED.over_15,
    over_25 = EXCLUDED.over_25,
    under_25 = EXCLUDED.under_25,
    under_35 = EXCLUDED.under_35,
    gg_yes = EXCLUDED.gg_yes,
    ng_yes = EXCLUDED.ng_yes,
    home_win = EXCLUDED.home_win,
    draw = EXCLUDED.draw,
    away_win = EXCLUDED.away_win,
    aligned_at = now()
"""


def ensure_schema() -> None:
    if SQL_DDL.exists():
        with get_db() as cur:
            cur.execute(SQL_DDL.read_text(encoding="utf-8"))


def get_complete_seasons(min_mds: int = 28) -> list[tuple[str, str, int]]:
    with get_db() as cur:
        cur.execute(COMPLETE_SEASON_QUERY, {"min_mds": min_mds})
        return cur.fetchall()


SEASON_INSERT = """
WITH best_odds AS (
    SELECT DISTINCT ON (matchday_number, home_team, away_team)
        matchday_number, home_team, away_team,
        o15, o25, u25, u35, gg, ng, captured_at
    FROM vfl_odds_v2
    WHERE season_id = %(season_id)s
    ORDER BY
        matchday_number, home_team, away_team,
        (o15 IS NOT NULL AND o25 IS NOT NULL AND u35 IS NOT NULL AND gg IS NOT NULL) DESC,
        captured_at DESC
),
snapshot_md AS (
    SELECT matchday_id
    FROM vfl_league_snapshots
    GROUP BY matchday_id
    HAVING COUNT(DISTINCT team_name) >= 16
)
INSERT INTO vfl_fixture_aligned (
    result_id, season_name, season_id, matchday_id, matchday_number,
    event_id, home_team, away_team, home_goals, away_goals, total_goals,
    o15, o25, u25, u35, gg, ng, odds_captured_at,
    has_core_odds, has_league_snapshot,
    over_15, over_25, under_25, under_35, gg_yes, ng_yes,
    home_win, draw, away_win, aligned_at
)
SELECT
    r.id, s.season_name, s.season_id, m.id, m.matchday_number,
    COALESCE(NULLIF(r.event_id, ''), fem.event_id),
    r.home_team, r.away_team, r.home_goals, r.away_goals, r.total_goals,
    o.o15, o.o25, o.u25, o.u35, o.gg, o.ng, o.captured_at,
    (o.o15 IS NOT NULL AND o.o25 IS NOT NULL AND o.u35 IS NOT NULL AND o.gg IS NOT NULL),
    (snap.matchday_id IS NOT NULL),
    (r.total_goals > 1), (r.total_goals > 2), (r.total_goals < 3), (r.total_goals < 4),
    (r.home_goals > 0 AND r.away_goals > 0), (r.home_goals = 0 OR r.away_goals = 0),
    (r.home_goals > r.away_goals), (r.home_goals = r.away_goals), (r.home_goals < r.away_goals),
    now()
FROM vfl_results_v2 r
JOIN vfl_matchdays m ON r.matchday_id = m.id
JOIN vfl_seasons s ON m.season_id = s.id
LEFT JOIN fixture_event_map fem
    ON fem.season_id = s.season_id AND fem.matchday_number = m.matchday_number
   AND fem.home_team = r.home_team AND fem.away_team = r.away_team
LEFT JOIN best_odds o
    ON o.matchday_number = m.matchday_number
   AND o.home_team = r.home_team AND o.away_team = r.away_team
LEFT JOIN snapshot_md snap ON snap.matchday_id = m.id
WHERE s.season_name = %(season_name)s
ON CONFLICT (result_id) DO UPDATE SET
    season_name = EXCLUDED.season_name, season_id = EXCLUDED.season_id,
    matchday_id = EXCLUDED.matchday_id, matchday_number = EXCLUDED.matchday_number,
    event_id = EXCLUDED.event_id, home_team = EXCLUDED.home_team, away_team = EXCLUDED.away_team,
    home_goals = EXCLUDED.home_goals, away_goals = EXCLUDED.away_goals, total_goals = EXCLUDED.total_goals,
    o15 = EXCLUDED.o15, o25 = EXCLUDED.o25, u25 = EXCLUDED.u25, u35 = EXCLUDED.u35,
    gg = EXCLUDED.gg, ng = EXCLUDED.ng, odds_captured_at = EXCLUDED.odds_captured_at,
    has_core_odds = EXCLUDED.has_core_odds, has_league_snapshot = EXCLUDED.has_league_snapshot,
    over_15 = EXCLUDED.over_15, over_25 = EXCLUDED.over_25, under_25 = EXCLUDED.under_25,
    under_35 = EXCLUDED.under_35, gg_yes = EXCLUDED.gg_yes, ng_yes = EXCLUDED.ng_yes,
    home_win = EXCLUDED.home_win, draw = EXCLUDED.draw, away_win = EXCLUDED.away_win,
    aligned_at = now()
"""


def refresh_aligned(min_mds: int = 28) -> dict:
    ensure_schema()
    seasons = get_complete_seasons(min_mds=min_mds)
    season_names = [s[0] for s in seasons]

    with get_db() as cur:
        cur.execute("TRUNCATE vfl_fixture_aligned")
        for season_name, season_id, _mds in seasons:
            cur.execute(
                SEASON_INSERT,
                {"season_name": season_name, "season_id": season_id},
            )

        cur.execute("DELETE FROM vfl_aligned_seasons")
        cur.execute(
            """
            INSERT INTO vfl_aligned_seasons (
                season_name, season_id, matchdays, fixtures,
                core_odds_fixtures, snapshot_fixtures, complete_both,
                first_matchday, last_matchday, aligned_at
            )
            SELECT
                season_name,
                season_id,
                COUNT(DISTINCT matchday_number),
                COUNT(*),
                COUNT(*) FILTER (WHERE has_core_odds),
                COUNT(*) FILTER (WHERE has_league_snapshot),
                TRUE,
                MIN(matchday_number),
                MAX(matchday_number),
                now()
            FROM vfl_fixture_aligned
            GROUP BY season_name, season_id
            """
        )

        cur.execute(
            """
            SELECT
                COUNT(*) AS fixtures,
                COUNT(DISTINCT season_name) AS seasons,
                COUNT(*) FILTER (WHERE has_core_odds) AS core_odds,
                COUNT(*) FILTER (WHERE has_league_snapshot) AS with_snapshots
            FROM vfl_fixture_aligned
            """
        )
        fixtures, season_count, core_odds, with_snapshots = cur.fetchone()

    return {
        "seasons": season_count,
        "season_names": season_names,
        "fixtures": fixtures,
        "core_odds_fixtures": core_odds,
        "snapshot_fixtures": with_snapshots,
        "min_mds": min_mds,
        "aligned_at": datetime.now(timezone.utc).isoformat(),
    }


def export_csv() -> Path:
    import csv

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "vfl_fixture_unified.csv"
    cols = [
        "result_id", "season_name", "season_id", "matchday_number", "event_id",
        "home_team", "away_team", "home_goals", "away_goals", "total_goals",
        "o15", "o25", "u25", "u35", "gg", "ng",
        "has_core_odds", "has_league_snapshot",
        "over_15", "over_25", "under_25", "under_35", "gg_yes", "ng_yes",
        "home_win", "draw", "away_win",
    ]
    with get_db() as cur:
        cur.execute(
            f"""
            SELECT {', '.join(cols)}
            FROM vfl_fixture_aligned
            ORDER BY season_name, matchday_number, home_team
            """
        )
        rows = cur.fetchall()

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)
    return out


def write_manifest(stats: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_DIR / "dataset_manifest.json"

    with get_db() as cur:
        cur.execute(
            """
            SELECT season_name, season_id, matchdays, fixtures,
                   core_odds_fixtures, snapshot_fixtures,
                   first_matchday, last_matchday
            FROM vfl_aligned_seasons
            ORDER BY season_name
            """
        )
        season_rows = [
            {
                "season_name": r[0],
                "season_id": r[1],
                "matchdays": r[2],
                "fixtures": r[3],
                "core_odds_fixtures": r[4],
                "snapshot_fixtures": r[5],
                "first_matchday": r[6],
                "last_matchday": r[7],
            }
            for r in cur.fetchall()
        ]

    manifest = {
        **stats,
        "join_keys": ["season_id", "matchday_number", "home_team", "away_team"],
        "core_odds_fields": ["o15", "o25", "u35", "gg"],
        "all_odds_fields": ["o15", "o25", "u25", "u35", "gg", "ng"],
        "outcome_fields": [
            "over_15", "over_25", "under_25", "under_35",
            "gg_yes", "ng_yes", "home_win", "draw", "away_win",
        ],
        "postgres_table": "vfl_fixture_aligned",
        "csv_path": "data/aligned/vfl_fixture_unified.csv",
        "seasons_detail": season_rows,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    seasons_txt = OUT_DIR / "complete_seasons.txt"
    seasons_txt.write_text("\n".join(stats["season_names"]) + "\n", encoding="utf-8")
    return manifest_path


def validate() -> dict:
    with get_db() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE has_core_odds) AS core,
                COUNT(*) FILTER (WHERE NOT has_core_odds) AS missing_core,
                COUNT(DISTINCT season_name) AS seasons
            FROM vfl_fixture_aligned
            """
        )
        total, core, missing_core, seasons = cur.fetchone()

        cur.execute(
            """
            SELECT season_name, matchday_number, COUNT(*) AS n
            FROM vfl_fixture_aligned
            GROUP BY season_name, matchday_number
            HAVING COUNT(*) <> 8
            ORDER BY season_name, matchday_number
            LIMIT 10
            """
        )
        bad_md = cur.fetchall()

    return {
        "total_fixtures": total,
        "core_odds_fixtures": core,
        "missing_core_odds": missing_core,
        "seasons": seasons,
        "non_8_fixture_mds_sample": bad_md,
    }


def main():
    ap = argparse.ArgumentParser(description="Align VFL odds+results dataset")
    ap.add_argument("--refresh", action="store_true", help="Rebuild aligned tables")
    ap.add_argument("--export", action="store_true", help="Export unified CSV")
    ap.add_argument("--validate", action="store_true", help="Print validation summary")
    ap.add_argument("--min-mds", type=int, default=28, help="Min matchdays for complete season")
    args = ap.parse_args()

    if not any([args.refresh, args.export, args.validate]):
        args.refresh = True
        args.export = True
        args.validate = True

    stats = {}
    if args.refresh:
        stats = refresh_aligned(min_mds=args.min_mds)
        print(f"Aligned {stats['fixtures']} fixtures across {stats['seasons']} seasons")
        print(f"  core odds: {stats['core_odds_fixtures']}")
        print(f"  with league snapshots: {stats['snapshot_fixtures']}")
        manifest = write_manifest(stats)
        print(f"Wrote {manifest}")

    if args.export:
        if not stats:
            stats = {"season_names": [s[0] for s in get_complete_seasons(args.min_mds)]}
        csv_path = export_csv()
        print(f"Exported {csv_path}")

    if args.validate:
        v = validate()
        print(json.dumps(v, indent=2, default=str))


if __name__ == "__main__":
    main()