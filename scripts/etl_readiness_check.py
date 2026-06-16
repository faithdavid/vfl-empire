#!/usr/bin/env python3
"""
ETL readiness gate for vfl_empire prematch unification.
Exit 0 + prints READY when backfill is done and live ingest is fresh.
Exit 1 otherwise (for cron retry).
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EMPIRE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMPIRE / "services"))

from common.db_manager import get_db

TARGET_FM_SEASONS = 321
MAX_INGEST_AGE_MIN = 15


def backfill_running() -> bool:
    try:
        out = subprocess.check_output(["pgrep", "-f", "backfill_prematch_odds.py"], text=True)
        return bool(out.strip())
    except subprocess.CalledProcessError:
        return False


def ingest_fresh() -> tuple[bool, str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/ingest/status", timeout=8) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return False, f"ingester unreachable: {e}"
    ts = data.get("last_event_list_ingest") or data.get("last_results_ingest")
    if not ts:
        return False, "no ingest timestamps"
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    age_min = (datetime.now(timezone.utc) - t).total_seconds() / 60
    ok = age_min <= MAX_INGEST_AGE_MIN
    return ok, f"last ingest {age_min:.1f}m ago ({ts})"


def main():
    running = backfill_running()
    with get_db() as cur:
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT season_id) FROM vfl_prematch_odds")
        pm_rows, pm_seasons = cur.fetchone()
        cur.execute("SELECT COUNT(DISTINCT season_id) FROM fixture_markets")
        fm_seasons = cur.fetchone()[0]
        cur.execute("SELECT MAX(captured_at) FROM vfl_prematch_odds")
        pm_max = cur.fetchone()[0]

    fresh, ingest_msg = ingest_fresh()

    print("=== ETL status ===")
    print(f"backfill_prematch_odds running: {running}")
    print(f"vfl_prematch_odds: {pm_rows} rows, {pm_seasons} season_ids, max_captured={pm_max}")
    print(f"fixture_markets distinct seasons: {fm_seasons}")
    print(f"live MSport ingest: {ingest_msg}")

    ready = (
        not running
        and pm_seasons >= TARGET_FM_SEASONS
        and fresh
    )
    if ready:
        print("\nREADY: Prematch ETL complete; live ingest fresh. Safe to treat vfl_prematch_odds as full archive+live.")
        sys.exit(0)

    if running:
        # rough ETA from progress
        pct_note = f"seasons {pm_seasons}/{TARGET_FM_SEASONS} — backfill still running"
        print(f"\nNOT READY: {pct_note}")
    else:
        print("\nNOT READY: backfill stopped but seasons below target or ingest stale")
    sys.exit(1)


if __name__ == "__main__":
    main()