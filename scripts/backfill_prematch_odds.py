#!/usr/bin/env python3
"""
One-time / repeatable backfill: fixture_markets + vfl_odds_v2 -> vfl_prematch_odds.
Uses ON CONFLICT so re-runs are safe; fixture_markets rows win on conflict (loaded first).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

EMPIRE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMPIRE_ROOT / "services"))

from common.db_manager import get_db
from common.prematch_odds import upsert_prematch_records, vfl_odds_v2_to_records

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("backfill_prematch")


def backfill_fixture_markets(batch: int, offset: int, limit: int | None) -> int:
    total = 0
    last_id = offset
    while True:
        if limit is not None and total >= limit:
            break
        chunk = batch if limit is None else min(batch, limit - total)
        with get_db() as cur:
            cur.execute(
                """
                SELECT id, event_id, season_id, matchday_number, home_team, away_team,
                       market_name, specifiers, selection_name, odds, captured_at
                FROM fixture_markets
                WHERE id > %s
                ORDER BY id
                LIMIT %s
                """,
                (last_id, chunk),
            )
            rows = cur.fetchall()
        if not rows:
            break
        records = []
        cap = None
        for r in rows:
            last_id = r["id"]
            cap = r["captured_at"]
            records.append(
                {
                    "event_id": r["event_id"],
                    "season_id": r["season_id"],
                    "matchday_number": r["matchday_number"],
                    "home_team": r["home_team"],
                    "away_team": r["away_team"],
                    "market_name": r["market_name"],
                    "specifiers": r["specifiers"] or "",
                    "selection_name": r["selection_name"],
                    "odds": r["odds"],
                    "source": "fixture_markets_backfill",
                }
            )
        upsert_prematch_records(records, captured_at=cap)
        total += len(records)
        if total % 50000 < batch:
            log.info("fixture_markets backfill progress: %s rows (last_id=%s)", total, last_id)
    return total


def backfill_vfl_odds_v2(batch: int) -> int:
    total = 0
    last_id = 0
    while True:
        with get_db() as cur:
            cur.execute(
                """
                SELECT id, event_id, season_id, matchday_number, home_team, away_team,
                       o15, o25, u25, u35, gg, ng, captured_at
                FROM vfl_odds_v2
                WHERE id > %s AND event_id IS NOT NULL AND event_id <> 'test_sid'
                ORDER BY id
                LIMIT %s
                """,
                (last_id, batch),
            )
            rows = cur.fetchall()
        if not rows:
            break
        for r in rows:
            last_id = r["id"]
            recs = vfl_odds_v2_to_records(
                r["event_id"],
                r["season_id"],
                r["matchday_number"],
                r["home_team"],
                r["away_team"],
                r["o15"],
                r["o25"],
                r["u25"],
                r["u35"],
                r["gg"],
                r["ng"],
            )
            upsert_prematch_records(recs, captured_at=r["captured_at"])
            total += len(recs)
        if total and total % 20000 < batch * 6:
            log.info("vfl_odds_v2 backfill progress: ~%s selection rows (last_id=%s)", total, last_id)
    return total


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--batch", type=int, default=5000)
    p.add_argument("--skip-markets", action="store_true")
    p.add_argument("--skip-v2", action="store_true")
    p.add_argument("--markets-limit", type=int, default=None, help="For testing")
    p.add_argument("--markets-offset", type=int, default=0)
    args = p.parse_args()

    t0 = time.time()
    n1 = n2 = 0
    if not args.skip_markets:
        log.info("Backfilling from fixture_markets...")
        n1 = backfill_fixture_markets(args.batch, args.markets_offset, args.markets_limit)
        log.info("fixture_markets done: %s rows in %.1fs", n1, time.time() - t0)
    if not args.skip_v2:
        log.info("Backfilling from vfl_odds_v2 (fills gaps only on conflict)...")
        n2 = backfill_vfl_odds_v2(args.batch)
        log.info("vfl_odds_v2 done: %s selection rows", n2)

    with get_db() as cur:
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT season_id), COUNT(DISTINCT event_id) FROM vfl_prematch_odds")
        row = cur.fetchone()
    log.info("vfl_prematch_odds totals: rows=%s seasons=%s events=%s", row[0], row[1], row[2])


if __name__ == "__main__":
    main()