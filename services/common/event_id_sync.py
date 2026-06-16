"""Sync MSport vf:match event IDs into fixture_event_map and backfill results."""

from __future__ import annotations

import logging
import re
from typing import Any

from .db_manager import get_db
from .msport_client import _normalise_team_name, get_event_list, get_match_day_info

logger = logging.getLogger("event_id_sync")

REAL_MSPORT_RE = re.compile(r"^vf:match:\d+$")
SYNTHETIC_RE = re.compile(r"^vf:(season|match:season):")


def _resolve_event_id(event: dict) -> str | None:
    eid = event.get("eventId") or event.get("id")
    if eid and REAL_MSPORT_RE.match(str(eid)):
        return str(eid)
    return None


def upsert_fixture_event_map(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    count = 0
    with get_db() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO fixture_event_map
                (season_id, season_name, matchday_number, home_team, away_team, event_id, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (season_id, matchday_number, home_team, away_team)
                DO UPDATE SET
                    event_id = EXCLUDED.event_id,
                    season_name = COALESCE(EXCLUDED.season_name, fixture_event_map.season_name),
                    source = EXCLUDED.source,
                    last_seen_at = now()
                """,
                (
                    row["season_id"],
                    row.get("season_name"),
                    row["matchday_number"],
                    row["home_team"],
                    row["away_team"],
                    row["event_id"],
                    row.get("source", "event_list"),
                ),
            )
            count += 1
    return count


def collect_from_event_list() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    matchdays = get_event_list() or []
    for md_group in matchdays:
        season_id = md_group.get("seasonId")
        season_name = md_group.get("seasonName")
        md_num = md_group.get("matchDay")
        if not season_id or not md_num:
            continue
        for ev in md_group.get("events") or []:
            eid = _resolve_event_id(ev)
            if not eid:
                continue
            rows.append(
                {
                    "season_id": str(season_id),
                    "season_name": season_name,
                    "matchday_number": int(md_num),
                    "home_team": _normalise_team_name(ev.get("homeTeam", "")),
                    "away_team": _normalise_team_name(ev.get("awayTeam", "")),
                    "event_id": eid,
                    "source": "event_list",
                }
            )
    return rows


def lookup_event_id(
    season_id: str,
    matchday_number: int,
    home_team: str,
    away_team: str,
) -> str | None:
    home = _normalise_team_name(home_team)
    away = _normalise_team_name(away_team)
    with get_db() as cur:
        cur.execute(
            """
            SELECT event_id FROM fixture_event_map
            WHERE season_id = %s AND matchday_number = %s
              AND home_team = %s AND away_team = %s
            LIMIT 1
            """,
            (season_id, matchday_number, home, away),
        )
        row = cur.fetchone()
        return row[0] if row else None


def backfill_results_from_map(limit: int | None = None) -> int:
    """Upgrade synthetic/missing vfl_results_v2.event_id using fixture_event_map."""
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    updated = 0
    with get_db() as cur:
        cur.execute(
            f"""
            SELECT r.id, s.season_id, md.matchday_number, r.home_team, r.away_team, r.event_id
            FROM vfl_results_v2 r
            JOIN vfl_matchdays md ON md.id = r.matchday_id
            JOIN vfl_seasons s ON s.id = md.season_id
            WHERE r.event_id IS NULL
               OR r.event_id LIKE 'vf:season:%'
               OR r.event_id LIKE 'vf:match:season:%'
            {limit_sql}
            """
        )
        candidates = cur.fetchall()
        for rid, season_id, md_num, home, away, current_eid in candidates:
            if current_eid and REAL_MSPORT_RE.match(str(current_eid)):
                continue
            cur.execute(
                """
                SELECT event_id FROM fixture_event_map
                WHERE season_id = %s AND matchday_number = %s
                  AND home_team = %s AND away_team = %s
                LIMIT 1
                """,
                (season_id, md_num, home, away),
            )
            found = cur.fetchone()
            if not found:
                continue
            new_eid = found[0]
            cur.execute(
                """
                UPDATE vfl_results_v2 SET event_id = %s
                WHERE id = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM vfl_results_v2 x
                    WHERE x.event_id = %s AND x.id <> %s
                  )
                """,
                (new_eid, rid, new_eid, rid),
            )
            if cur.rowcount:
                updated += 1
    return updated


def sync_event_ids() -> dict[str, int]:
    """Poll live APIs, refresh map, backfill results. Safe to run every pipeline cycle."""
    ensure_schema()
    rows = collect_from_event_list()
    mapped = upsert_fixture_event_map(rows)
    backfilled = backfill_results_from_map()
    info = get_match_day_info() or {}
    logger.info(
        "event_id_sync: season=%s md=%s mapped=%d backfilled=%d",
        info.get("seasonName"),
        info.get("matchDay"),
        mapped,
        backfilled,
    )
    return {"mapped": mapped, "backfilled": backfilled}


def ensure_schema() -> None:
    with get_db() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fixture_event_map (
                id BIGSERIAL PRIMARY KEY,
                season_id TEXT NOT NULL,
                season_name TEXT,
                matchday_number INTEGER NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                event_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'event_list',
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (season_id, matchday_number, home_team, away_team)
            )
            """
        )