#!/usr/bin/env python3
"""
VFL Data Pipeline Daemon (modular, high-frequency capable)
Supports --live-only for tight live loops (every 30-60s).
Supports --loop for continuous runs.
Integrates odds/details + results comber + settlement awareness.
All inserts are deduplicated via DB constraints.
"""

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

EMPIRE_ROOT = Path(__file__).parent.parent
LOG_DIR = EMPIRE_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "data_pipeline.log"

sys.path.insert(0, str(EMPIRE_ROOT / "scripts"))
sys.path.insert(0, str(EMPIRE_ROOT / "services"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DATA-DAEMON] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)]
)
log = logging.getLogger("data-pipeline")

try:
    from full_odds_and_details_collector import collect_current as collect_odds
except Exception:
    collect_odds = None

try:
    sys.path.insert(0, str(EMPIRE_ROOT / "services"))
    from common.event_id_sync import sync_event_ids
except Exception:
    sync_event_ids = None

try:
    from common.market_catalog import sync_market_catalog
except Exception:
    sync_market_catalog = None

try:
    from common.msport_client import get_match_day_info
except Exception:
    get_match_day_info = None

try:
    from results_page_comber import comb_results
except Exception:
    comb_results = None

try:
    from msport_settlement_mirror import main as settlement_main
except Exception:
    settlement_main = None

running = True

def handle_signal(signum, frame):
    global running
    log.info("Shutting down...")
    running = False

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

def run_live_loop(interval: int = 30):
    """High-frequency live data loop (for current MD, odds, quick updates)."""
    log.info(f"Starting LIVE loop every {interval}s (no lapses on fast 4-min MDs)")
    last_odds = 0
    last_catalog = 0
    catalog_interval = max(3600, interval * 20)
    while running:
        now = time.time()
        if now - last_odds >= interval:
            if get_match_day_info:
                try:
                    info = get_match_day_info() or {}
                    log.info(
                        "Match day: %s MD%s status=%s",
                        info.get("seasonName"),
                        info.get("matchDay"),
                        info.get("status"),
                    )
                except Exception as e:
                    log.debug(f"match day info: {e}")
            if sync_event_ids:
                try:
                    stats = sync_event_ids()
                    log.info(
                        "Event ID sync: mapped=%s backfilled=%s",
                        stats.get("mapped"),
                        stats.get("backfilled"),
                    )
                except Exception as e:
                    log.error(f"Event ID sync error: {e}")
            if sync_market_catalog and now - last_catalog >= catalog_interval:
                try:
                    n = sync_market_catalog()
                    log.info("Market catalog sync: %s rows", n)
                    last_catalog = now
                except Exception as e:
                    log.error(f"Market catalog error: {e}")
            if collect_odds:
                try:
                    log.info("Collecting full event/detail + upserting markets...")
                    collect_odds(sync_catalog=False, always_detail=True)
                except Exception as e:
                    log.error(f"Odds collection error: {e}")
            last_odds = now

        # Light settlement check if available
        if settlement_main and (now % 120 < interval):  # occasional
            try:
                # settlement_main may expect args; run in non-blocking friendly way if possible
                pass  # integrate if it supports --once style
            except Exception:
                pass

        time.sleep(min(5, interval // 3))  # responsive sleep

def run_full_loop(base_interval: int = 60):
    """General loop for odds + periodic comber."""
    log.info(f"Starting full data loop (odds ~{base_interval}s, comber less frequent)")
    last_odds = 0
    last_comber = 0
    comber_interval = 180  # ~3 min for small combs

    while running:
        now = time.time()

        if now - last_odds >= base_interval:
            if sync_event_ids:
                try:
                    sync_event_ids()
                except Exception as e:
                    log.error(f"Event ID sync error: {e}")
            if collect_odds:
                try:
                    collect_odds(sync_catalog=False, always_detail=True)
                    last_odds = now
                except Exception as e:
                    log.error(f"Odds error: {e}")

        if now - last_comber >= comber_interval:
            if comb_results:
                try:
                    log.info("Running small results comber pass (anti-lapse)...")
                    comb_results(steps=8, dry_run=False, resume=True)
                    last_comber = now
                except Exception as e:
                    log.error(f"Comber error: {e}")

        time.sleep(5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--live-only", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.live_only:
        run_live_loop(args.interval)
    else:
        if args.once:
            if collect_odds: collect_odds()
            if comb_results: comb_results(steps=5, dry_run=False, resume=True)
        else:
            run_full_loop(args.interval)
