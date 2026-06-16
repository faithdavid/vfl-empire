#!/usr/bin/env python3
"""
Migrate SQLite historical data into central Postgres vfl_empire.

Phases:
  details  - event_details  -> fixture_details
  markets  - deep_markets   -> fixture_markets (joined with event_details metadata)
  results  - vfl_results.db  -> vfl_seasons / vfl_matchdays / vfl_results_v2
  matches  - history.db      -> matches (summary odds + HT/first-goal archive)
  all      - run all phases in order

Usage:
  python3 migrate_sqlite_central.py --phase details
  python3 migrate_sqlite_central.py --phase markets --batch-size 25000
  python3 migrate_sqlite_central.py --phase results
  python3 migrate_sqlite_central.py --phase all
"""
import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

SCRIPTS_DIR = Path(__file__).parent
SERVICES_DIR = SCRIPTS_DIR.parent / "services"
sys.path.insert(0, str(SERVICES_DIR))

from common.db_manager import PG_CONFIG
from common.msport_client import _normalise_team_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sqlite_central_migrate")

SQLITE_ODDS = Path("/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_odds.db")
SQLITE_RESULTS = Path("/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db")
SQLITE_HISTORY = Path("/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db")

MATCHES_COLS = (
    "id", "season", "day", "home", "away",
    "oh", "od", "oa", "o_o25", "o_u25", "o_gg", "o_ng",
    "outcome", "h", "a", "total", "gg", "o25",
    "half_time", "first_goal", "season_start_time", "har_timestamp", "source_file",
)


def parse_ts(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def load_event_meta(sqlite_conn):
    """Latest event_details row per event_id."""
    cur = sqlite_conn.execute(
        """
        SELECT event_id, season_id, match_day, home_team, away_team, detail_json, captured_at
        FROM event_details
        ORDER BY event_id, captured_at DESC
        """
    )
    meta = {}
    details_rows = []
    for row in cur:
        eid = row[0]
        if eid not in meta:
            meta[eid] = {
                "season_id": row[1] or None,
                "matchday_number": row[2],
                "home_team": row[3],
                "away_team": row[4],
            }
            details_rows.append(row)
    logger.info("Loaded %d unique events from event_details", len(meta))
    return meta, details_rows


def migrate_fixture_details(sqlite_conn, pg_conn, batch_size=2000):
    _, details_rows = load_event_meta(sqlite_conn)
    if not details_rows:
        logger.info("No event_details to migrate.")
        return 0

    pg_cur = pg_conn.cursor()
    pg_cur.execute("SELECT event_id FROM fixture_details")
    existing = {r[0] for r in pg_cur.fetchall()}
    logger.info("fixture_details already has %d rows; skipping those event_ids", len(existing))

    inserted = 0
    batch = []
    for row in details_rows:
        eid, season_id, match_day, home, away, detail_json, captured_at = row
        if eid in existing:
            continue
        try:
            payload = json.loads(detail_json) if detail_json else {}
        except json.JSONDecodeError:
            payload = {"raw": detail_json}
        batch.append(
            (
                eid,
                season_id or None,
                match_day,
                home,
                away,
                json.dumps(payload),
                parse_ts(captured_at),
            )
        )
        if len(batch) >= batch_size:
            execute_values(
                pg_cur,
                """
                INSERT INTO fixture_details
                (event_id, season_id, matchday_number, home_team, away_team, details_json, captured_at)
                VALUES %s
                ON CONFLICT (event_id) DO NOTHING
                """,
                batch,
            )
            pg_conn.commit()
            inserted += len(batch)
            logger.info("  fixture_details: +%d (total %d)", len(batch), inserted)
            batch = []

    if batch:
        execute_values(
            pg_cur,
            """
            INSERT INTO fixture_details
            (event_id, season_id, matchday_number, home_team, away_team, details_json, captured_at)
            VALUES %s
            ON CONFLICT (event_id) DO NOTHING
            """,
            batch,
        )
        pg_conn.commit()
        inserted += len(batch)
        logger.info("  fixture_details: +%d (total %d)", len(batch), inserted)

    logger.info("fixture_details migration done: %d rows attempted", inserted)
    return inserted


def migrate_fixture_markets(sqlite_conn, pg_conn, batch_size=25000):
    meta, _ = load_event_meta(sqlite_conn)
    pg_cur = pg_conn.cursor()

    max_id = sqlite_conn.execute("SELECT MAX(id) FROM deep_markets").fetchone()[0] or 0
    logger.info("Migrating deep_markets id 1..%d in batches of %d", max_id, batch_size)

    total_read = 0
    total_inserted = 0
    start = time.time()
    offset_id = 0

    while offset_id < max_id:
        rows = sqlite_conn.execute(
            """
            SELECT id, event_id, market_name, specifiers, selection_name, odds, captured_at
            FROM deep_markets
            WHERE id > ? AND id <= ?
            ORDER BY id
            """,
            (offset_id, offset_id + batch_size),
        ).fetchall()
        offset_id += batch_size
        if not rows:
            continue

        total_read += len(rows)
        batch = []
        for _id, eid, market_name, specifiers, selection_name, odds, captured_at in rows:
            m = meta.get(eid, {})
            batch.append(
                (
                    eid,
                    m.get("season_id"),
                    m.get("matchday_number"),
                    m.get("home_team"),
                    m.get("away_team"),
                    market_name,
                    specifiers or "",
                    selection_name,
                    odds,
                    parse_ts(captured_at),
                )
            )

        execute_values(
            pg_cur,
            """
            INSERT INTO fixture_markets
            (event_id, season_id, matchday_number, home_team, away_team,
             market_name, specifiers, selection_name, odds, captured_at)
            VALUES %s
            ON CONFLICT (event_id, market_name, specifiers, selection_name) DO NOTHING
            """,
            batch,
            page_size=1000,
        )
        pg_conn.commit()
        # rowcount unreliable for execute_values; estimate from batch
        total_inserted += len(batch)
        elapsed = time.time() - start
        rate = total_read / elapsed if elapsed else 0
        logger.info(
            "  markets batch id<=%d: read %d rows (%.0f/s, ~%d total read)",
            offset_id,
            len(rows),
            rate,
            total_read,
        )

    logger.info(
        "fixture_markets migration done: read %d sqlite rows in %.1fs",
        total_read,
        time.time() - start,
    )
    return total_inserted


def migrate_results(sqlite_conn, pg_conn):
    logger.info("Migrating vfl_results.db -> vfl_results_v2 ...")
    sq = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()

    seasons = sq.execute(
        "SELECT DISTINCT season_id, season_name FROM results WHERE season_id != '' ORDER BY season_name"
    ).fetchall()
    logger.info("Found %d seasons in SQLite results", len(seasons))

    inserted_results = 0
    for sid, sname in seasons:
        pg_cur.execute(
            """
            INSERT INTO vfl_seasons (season_id, season_name)
            VALUES (%s, %s)
            ON CONFLICT (season_id) DO UPDATE SET season_name = EXCLUDED.season_name
            RETURNING id
            """,
            (sid, sname),
        )
        db_sid = pg_cur.fetchone()[0]

        mds = sq.execute(
            "SELECT DISTINCT match_day FROM results WHERE season_id = ? ORDER BY match_day",
            (sid,),
        ).fetchall()

        for (md,) in mds:
            pg_cur.execute(
                """
                INSERT INTO vfl_matchdays (season_id, matchday_number, status)
                VALUES (%s, %s, 'FINISHED')
                ON CONFLICT (season_id, matchday_number) DO UPDATE SET status = 'FINISHED'
                RETURNING id
                """,
                (db_sid, md),
            )
            db_md_id = pg_cur.fetchone()[0]

            rows = sq.execute(
                """
                SELECT event_id, home_team, away_team, home_goals, away_goals
                FROM results WHERE season_id = ? AND match_day = ?
                """,
                (sid, md),
            ).fetchall()

            values = [
                (
                    db_md_id,
                    eid,
                    _normalise_team_name(h),
                    _normalise_team_name(a),
                    hg,
                    ag,
                )
                for eid, h, a, hg, ag in rows
            ]
            if values:
                execute_values(
                    pg_cur,
                    """
                    INSERT INTO vfl_results_v2
                    (matchday_id, event_id, home_team, away_team, home_goals, away_goals)
                    VALUES %s
                    ON CONFLICT DO NOTHING
                    """,
                    values,
                )
                inserted_results += len(values)

        pg_conn.commit()

    logger.info("vfl_results_v2 migration done (~%d rows attempted)", inserted_results)
    return inserted_results


def migrate_matches(sqlite_conn, pg_conn, batch_size=10000):
    """Copy history.db matches gap into Postgres (VFLM 5137+ and any other missing rows)."""
    pg_cur = pg_conn.cursor()
    pg_cur.execute("SELECT COUNT(*) FROM matches")
    before = pg_cur.fetchone()[0]

    total_read = 0
    col_str = ", ".join(MATCHES_COLS)
    sqlite_cur = sqlite_conn.execute(
        f"SELECT {col_str} FROM matches ORDER BY id"
    )

    while True:
        rows = sqlite_cur.fetchmany(batch_size)
        if not rows:
            break
        total_read += len(rows)
        execute_values(
            pg_cur,
            f"""
            INSERT INTO matches ({col_str})
            VALUES %s
            ON CONFLICT (season, day, home, away) DO NOTHING
            """,
            rows,
            page_size=1000,
        )
        pg_conn.commit()
        logger.info("  matches: read %d rows so far", total_read)

    pg_cur.execute("SELECT COUNT(*) FROM matches")
    after = pg_cur.fetchone()[0]
    inserted = after - before
    logger.info(
        "matches migration done: %d new rows (%d -> %d, %d sqlite rows scanned)",
        inserted,
        before,
        after,
        total_read,
    )
    return inserted


def print_counts(pg_conn):
    cur = pg_conn.cursor()
    for label, sql in [
        ("fixture_details", "SELECT COUNT(*) FROM fixture_details"),
        ("fixture_markets", "SELECT COUNT(*) FROM fixture_markets"),
        ("fixture_markets events", "SELECT COUNT(DISTINCT event_id) FROM fixture_markets"),
        ("vfl_results_v2", "SELECT COUNT(*) FROM vfl_results_v2"),
        ("vfl_seasons", "SELECT COUNT(*) FROM vfl_seasons"),
        ("matches", "SELECT COUNT(*) FROM matches"),
        ("matches VFLM seasons", "SELECT COUNT(DISTINCT season) FROM matches WHERE season LIKE 'VFLM%'"),
    ]:
        cur.execute(sql)
        logger.info("PG %s: %s", label, cur.fetchone()[0])


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite data to central Postgres")
    parser.add_argument(
        "--phase",
        choices=["details", "markets", "results", "matches", "all"],
        default="all",
        help="Migration phase to run",
    )
    parser.add_argument("--batch-size", type=int, default=25000, help="Batch size for markets")
    args = parser.parse_args()

    if not SQLITE_ODDS.exists():
        logger.error("Missing %s", SQLITE_ODDS)
        sys.exit(1)

    pg_conn = psycopg2.connect(**PG_CONFIG)
    odds_conn = sqlite3.connect(f"file:{SQLITE_ODDS}?mode=ro", uri=True)

    try:
        if args.phase in ("details", "all"):
            migrate_fixture_details(odds_conn, pg_conn)

        if args.phase in ("markets", "all"):
            migrate_fixture_markets(odds_conn, pg_conn, batch_size=args.batch_size)

        if args.phase in ("results", "all"):
            if not SQLITE_RESULTS.exists():
                logger.error("Missing %s", SQLITE_RESULTS)
            else:
                results_conn = sqlite3.connect(f"file:{SQLITE_RESULTS}?mode=ro", uri=True)
                try:
                    migrate_results(results_conn, pg_conn)
                finally:
                    results_conn.close()

        if args.phase in ("matches", "all"):
            if not SQLITE_HISTORY.exists():
                logger.error("Missing %s", SQLITE_HISTORY)
            else:
                history_conn = sqlite3.connect(f"file:{SQLITE_HISTORY}?mode=ro", uri=True)
                try:
                    migrate_matches(history_conn, pg_conn, batch_size=args.batch_size)
                finally:
                    history_conn.close()

        print_counts(pg_conn)
    finally:
        odds_conn.close()
        pg_conn.close()

    logger.info("Done.")


if __name__ == "__main__":
    main()