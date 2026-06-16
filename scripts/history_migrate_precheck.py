#!/usr/bin/env python3
"""Count how many history.db scored rows are NOT already in vfl_results_v2 (same season/day/teams)."""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

EMPIRE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

HISTORY = Path("/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db")


def norm(s):
    return (s or "").strip()


def main():
    conn = sqlite3.connect(HISTORY)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT season, day, home, away FROM matches WHERE h IS NOT NULL AND outcome IS NOT NULL"
    )
    rows = cur.fetchall()
    conn.close()

    # Build PG lookup: (season_id text, md, home, away) from vfl_results_v2
    with get_db() as pg:
        pg.execute(
            """
            SELECT vs.season_id, vs.season_name, md.matchday_number, r.home_team, r.away_team
            FROM vfl_results_v2 r
            JOIN vfl_matchdays md ON md.id = r.matchday_id
            JOIN vfl_seasons vs ON vs.id = md.season_id
            """
        )
        existing = set()
        for r in pg.fetchall():
            sid = r["season_id"] if hasattr(r, "keys") else r[0]
            sname = r["season_name"] if hasattr(r, "keys") else r[1]
            md = r["matchday_number"] if hasattr(r, "keys") else r[2]
            h, a = r["home_team"], r["away_team"]
            existing.add((str(sid), int(md), norm(h), norm(a)))
            if sname:
                existing.add((str(sname), int(md), norm(h), norm(a)))

    def keys_for(season_key, day, home, away):
        sk = str(season_key).strip()
        h, a = norm(home), norm(away)
        d = int(day)
        out = {(sk, d, h, a)}
        m = re.match(r"VFLM\s*(\d+)", sk, re.I)
        if m:
            out.add((f"VFLM {m.group(1)}", d, h, a))
        return out

    would_insert = 0
    already = 0
    for r in rows:
        kset = keys_for(r["season"], r["day"], r["home"], r["away"])
        if any(k in existing for k in kset):
            already += 1
        else:
            would_insert += 1

    print("=== history.db vs PG (honest overlap) ===")
    print(f"history scored rows:        {len(rows)}")
    print(f"already in vfl_results_v2:  {already}")
    print(f"would NEW insert:           {would_insert}")
    print("(Migrate uses ON CONFLICT — real insert count should match 'would NEW' roughly)")


if __name__ == "__main__":
    main()