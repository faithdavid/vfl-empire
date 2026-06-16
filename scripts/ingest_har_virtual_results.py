#!/usr/bin/env python3
"""
Parse MSport virtual/result HAR JSON into vfl_results_v2 (silver).

Data-prep alignment (exploration / DS / ML):
  - Fixed grain: one row per (season, matchday, home_team, away_team)
  - Validity: scored fixtures only; fullTime must parse as H:A
  - Uniqueness: ON CONFLICT (matchday_id, home_team, away_team) DO NOTHING
  - Lineage: event_id prefix github_har_result: + source tag in migration log
  - Consistency: team names trimmed; season via vf:season: + VFLM name from payload

Does not overwrite existing silver rows (live MSport wins on conflict).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

EMPIRE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMPIRE / "services"))

from common.db_manager import get_db

log = logging.getLogger("ingest_har_results")

SCORE_RE = re.compile(r"^(\d+)\s*:\s*(\d+)$")
VFLM_RE = re.compile(r"VFLM\s*(\d+)", re.I)


def normalise_team(name: str) -> str:
    return (name or "").strip()


def parse_score(full_time: str) -> tuple[int, int] | None:
    if not full_time:
        return None
    m = SCORE_RE.match(str(full_time).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def season_meta_from_url(url: str) -> dict:
    out = {}
    try:
        q = parse_qs(urlparse(url).query)
        if "seasonId" in q:
            out["season_id"] = q["seasonId"][0]
        if "matchDay" in q:
            out["matchday"] = int(q["matchDay"][0])
    except (ValueError, IndexError, TypeError):
        pass
    return out


def resolve_season(cur, season_id: str | None, season_name: str | None) -> int | None:
    """Mirror migrate_history_matches_to_pg.resolve_season."""
    for sk in filter(None, [season_id, season_name]):
        sk = str(sk).strip()
        cur.execute(
            "SELECT id FROM vfl_seasons WHERE season_id = %s OR season_name = %s LIMIT 1",
            (sk, sk),
        )
        row = cur.fetchone()
        if row:
            return row["id"] if isinstance(row, dict) else row[0]
    if season_name:
        m = VFLM_RE.search(season_name)
        if m:
            name = f"VFLM {m.group(1)}"
            cur.execute("SELECT id FROM vfl_seasons WHERE season_name = %s LIMIT 1", (name,))
            row = cur.fetchone()
            if row:
                return row["id"] if isinstance(row, dict) else row[0]
    sid_text = season_id or (f"legacy:{season_name}" if season_name else None)
    if not sid_text:
        return None
    sname = season_name or sid_text
    if VFLM_RE.search(sname or ""):
        sname = f"VFLM {VFLM_RE.search(sname).group(1)}"
    cur.execute(
        """
        INSERT INTO vfl_seasons (season_id, season_name)
        VALUES (%s, %s)
        ON CONFLICT (season_id) DO UPDATE SET season_name = EXCLUDED.season_name
        RETURNING id
        """,
        (sid_text, sname),
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


def contexts_from_body(body: dict, url_meta: dict) -> list[dict]:
    """Each context = seasonId + matchDay + results list."""
    if not isinstance(body, dict):
        return []
    data = body.get("data") or {}
    if not isinstance(data, dict):
        return []
    out: list[dict] = []

    def ctx_from_block(block: dict | None, results: list) -> dict | None:
        if not block or not isinstance(block, dict):
            return None
        sid = block.get("seasonId") or url_meta.get("season_id")
        md = block.get("matchDay") or url_meta.get("matchday")
        sname = block.get("seasonName")
        if sid is None or md is None:
            return None
        return {"season_id": sid, "matchday": int(md), "season_name": sname, "results": results}

    results = data.get("results") or []
    if results:
        for key in ("current", "prev", "after"):
            block = data.get(key)
            c = ctx_from_block(block, results)
            if c:
                out.append(c)
        if not out and url_meta.get("season_id") and url_meta.get("matchday"):
            out.append(
                {
                    "season_id": url_meta["season_id"],
                    "matchday": url_meta["matchday"],
                    "season_name": None,
                    "results": results,
                }
            )
    return out


def iter_har_result_items(path: Path):
    items = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(items, list):
        return
    for item in items:
        yield item


def ingest_result_json(path: Path, *, dry_run: bool) -> dict:
    stats = {
        "har_bodies": 0,
        "contexts": 0,
        "fixtures_parsed": 0,
        "invalid_score": 0,
        "inserted": 0,
        "duplicate": 0,
        "skipped_no_season": 0,
    }
    if not path.exists():
        log.warning("Missing %s", path)
        return stats

    # Dedupe in-memory same fixture from repeated HAR snapshots
    seen: set[tuple] = set()

    with get_db() as pg:
        for item in iter_har_result_items(path):
            body = item.get("body") or {}
            url = item.get("url") or ""
            url_meta = season_meta_from_url(url)
            stats["har_bodies"] += 1
            for ctx in contexts_from_body(body, url_meta):
                stats["contexts"] += 1
                sid_text = ctx["season_id"]
                md = ctx["matchday"]
                sname = ctx.get("season_name")
                if dry_run:
                    db_sid = 1
                else:
                    db_sid = resolve_season(pg, sid_text, sname)
                if db_sid is None:
                    stats["skipped_no_season"] += len(ctx["results"])
                    continue
                if not dry_run:
                    md_id = ensure_matchday(pg, db_sid, md)
                for r in ctx["results"]:
                    home = normalise_team(r.get("homeTeam"))
                    away = normalise_team(r.get("awayTeam"))
                    if not home or not away:
                        continue
                    score = parse_score(r.get("fullTime") or r.get("scoreOfWholeMatch"))
                    if score is None:
                        stats["invalid_score"] += 1
                        continue
                    hg, ag = score
                    key = (sid_text, md, home, away)
                    if key in seen:
                        stats["duplicate"] += 1
                        continue
                    seen.add(key)
                    stats["fixtures_parsed"] += 1
                    if dry_run:
                        stats["inserted"] += 1
                        continue
                    event_id = f"github_har_result:{sid_text}:{md}:{home}:{away}"
                    pg.execute(
                        """
                        INSERT INTO vfl_results_v2 (matchday_id, event_id, home_team, away_team, home_goals, away_goals)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (matchday_id, home_team, away_team) DO NOTHING
                        """,
                        (md_id, event_id, home, away, hg, ag),
                    )
                    if pg.rowcount:
                        stats["inserted"] += 1
                    else:
                        stats["duplicate"] += 1

    return stats


HARNESS = EMPIRE / "scratch" / "github_harness"


def vflm_coverage_github_har() -> dict:
    with get_db() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM vfl_results_v2
            WHERE event_id LIKE 'github_har_result:%'
            """
        )
        r = cur.fetchone()
        n = r["c"] if isinstance(r, dict) else r[0]
        cur.execute(
            """
            SELECT MIN(s.season_name), MAX(s.season_name), COUNT(DISTINCT s.id)
            FROM vfl_results_v2 v
            JOIN vfl_matchdays md ON md.id = v.matchday_id
            JOIN vfl_seasons s ON s.id = md.season_id
            WHERE v.event_id LIKE 'github_har_result:%%'
              AND s.season_name ~ '^VFLM'
            """
        )
        row = cur.fetchone()
        if isinstance(row, dict):
            vmin, vmax, seasons = row.get("min"), row.get("max"), row.get("count")
        else:
            vmin, vmax, seasons = row[0], row[1], row[2]
    return {"github_har_result_rows": n, "vflm_min": vmin, "vflm_max": vmax, "seasons": seasons}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--path",
        type=Path,
        default=HARNESS / "extracted_har" / "result.json",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    before = vflm_coverage_github_har()
    log.info("Before github_har_result rows: %s", before)

    stats = ingest_result_json(args.path, dry_run=args.dry_run)
    log.info("Ingest stats: %s", stats)

    if not args.dry_run:
        after = vflm_coverage_github_har()
        log.info("After github_har_result: %s", after)


if __name__ == "__main__":
    main()