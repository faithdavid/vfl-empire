#!/usr/bin/env python3
"""Reconciliation: SQLite history vs Postgres silver tables."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

EMPIRE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

HISTORY = Path("/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db")


def main():
    conn = sqlite3.connect(HISTORY)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM matches WHERE h IS NOT NULL")
    hist_scored = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT season) FROM matches WHERE h IS NOT NULL")
    hist_seasons = c.fetchone()[0]
    conn.close()

    with get_db() as cur:
        cur.execute("SELECT COUNT(*) FROM vfl_results_v2")
        pg_res = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(DISTINCT vs.id) FROM vfl_results_v2 r
            JOIN vfl_matchdays md ON md.id = r.matchday_id
            JOIN vfl_seasons vs ON vs.id = md.season_id
            """
        )
        pg_seasons = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT season_id) FROM vfl_prematch_odds")
        pm = cur.fetchone()
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT season_id) FROM fixture_markets")
        fm = cur.fetchone()

    print("=== Reconciliation ===")
    print(f"history.db scored rows:     {hist_scored} ({hist_seasons} seasons)")
    print(f"PG vfl_results_v2 rows:     {pg_res} ({pg_seasons} seasons with results)")
    print(f"PG vfl_prematch_odds:       {pm[0]} rows, {pm[1]} season_ids")
    print(f"PG fixture_markets (legacy): {fm[0]} rows, {fm[1]} season_ids")
    print("Prematch backfill target:   prematch seasons >= fixture_markets distinct season_id")


if __name__ == "__main__":
    main()