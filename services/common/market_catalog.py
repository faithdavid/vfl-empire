"""Sync MSport default-market-info catalog into Postgres."""

from __future__ import annotations

import json
import logging
from typing import Any

from .db_manager import get_db
from .msport_client import get_default_market_info

logger = logging.getLogger("market_catalog")


def ensure_schema() -> None:
    with get_db() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS market_catalog (
                id BIGSERIAL PRIMARY KEY,
                sport_id TEXT NOT NULL DEFAULT 'vf:sport:1',
                market_group TEXT NOT NULL DEFAULT 'main',
                market_name TEXT NOT NULL,
                market_id TEXT,
                title TEXT,
                outcome_number INTEGER,
                optional_status INTEGER,
                raw_json JSONB,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (sport_id, market_group, market_name, market_id)
            )
            """
        )


def _flatten_catalog(data: dict, sport_id: str = "vf:sport:1") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sections = [
        ("main", data.get("markets") or []),
        ("other_default", data.get("otherDefaultMarkets") or []),
        ("other", data.get("otherMarkets") or []),
    ]
    for group, markets in sections:
        for market in markets:
            mname = market.get("name", "")
            for info in market.get("marketInfos") or []:
                rows.append(
                    {
                        "sport_id": sport_id,
                        "market_group": group,
                        "market_name": mname or info.get("name", ""),
                        "market_id": str(info.get("id", "")),
                        "title": info.get("title"),
                        "outcome_number": info.get("outcomeNumber"),
                        "optional_status": info.get("optionalStatus"),
                        "raw_json": info,
                    }
                )
    return rows


def sync_market_catalog(sport_id: str = "vf:sport:1") -> int:
    """Refresh market_catalog from default-market-info/v2. Safe every pipeline cycle."""
    ensure_schema()
    data = get_default_market_info(sport_id=sport_id, with_others=True)
    if not data:
        logger.warning("default-market-info returned no data")
        return 0

    rows = _flatten_catalog(data, sport_id=sport_id)
    if not rows:
        return 0

    count = 0
    with get_db() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO market_catalog
                (sport_id, market_group, market_name, market_id, title,
                 outcome_number, optional_status, raw_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sport_id, market_group, market_name, market_id)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    outcome_number = EXCLUDED.outcome_number,
                    optional_status = EXCLUDED.optional_status,
                    raw_json = EXCLUDED.raw_json,
                    last_seen_at = now()
                """,
                (
                    row["sport_id"],
                    row["market_group"],
                    row["market_name"],
                    row["market_id"],
                    row.get("title"),
                    row.get("outcome_number"),
                    row.get("optional_status"),
                    json.dumps(row.get("raw_json") or {}),
                ),
            )
            count += 1

    logger.info("market_catalog sync: %d rows for %s", count, sport_id)
    return count