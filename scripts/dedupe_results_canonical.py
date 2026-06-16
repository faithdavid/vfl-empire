#!/usr/bin/env python3
"""
Canonicalize vfl_results_v2 to MSport truth: 30 MD × 8 fixtures = 240 rows/season.

Rules:
  1) One vfl_seasons row per VFLM name (merge duplicate season PKs).
  2) Per (season, matchday_number): keep exactly 8 rows when possible.
  3) Source priority: vf:match: (live MSport) > history: (MSport history.db) > github_har_result:
  4) Drop all other result rows for that matchday.

Does NOT delete prematch; re-link results only.
"""
from __future__ import annotations

import argparse
import logging
import re
from collections import defaultdict

import sys
from pathlib import Path

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

VFLM_RE = re.compile(r"^VFLM\s+(\d+)$", re.I)


def source_rank(event_id: str) -> int:
    if event_id.startswith("vf:match:"):
        return 0
    if event_id.startswith("history:"):
        return 1
    if event_id.startswith("github_har_result:"):
        return 2
    return 3


def pick_eight(rows: list[dict]) -> list[dict]:
    """One source tier per MD; MSport live > history > HAR."""
    for prefix in ("vf:match:", "history:", "github_har_result:"):
        tier = [r for r in rows if r["event_id"].startswith(prefix)]
        if not tier:
            continue
        tier.sort(key=lambda r: r["id"])
        by_slot: dict[tuple[str, str], dict] = {}
        for r in tier:
            key = (r["home_team"], r["away_team"])
            if key not in by_slot:
                by_slot[key] = r
        chosen = sorted(by_slot.values(), key=lambda r: r["id"])
        if len(chosen) > 8:
            chosen = chosen[:8]
        return chosen
    tier = sorted(rows, key=lambda r: (source_rank(r["event_id"]), r["id"]))
    by_slot = {}
    for r in tier:
        key = (r["home_team"], r["away_team"])
        if key not in by_slot:
            by_slot[key] = r
    chosen = sorted(by_slot.values(), key=lambda r: r["id"])
    return chosen[:8] if len(chosen) > 8 else chosen


def merge_duplicate_season_names(dry_run: bool) -> dict:
    """Same season_name, multiple vfl_seasons.id → keep best PK, reassign matchdays."""
    stats = {"names": 0, "deleted_season_rows": 0, "reassigned_mds": 0}
    with get_db() as cur:
        cur.execute(
            """
            SELECT season_name, array_agg(id ORDER BY id) AS ids,
                   array_agg(season_id ORDER BY id) AS keys
            FROM vfl_seasons
            WHERE season_name ~ '^VFLM'
            GROUP BY season_name
            HAVING COUNT(*) > 1
            """
        )
        dups = cur.fetchall()
        stats["names"] = len(dups)
        for row in dups:
            name = row["season_name"]
            ids = row["ids"]
            # keeper: most live results, else lowest id
            cur.execute(
                """
                SELECT s.id, COUNT(v.id) FILTER (WHERE v.event_id LIKE 'vf:match:%%') AS live_n
                FROM vfl_seasons s
                LEFT JOIN vfl_matchdays md ON md.season_id = s.id
                LEFT JOIN vfl_results_v2 v ON v.matchday_id = md.id
                WHERE s.id = ANY(%s)
                GROUP BY s.id
                ORDER BY live_n DESC, s.id ASC
                """,
                (ids,),
            )
            ranked = cur.fetchall()
            keeper = ranked[0]["id"]
            losers = [r["id"] for r in ranked[1:]]
            for loser in losers:
                cur.execute(
                    "SELECT id, matchday_number FROM vfl_matchdays WHERE season_id = %s",
                    (loser,),
                )
                for md in cur.fetchall():
                    cur.execute(
                        "SELECT id FROM vfl_matchdays WHERE season_id = %s AND matchday_number = %s",
                        (keeper, md["matchday_number"]),
                    )
                    target = cur.fetchone()
                    if target:
                        keeper_md = target["id"]
                        loser_md = md["id"]
                        if not dry_run:
                            cur.execute(
                                """
                                DELETE FROM vfl_results_v2 v
                                USING vfl_results_v2 k
                                WHERE v.matchday_id = %s AND k.matchday_id = %s
                                  AND v.home_team = k.home_team AND v.away_team = k.away_team
                                """,
                                (loser_md, keeper_md),
                            )
                            cur.execute(
                                "UPDATE vfl_results_v2 SET matchday_id = %s WHERE matchday_id = %s",
                                (keeper_md, loser_md),
                            )
                            cur.execute("DELETE FROM vfl_matchdays WHERE id = %s", (loser_md,))
                        stats["reassigned_mds"] += 1
                    else:
                        if not dry_run:
                            cur.execute(
                                "UPDATE vfl_matchdays SET season_id = %s WHERE id = %s",
                                (keeper, md["id"]),
                            )
                        stats["reassigned_mds"] += 1
                if not dry_run:
                    cur.execute("DELETE FROM vfl_seasons WHERE id = %s", (loser,))
                stats["deleted_season_rows"] += 1
            logging.info("merged %s keeper=%s dropped_pks=%s", name, keeper, losers)
    return stats


def dedupe_results(dry_run: bool) -> dict:
    stats = {
        "seasons_processed": 0,
        "matchdays_processed": 0,
        "keep_rows": 0,
        "delete_rows": 0,
        "md_not_eight": 0,
    }
    delete_ids: list[int] = []

    with get_db() as cur:
        cur.execute(
            """
            SELECT DISTINCT s.season_name
            FROM vfl_seasons s
            WHERE s.season_name ~ '^VFLM'
            ORDER BY 1
            """
        )
        season_names = [r["season_name"] for r in cur.fetchall()]

        for sname in season_names:
            cur.execute("SELECT id FROM vfl_seasons WHERE season_name = %s ORDER BY id", (sname,))
            pks = [r["id"] for r in cur.fetchall()]
            if len(pks) > 1:
                continue  # run merge first
            season_pk = pks[0]
            stats["seasons_processed"] += 1

            for md_num in range(1, 31):
                cur.execute(
                    """
                    SELECT v.id, v.event_id, v.home_team, v.away_team, md.id AS md_id
                    FROM vfl_results_v2 v
                    JOIN vfl_matchdays md ON md.id = v.matchday_id
                    WHERE md.season_id = %s AND md.matchday_number = %s
                    """,
                    (season_pk, md_num),
                )
                rows = [dict(r) for r in cur.fetchall()]
                if not rows:
                    continue
                stats["matchdays_processed"] += 1
                keep = pick_eight(rows)
                keep_ids = {r["id"] for r in keep}
                stats["keep_rows"] += len(keep)
                if len(keep) != 8:
                    stats["md_not_eight"] += 1
                for r in rows:
                    if r["id"] not in keep_ids:
                        delete_ids.append(r["id"])
                        stats["delete_rows"] += 1

        logging.info(
            "plan: keep=%s delete=%s md_not_8=%s",
            stats["keep_rows"],
            stats["delete_rows"],
            stats["md_not_eight"],
        )
        if not dry_run and delete_ids:
            # batch delete
            for i in range(0, len(delete_ids), 5000):
                chunk = delete_ids[i : i + 5000]
                cur.execute("DELETE FROM vfl_results_v2 WHERE id = ANY(%s)", (chunk,))

    return stats


def count_complete() -> dict:
    with get_db() as cur:
        cur.execute(
            """
            WITH per AS (
              SELECT s.season_name,
                     COUNT(DISTINCT md.matchday_number) AS md_n,
                     COUNT(v.id) AS res_n
              FROM vfl_seasons s
              JOIN vfl_matchdays md ON md.season_id = s.id
              LEFT JOIN vfl_results_v2 v ON v.matchday_id = md.id
              WHERE s.season_name ~ '^VFLM'
              GROUP BY s.season_name
            )
            SELECT
              COUNT(*) FILTER (WHERE md_n = 30 AND res_n = 240) AS complete_240,
              COUNT(*) FILTER (WHERE md_n = 30 AND res_n >= 240) AS complete_ge240,
              COUNT(*) FILTER (WHERE res_n > 240) AS seasons_over_240,
              SUM(res_n) FILTER (WHERE md_n = 30) AS total_results_30md
            FROM per
            """
        )
        return dict(cur.fetchone())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-merge-seasons", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    before = count_complete()
    print("BEFORE", before)

    if not args.skip_merge_seasons:
        m = merge_duplicate_season_names(dry_run=args.dry_run)
        print("MERGE_SEASONS", m)

    d = dedupe_results(dry_run=args.dry_run)
    print("DEDUPE", d)

    if not args.dry_run:
        after = count_complete()
        print("AFTER", after)
    else:
        print("(dry-run: no AFTER counts)")


if __name__ == "__main__":
    main()