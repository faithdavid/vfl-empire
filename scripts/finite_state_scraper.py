#!/usr/bin/env python3
"""
Phase 1: Finite State Space Scraper
====================================
Scrapes ALL available seasons from the MSport Results API and stores
match-level data for finite state space analysis.

Usage:
    python3 scripts/finite_state_scraper.py

Output:
    /home/ubuntu/faith-workspace/vfl-complete-data/data/finite_state_space.json
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

# Ensure we can import from vfl-empire
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire')
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')

# Import the API client that actually works
os.environ['MSPORT_DEVICE_ID'] = '260524012204pdid09992064'
from msport_api import get_season_list, get_results

RATE_LIMIT_SLEEP = 0.15  # seconds between API calls
OUTPUT_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/data/finite_state_space.json'
MAX_SEASONS = None  # Set to int to limit (None = all)
MAX_MATCHDAYS = 30  # Maximum matchdays to scrape per season


def scrape_all():
    """Main scraping orchestrator."""
    start_time = time.time()
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting Finite State Space scraper...")

    # 1. Fetch season list
    print("Fetching season list...")
    seasons_raw = get_season_list()
    if not seasons_raw:
        print("ERROR: No seasons returned from API!")
        return False

    print(f"Received {len(seasons_raw)} seasons from API")

    # Sort by season name to ensure consistency (VFLM NNNN)
    seasons_raw.sort(key=lambda s: int(s.get('seasonName', '0').replace('VFLM ', '').replace('VFL ', '0')))

    if MAX_SEASONS:
        seasons_raw = seasons_raw[:MAX_SEASONS]

    # 2. Structure the output
    output = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "total_seasons": len(seasons_raw),
            "source": "MSport API (result/season/selection + result endpoints)"
        },
        "seasons": []
    }

    total_matches = 0
    total_api_calls = 0
    seasons_with_results = 0

    for s_idx, s in enumerate(seasons_raw):
        season_id = s.get('seasonId', '')
        season_name = s.get('seasonName', 'unknown')
        matchdays_available = sorted(s.get('matchDay', []))

        if not season_id:
            print(f"  Skipping season {s_idx}: no seasonId")
            continue

        # Only process matchdays 1-30
        mds_to_scrape = [md for md in matchdays_available if 1 <= md <= MAX_MATCHDAYS]

        season_data = {
            "season_id": season_id,
            "season_name": season_name,
            "matchdays": {}
        }

        season_match_count = 0

        for md in mds_to_scrape:
            if total_api_calls > 0 and total_api_calls % 30 == 0:
                elapsed = time.time() - start_time
                print(f"  Progress: {total_api_calls} API calls, {total_matches} matches, {elapsed:.0f}s elapsed")

            # Rate limit
            time.sleep(RATE_LIMIT_SLEEP)
            total_api_calls += 1

            try:
                results = get_results(season_id, md)
            except Exception as e:
                print(f"  ERROR: {season_name} MD{md}: {e}")
                continue

            if not results:
                continue

            # Parse each match result
            parsed_matches = []
            for r in results:
                if not isinstance(r, dict):
                    continue
                home = r.get('homeTeam', '').strip()
                away = r.get('awayTeam', '').strip()
                ft = r.get('fullTime', '')
                ht = r.get('halfTime', '')
                fg = r.get('firstGoal', '')

                if not home or not away or not ft:
                    continue

                parsed_matches.append({
                    "homeTeam": home,
                    "awayTeam": away,
                    "fullTime": ft,
                    "halfTime": ht,
                    "firstGoal": fg
                })

            if parsed_matches:
                season_data["matchdays"][str(md)] = parsed_matches
                season_match_count += len(parsed_matches)
                total_matches += len(parsed_matches)

        if season_match_count > 0:
            seasons_with_results += 1

        output["seasons"].append(season_data)

        if (s_idx + 1) % 5 == 0:
            print(f"  Season {s_idx+1}/{len(seasons_raw)}: {season_name} - {season_match_count} matches so far")

    # 3. Update metadata
    output["metadata"]["total_matches"] = total_matches
    output["metadata"]["total_api_calls"] = total_api_calls
    output["metadata"]["seasons_with_results"] = seasons_with_results
    output["metadata"]["elapsed_seconds"] = round(time.time() - start_time, 1)

    # 4. Write output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"  Seasons processed: {len(seasons_raw)}")
    print(f"  Seasons with results: {seasons_with_results}")
    print(f"  Total API calls: {total_api_calls}")
    print(f"  Total matches captured: {total_matches}")
    print(f"  Elapsed: {output['metadata']['elapsed_seconds']}s")
    print(f"  Output: {OUTPUT_PATH}")
    print(f"{'='*60}")

    return True


if __name__ == '__main__':
    success = scrape_all()
    sys.exit(0 if success else 1)
