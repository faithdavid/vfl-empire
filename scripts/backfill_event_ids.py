#!/usr/bin/env python3
"""Backfill missing or synthetic vfl_results_v2.event_id values where data exists."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services"))

from common.db_manager import get_db  # noqa: E402

COMBER_SYNTHETIC = """
    'vf:match:season:vflm'
    || regexp_replace(s.season_name, 'VFLM ', '')
    || ':md:' || md.matchday_number::text
    || ':' || replace(r.home_team, ' ', '')
    || ':' || replace(r.away_team, ' ', '')
"""

REAL_MSPORT_RES = (
    "res.event_id LIKE 'vf:match:%' AND res.event_id !~ 'season:'"
)
REAL_MSPORT_MKT = (
    "m.event_id LIKE 'vf:match:%' AND m.event_id !~ 'season:'"
)


def count(cur, sql: str) -> int:
    cur.execute(sql)
    return int(cur.fetchone()[0])


def run_step(name: str, sql: str) -> int:
    with get_db() as cur:
        cur.execute(sql)
        updated = cur.rowcount
    print(f"  {name}: updated {updated}")
    return updated


def main() -> None:
    with get_db() as cur:
        null_before = count(cur, "SELECT COUNT(*) FROM vfl_results_v2 WHERE event_id IS NULL")
        vf_season_before = count(
            cur, "SELECT COUNT(*) FROM vfl_results_v2 WHERE event_id LIKE 'vf:season:%'"
        )
        malformed_before = count(
            cur,
            "SELECT COUNT(*) FROM vfl_results_v2 "
            "WHERE event_id LIKE 'vf:match:season:vf:season:%'",
        )
    print(
        f"Before: null={null_before}, vf:season={vf_season_before}, "
        f"malformed={malformed_before}"
    )

    steps = [
        (
            "null_from_results",
            f"""
            UPDATE vfl_results_v2 r
            SET event_id = src.event_id
            FROM (
                SELECT r2.id, res.event_id
                FROM vfl_results_v2 r2
                JOIN vfl_matchdays md ON md.id = r2.matchday_id
                JOIN vfl_seasons s ON s.id = md.season_id
                JOIN results res
                  ON res.season_id = s.season_id
                 AND res.match_day = md.matchday_number
                 AND res.home_team = r2.home_team
                 AND res.away_team = r2.away_team
                WHERE r2.event_id IS NULL
                  AND res.event_id IS NOT NULL
                  AND res.event_id != ''
                  AND {REAL_MSPORT_RES}
            ) src
            WHERE r.id = src.id
            """,
        ),
        (
            "null_from_markets",
            f"""
            UPDATE vfl_results_v2 r
            SET event_id = src.event_id
            FROM (
                SELECT DISTINCT ON (r2.id) r2.id, m.event_id
                FROM vfl_results_v2 r2
                JOIN vfl_matchdays md ON md.id = r2.matchday_id
                JOIN vfl_seasons s ON s.id = md.season_id
                JOIN fixture_markets m
                  ON m.season_id = s.season_id
                 AND m.matchday_number = md.matchday_number
                 AND m.home_team = r2.home_team
                 AND m.away_team = r2.away_team
                WHERE r2.event_id IS NULL
                  AND {REAL_MSPORT_MKT}
                ORDER BY r2.id, m.event_id
            ) src
            WHERE r.id = src.id
            """,
        ),
        (
            "null_synthetic_comber",
            f"""
            UPDATE vfl_results_v2 r
            SET event_id = {COMBER_SYNTHETIC}
            FROM vfl_matchdays md
            JOIN vfl_seasons s ON s.id = md.season_id
            WHERE r.matchday_id = md.id
              AND r.event_id IS NULL
            """,
        ),
        (
            "malformed_from_markets",
            f"""
            UPDATE vfl_results_v2 r
            SET event_id = src.event_id
            FROM (
                SELECT DISTINCT ON (r2.id) r2.id, m.event_id
                FROM vfl_results_v2 r2
                JOIN vfl_matchdays md ON md.id = r2.matchday_id
                JOIN vfl_seasons s ON s.id = md.season_id
                JOIN fixture_markets m
                  ON m.season_id = s.season_id
                 AND m.matchday_number = md.matchday_number
                 AND m.home_team = r2.home_team
                 AND m.away_team = r2.away_team
                WHERE r2.event_id LIKE 'vf:match:season:vf:season:%'
                  AND {REAL_MSPORT_MKT}
                ORDER BY r2.id, m.event_id
            ) src
            WHERE r.id = src.id
            """,
        ),
        (
            "delete_redundant_malformed",
            """
            DELETE FROM vfl_results_v2 r
            USING vfl_matchdays md, vfl_seasons s
            WHERE r.matchday_id = md.id
              AND s.id = md.season_id
              AND r.event_id LIKE 'vf:match:season:vf:season:%'
              AND EXISTS (
                SELECT 1
                FROM vfl_results_v2 r2
                JOIN vfl_matchdays md2 ON md2.id = r2.matchday_id
                JOIN vfl_seasons s2 ON s2.id = md2.season_id
                WHERE s2.season_name = s.season_name
                  AND md2.matchday_number = md.matchday_number
                  AND r2.home_team = r.home_team
                  AND r2.away_team = r.away_team
                  AND r2.id != r.id
                  AND r2.event_id NOT LIKE 'vf:match:season:vf:season:%'
              )
            """,
        ),
        (
            "malformed_to_comber",
            f"""
            UPDATE vfl_results_v2 r
            SET event_id = {COMBER_SYNTHETIC}
            FROM vfl_matchdays md
            JOIN vfl_seasons s ON s.id = md.season_id
            WHERE r.matchday_id = md.id
              AND r.event_id LIKE 'vf:match:season:vf:season:%'
              AND NOT EXISTS (
                SELECT 1 FROM vfl_results_v2 ex
                WHERE ex.event_id = {COMBER_SYNTHETIC}
                  AND ex.id != r.id
              )
            """,
        ),
        (
            "malformed_suffix_fallback",
            f"""
            UPDATE vfl_results_v2 r
            SET event_id = {COMBER_SYNTHETIC} || ':r' || r.id::text
            FROM vfl_matchdays md
            JOIN vfl_seasons s ON s.id = md.season_id
            WHERE r.matchday_id = md.id
              AND r.event_id LIKE 'vf:match:season:vf:season:%'
            """,
        ),
        (
            "vf_season_from_markets",
            f"""
            UPDATE vfl_results_v2 r
            SET event_id = src.event_id
            FROM (
                SELECT DISTINCT ON (r2.id) r2.id, m.event_id
                FROM vfl_results_v2 r2
                JOIN vfl_matchdays md ON md.id = r2.matchday_id
                JOIN vfl_seasons s ON s.id = md.season_id
                JOIN fixture_markets m
                  ON m.season_id = s.season_id
                 AND m.matchday_number = md.matchday_number
                 AND m.home_team = r2.home_team
                 AND m.away_team = r2.away_team
                WHERE r2.event_id LIKE 'vf:season:%'
                  AND {REAL_MSPORT_MKT}
                ORDER BY r2.id, m.event_id
            ) src
            WHERE r.id = src.id
            """,
        ),
    ]

    for name, sql in steps:
        run_step(name, sql)

    with get_db() as cur:
        null_after = count(cur, "SELECT COUNT(*) FROM vfl_results_v2 WHERE event_id IS NULL")
        vf_season_after = count(
            cur, "SELECT COUNT(*) FROM vfl_results_v2 WHERE event_id LIKE 'vf:season:%'"
        )
        malformed_after = count(
            cur,
            "SELECT COUNT(*) FROM vfl_results_v2 "
            "WHERE event_id LIKE 'vf:match:season:vf:season:%'",
        )
        real_after = count(
            cur,
            "SELECT COUNT(*) FROM vfl_results_v2 "
            "WHERE event_id ~ '^vf:match:[0-9]+$'",
        )
        join_after = count(
            cur,
            """
            SELECT COUNT(*) FROM vfl_results_v2 r
            JOIN fixture_markets m ON r.event_id = m.event_id
            WHERE r.event_id ~ '^vf:match:[0-9]+$'
            """,
        )
    print(
        f"After: null={null_after}, vf:season={vf_season_after}, "
        f"malformed={malformed_after}, real_msport={real_after}, "
        f"market_join_rows={join_after}"
    )


if __name__ == "__main__":
    main()