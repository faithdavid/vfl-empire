"""Canonical pre-match odds store — one row per market selection per fixture."""
from __future__ import annotations

import logging
from typing import Any

from .db_manager import get_db

logger = logging.getLogger("prematch_odds")

UPSERT_SQL = """
INSERT INTO vfl_prematch_odds
(event_id, season_id, matchday_number, home_team, away_team,
 market_name, specifiers, selection_name, odds, source, captured_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, COALESCE(%s::timestamptz, now()))
ON CONFLICT (event_id, market_name, specifiers, selection_name) DO UPDATE SET
  odds = EXCLUDED.odds,
  captured_at = EXCLUDED.captured_at,
  source = EXCLUDED.source,
  season_id = COALESCE(EXCLUDED.season_id, vfl_prematch_odds.season_id),
  matchday_number = COALESCE(EXCLUDED.matchday_number, vfl_prematch_odds.matchday_number),
  home_team = COALESCE(EXCLUDED.home_team, vfl_prematch_odds.home_team),
  away_team = COALESCE(EXCLUDED.away_team, vfl_prematch_odds.away_team)
"""


def _row_params(r: dict[str, Any], captured_at=None) -> tuple:
    return (
        str(r["event_id"]),
        r.get("season_id"),
        r.get("matchday_number"),
        r.get("home_team"),
        r.get("away_team"),
        r["market_name"],
        r.get("specifiers") or "",
        r["selection_name"],
        r.get("odds"),
        r.get("source") or "api",
        captured_at,
    )


def upsert_prematch_records(records: list[dict], *, captured_at=None, batch_size: int = 500) -> int:
    """Upsert market selection rows into vfl_prematch_odds. Returns rows touched."""
    if not records:
        return 0
    affected = 0
    with get_db() as cur:
        batch: list[tuple] = []
        for r in records:
            if not r.get("event_id") or not r.get("market_name") or not r.get("selection_name"):
                continue
            batch.append(_row_params(r, captured_at))
            if len(batch) >= batch_size:
                for p in batch:
                    cur.execute(UPSERT_SQL, p)
                    affected += cur.rowcount or 0
                batch.clear()
        for p in batch:
            cur.execute(UPSERT_SQL, p)
            affected += cur.rowcount or 0
    return affected


def vfl_odds_v2_to_records(
    event_id: str,
    season_id: str | None,
    matchday_number: int | None,
    home_team: str | None,
    away_team: str | None,
    o15=None,
    o25=None,
    u25=None,
    u35=None,
    gg=None,
    ng=None,
) -> list[dict]:
    """Expand legacy vfl_odds_v2 columns into selection-level records."""
    out: list[dict] = []
    base = {
        "event_id": event_id,
        "season_id": season_id,
        "matchday_number": matchday_number,
        "home_team": home_team,
        "away_team": away_team,
        "source": "vfl_odds_v2_backfill",
    }

    def add(market_name: str, specifiers: str, selection_name: str, odds):
        if odds is None:
            return
        out.append(
            {
                **base,
                "market_name": market_name,
                "specifiers": specifiers,
                "selection_name": selection_name,
                "odds": float(odds),
            }
        )

    add("Over/Under", "total=1.5", "Over", o15)
    add("Over/Under", "total=2.5", "Over", o25)
    add("Over/Under", "total=2.5", "Under", u25)
    add("Over/Under", "total=3.5", "Under", u35)
    add("GG/NG", "", "Yes", gg)
    add("GG/NG", "", "No", ng)
    return out