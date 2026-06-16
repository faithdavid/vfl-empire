#!/usr/bin/env python3
"""Export vfl_seasons + history.sqlite distinct season keys -> docs/SEASON_ID_MAP.csv"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

EMPIRE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMPIRE / "services"))

from common.db_manager import get_db

HISTORY_DB = Path("/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db")
OUT = EMPIRE / "docs" / "SEASON_ID_MAP.csv"


def main():
    rows: list[dict] = []
    with get_db() as cur:
        cur.execute("SELECT season_id, season_name, id FROM vfl_seasons ORDER BY season_name")
        for r in cur.fetchall():
            rows.append({
                "source_key": r["season_id"],
                "season_name": r["season_name"] or "",
                "pg_vfl_seasons_id": r["id"],
                "source": "postgres",
            })

    if HISTORY_DB.exists():
        conn = sqlite3.connect(HISTORY_DB)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT season FROM matches ORDER BY season")
        pg_ids = {x["source_key"] for x in rows}
        for (season,) in cur.fetchall():
            if season in pg_ids:
                continue
            name = season if str(season).startswith("VFLM") else ""
            rows.append({
                "source_key": season,
                "season_name": name,
                "pg_vfl_seasons_id": "",
                "source": "history_sqlite_unmapped",
            })
        conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source_key", "season_name", "pg_vfl_seasons_id", "source"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()