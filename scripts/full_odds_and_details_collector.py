#!/usr/bin/env python3
"""
full_odds_and_details_collector.py
MSport Virtual EPL odds collector:
- Default: always fetches /event/detail per fixture (31+ markets) and upserts DB.
- Fallback: event/list embedded markets only if detail API fails.
- Syncs default-market-info catalog for market metadata.

Usage:
  python3 full_odds_and_details_collector.py --current
  python3 full_odds_and_details_collector.py --loop --interval 60
  python3 full_odds_and_details_collector.py --season vf:season:3098785 --md 6
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

EMPIRE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(EMPIRE_ROOT / "services"))
sys.path.insert(0, str(EMPIRE_ROOT / "scripts"))

try:
    from common.db_manager import get_db
    from common.market_catalog import sync_market_catalog
    from common.msport_client import (
        get_event_detail,
        get_event_list,
        get_match_day_info,
        list_market_count,
        markets_from_payload,
        markets_to_records,
        records_from_event,
        unwrap_event_payload,
    )

    USE_DB_MANAGER = True
except Exception:
    USE_DB_MANAGER = False
    import psycopg2

_LIST_SOURCE = "event_list"
_DETAIL_SOURCE = "event_detail"


def insert_markets(records: list[dict], *, upsert: bool = True) -> int:
    """Write to canonical vfl_prematch_odds (deep pre-match selections)."""
    if not records:
        return 0
    try:
        from common.prematch_odds import upsert_prematch_records
    except ImportError:
        sys.path.insert(0, str(EMPIRE_ROOT / "services"))
        from common.prematch_odds import upsert_prematch_records
    for r in records:
        if "source" not in r or not r["source"]:
            r["source"] = "event_detail"
    return upsert_prematch_records(records)


def insert_details(records: list[dict]) -> int:
    if not records:
        return 0
    inserted = 0
    sql = """
        INSERT INTO fixture_details
        (event_id, season_id, matchday_number, home_team, away_team, details_json, captured_at)
        VALUES (%s,%s,%s,%s,%s,%s, now())
        ON CONFLICT (event_id) DO UPDATE SET
          details_json = EXCLUDED.details_json,
          captured_at = now()
    """
    if USE_DB_MANAGER:
        with get_db() as cur:
            for r in records:
                cur.execute(
                    sql,
                    (
                        r["event_id"],
                        r.get("season_id"),
                        r.get("matchday_number"),
                        r.get("home_team"),
                        r.get("away_team"),
                        json.dumps(r.get("details_json", {})),
                    ),
                )
                inserted += 1
    else:
        conn = psycopg2.connect(
            dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost"
        )
        cur = conn.cursor()
        for r in records:
            cur.execute(
                sql,
                (
                    r["event_id"],
                    r.get("season_id"),
                    r.get("matchday_number"),
                    r.get("home_team"),
                    r.get("away_team"),
                    json.dumps(r.get("details_json", {})),
                ),
            )
            inserted += 1
        conn.commit()
        conn.close()
    return inserted


def collect_fixture(
    ev: dict,
    md: int,
    season_id: str,
    *,
    always_detail: bool = True,
    include_browser: bool = False,
) -> tuple[list[dict], dict | None, str]:
    """Return (market_records, detail_record, source_label)."""
    eid = ev.get("eventId")
    if not eid:
        return [], None, "skip"

    base = {
        "event_id": eid,
        "season_id": ev.get("seasonId", season_id),
        "matchday_number": md,
        "home_team": ev.get("homeTeam"),
        "away_team": ev.get("awayTeam"),
    }

    source = _DETAIL_SOURCE
    payload: dict = {}
    market_records: list[dict] = []

    if always_detail:
        det = get_event_detail(eid)
        if det:
            payload = unwrap_event_payload(det)
            market_records = markets_to_records(
                markets_from_payload(det),
                event_id=eid,
                season_id=base["season_id"],
                matchday_number=md,
                home_team=base["home_team"],
                away_team=base["away_team"],
                source=_DETAIL_SOURCE,
            )

    if not market_records:
        payload = unwrap_event_payload(ev)
        market_records = records_from_event(
            ev, season_id=season_id, matchday_number=md, source=_LIST_SOURCE
        )
        source = _LIST_SOURCE

    detail_record = {**base, "details_json": payload}

    if include_browser:
        try:
            from playwright.sync_api import sync_playwright

            from common.msport_client import DEFAULT_HEADERS

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
                page = browser.new_context(
                    user_agent=DEFAULT_HEADERS["User-Agent"]
                ).new_page()
                slug = str(eid).replace("vf:match:", "")
                page.goto(
                    f"https://www.msport.com/ng/web/virtual/details/{slug}",
                    wait_until="domcontentloaded",
                    timeout=25000,
                )
                time.sleep(2)
                txt = page.inner_text("body")
                detail_record["details_json"]["browser_panel"] = {
                    "raw_sample": txt[:2000],
                    "keywords": [
                        line.strip()[:120]
                        for line in txt.splitlines()
                        if any(
                            k in line.lower()
                            for k in [
                                "previous",
                                "form",
                                "last",
                                "h2h",
                                "stats",
                                "rank",
                                "goals",
                            ]
                        )
                    ],
                }
                browser.close()
        except Exception as ex:
            detail_record["details_json"]["browser_error"] = str(ex)

    return market_records, detail_record, source


def collect_for_md(
    season_id: str,
    md: int,
    *,
    always_detail: bool = True,
    include_browser: bool = False,
):
    print(f"\n=== Collecting odds for season={season_id} MD={md} ===")
    elist = get_event_list()
    if not elist:
        print("No event list")
        return 0, 0

    target_events = []
    for m in elist:
        if m.get("matchDay") == md:
            target_events = m.get("events", [])
            break

    print(f"Found {len(target_events)} fixtures for MD {md}")
    return _collect_events(
        target_events,
        md,
        season_id,
        always_detail=always_detail,
        include_browser=include_browser,
    )


def _collect_events(
    events: list[dict],
    md: int,
    season_id: str,
    *,
    always_detail: bool = True,
    include_browser: bool = False,
) -> tuple[int, int]:
    market_records: list[dict] = []
    detail_records: list[dict] = []
    list_only = 0
    detail_fetches = 0

    for ev in events:
        mkts, detail, source = collect_fixture(
            ev,
            md,
            season_id,
            always_detail=always_detail,
            include_browser=include_browser,
        )
        market_records.extend(mkts)
        if detail:
            detail_records.append(detail)
        if source == _DETAIL_SOURCE:
            detail_fetches += 1
        else:
            list_only += 1
        time.sleep(0.15)

    m_ins = insert_markets(market_records)
    d_ins = insert_details(detail_records)
    print(
        f"  {list_only} list-only, {detail_fetches} detail fetches → "
        f"{m_ins} market upserts ({len(market_records)} parsed), {d_ins} details"
    )
    return m_ins, d_ins


def collect_current(
    *,
    always_detail: bool = True,
    sync_catalog: bool = True,
    include_browser: bool = False,
):
    """Collect full event/detail for all matchdays in the current event list."""
    if sync_catalog:
        try:
            n = sync_market_catalog()
            print(f"Market catalog: {n} rows synced")
        except Exception as ex:
            print(f"Market catalog sync failed: {ex}")

    info = get_match_day_info()
    if not info:
        print("No current info")
        return 0, 0

    season_id = info.get("seasonId")
    cur_md = info.get("matchDay")
    season_name = info.get("seasonName")
    status = info.get("status")
    print(f"Current: {season_name} ({season_id}) MD {cur_md} status={status}")

    elist = get_event_list()
    if not elist:
        print("No event list")
        return 0, 0

    total_markets = 0
    total_details = 0
    for m in elist:
        md = m.get("matchDay")
        events = m.get("events", [])
        embedded = sum(list_market_count(ev) for ev in events)
        print(f"MD {md}: {len(events)} fixtures, {embedded} list-embedded markets")
        m_ins, d_ins = _collect_events(
            events,
            md,
            season_id,
            always_detail=always_detail,
            include_browser=include_browser,
        )
        total_markets += m_ins
        total_details += d_ins

    mode = "full detail" if always_detail else "list-only"
    print(f"\nTotal this run ({mode}): {total_markets} market upserts, {total_details} details")
    return total_markets, total_details


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", action="store_true")
    ap.add_argument("--season", help="Specific seasonId e.g. vf:season:3098785")
    ap.add_argument("--md", type=int, help="Specific matchday")
    ap.add_argument("--backfill-last", type=int, default=0)
    ap.add_argument(
        "--list-only",
        action="store_true",
        help="Skip event/detail; use event/list embedded markets only (not recommended)",
    )
    ap.add_argument("--no-catalog-sync", action="store_true")
    ap.add_argument("--include-browser-details", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()

    always_detail = not args.list_only

    def run_once():
        kwargs = {
            "always_detail": always_detail,
            "sync_catalog": not args.no_catalog_sync,
            "include_browser": args.include_browser_details,
        }
        if args.season and args.md:
            collect_for_md(
                args.season,
                args.md,
                always_detail=always_detail,
                include_browser=args.include_browser_details,
            )
        elif args.backfill_last > 0:
            info = get_match_day_info()
            if info:
                sid = info["seasonId"]
                cur_md = info["matchDay"]
                for md in range(max(1, cur_md - args.backfill_last), cur_md + 1):
                    collect_for_md(
                        sid,
                        md,
                        always_detail=always_detail,
                        include_browser=args.include_browser_details,
                    )
                    time.sleep(1)
        else:
            collect_current(**kwargs)

    if args.loop:
        while True:
            run_once()
            time.sleep(args.interval)
    else:
        run_once()


if __name__ == "__main__":
    main()