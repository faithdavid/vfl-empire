#!/usr/bin/env python3
"""
One-time ingest: faith-workspace history.db matches -> vfl_results_v2 (+ optional shallow prematch).

Dedupe: ON CONFLICT on (matchday_id, home_team, away_team) DO NOTHING.
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path

EMPIRE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMPIRE / "services"))

from common.db_manager import get_db
from common.prematch_odds import upsert_prematch_records

HISTORY_DB = Path("/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db")
log = logging.getLogger("migrate_history")


def normalise_team(name: str) -> str:
    return (name or "").strip()


def resolve_season(cur, season_key: str) -> int | None:
    """Return vfl_seasons.id (int PK)."""
    sk = str(season_key).strip()
    cur.execute(
        "SELECT id FROM vfl_seasons WHERE season_id = %s OR season_name = %s LIMIT 1",
        (sk, sk),
    )
    row = cur.fetchone()
    if row:
        return row["id"] if isinstance(row, dict) else row[0]

    # VFLM nnnn -> try season_name
    m = re.match(r"VFLM\s*(\d+)", sk, re.I)
    if m:
        name = f"VFLM {m.group(1)}"
        cur.execute("SELECT id FROM vfl_seasons WHERE season_name = %s LIMIT 1", (name,))
        row = cur.fetchone()
        if row:
            return row["id"] if isinstance(row, dict) else row[0]

    season_id_text = sk if sk.startswith("vf:season:") or sk.isdigit() else f"legacy:{sk}"
    if m:
        season_name = f"VFLM {m.group(1)}"
        if not sk.startswith("vf:"):
            season_id_text = f"legacy:{sk}"
    else:
        season_name = sk if sk.startswith("VFLM") else f"legacy_{sk[:32]}"
    cur.execute(
        """
        INSERT INTO vfl_seasons (season_id, season_name)
        VALUES (%s, %s)
        ON CONFLICT (season_id) DO UPDATE SET season_name = EXCLUDED.season_name
        RETURNING id
        """,
        (season_id_text, season_name),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def ensure_matchday(cur, db_season_id: int, day: int) -> int:
    cur.execute(
        """
        INSERT INTO vfl_matchdays (season_id, matchday_number, status)
        VALUES (%s, %s, 'FINISHED')
        ON CONFLICT (season_id, matchday_number) DO UPDATE SET status = EXCLUDED.status
        RETURNING id
        """,
        (db_season_id, int(day)),
    )
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def shallow_odds_records(
    event_id: str,
    season_id_text: str,
    day: int,
    home: str,
    away: str,
    row: sqlite3.Row,
) -> list[dict]:
    recs = []
    base = {
        "event_id": event_id,
        "season_id": season_id_text,
        "matchday_number": int(day),
        "home_team": home,
        "away_team": away,
        "source": "history_sqlite",
    }

    def add(market, spec, sel, val):
        if val is None:
            return
        try:
            odds = float(val)
        except (TypeError, ValueError):
            return
        recs.append({**base, "market_name": market, "specifiers": spec, "selection_name": sel, "odds": odds})

    add("1x2", "", "Home", row["oh"] if "oh" in row.keys() else None)
    add("1x2", "", "Draw", row["od"] if "od" in row.keys() else None)
    add("1x2", "", "Away", row["oa"] if "oa" in row.keys() else None)
    add("Over/Under", "total=2.5", "Over", row["o_o25"] if "o_o25" in row.keys() else None)
    add("Over/Under", "total=2.5", "Under", row["o_u25"] if "o_u25" in row.keys() else None)
    add("GG/NG", "", "Yes", row["o_gg"] if "o_gg" in row.keys() else None)
    add("GG/NG", "", "No", row["o_ng"] if "o_ng" in row.keys() else None)
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-prematch", action="store_true")
    ap.add_argument("--db", type=Path, default=HISTORY_DB)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.db.exists():
        log.error("Missing %s", args.db)
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM matches
        WHERE h IS NOT NULL AND outcome IS NOT NULL
        ORDER BY season, day, id
        """
    )
    rows = cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]
    log.info("Candidate rows with scores: %s", len(rows))

    inserted = 0
    skipped = 0
    prematch_batches: list[dict] = []

    with get_db() as pg:
        for r in rows:
            season_key = r["season"]
            day = r["day"]
            home = normalise_team(r["home"])
            away = normalise_team(r["away"])
            if not home or not away:
                skipped += 1
                continue
            try:
                hg, ag = int(r["h"]), int(r["a"])
            except (TypeError, ValueError):
                skipped += 1
                continue

            if args.dry_run:
                inserted += 1
                continue

            db_sid = resolve_season(pg, season_key)
            if db_sid is None:
                skipped += 1
                continue
            md_id = ensure_matchday(pg, db_sid, day)
            pg.execute(
                "SELECT season_id FROM vfl_seasons WHERE id = %s",
                (db_sid,),
            )
            sid_row = pg.fetchone()
            season_id_text = sid_row["season_id"] if sid_row else str(season_key)

            event_id = f"history:{season_key}:{day}:{home}:{away}"
            pg.execute(
                """
                INSERT INTO vfl_results_v2 (matchday_id, event_id, home_team, away_team, home_goals, away_goals)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (matchday_id, home_team, away_team) DO NOTHING
                """,
                (md_id, event_id, home, away, hg, ag),
            )
            if pg.rowcount:
                inserted += 1
            else:
                skipped += 1

            if not args.skip_prematch:
                prematch_batches.extend(
                    shallow_odds_records(event_id, season_id_text, day, home, away, r)
                )
                if len(prematch_batches) >= 500:
                    upsert_prematch_records(prematch_batches)
                    prematch_batches.clear()

    if prematch_batches and not args.dry_run and not args.skip_prematch:
        upsert_prematch_records(prematch_batches)

    log.info("Done. inserted_results=%s skipped_or_dup=%s dry_run=%s", inserted, skipped, args.dry_run)


if __name__ == "__main__":
    main()