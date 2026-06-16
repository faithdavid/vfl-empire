#!/usr/bin/env python3
"""Quick test - try oldest and newest seasons."""
import sys, json
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire')
from services.common.msport_client import fetch_json, get_season_list, get_results, BASE_URL

seasons = get_season_list()
print(f"Total seasons: {len(seasons)}")

# Try first (oldest), middle, and last (newest)
for idx in [0, 19, -1]:
    s = seasons[idx]
    sid = s['seasonId']
    sname = s['seasonName']
    print(f"\n--- Season {idx}: {sname} ({sid}) ---")
    for md in [1, 10, 20, 30]:
        results = get_results(sid, md)
        if results and len(results) > 0:
            print(f"  MD{md}: {len(results)} matches")
            if md == 1:
                for i, r in enumerate(results[:2]):
                    print(f"    Match {i}: {json.dumps(r, indent=2)[:400]}")
        else:
            print(f"  MD{md}: No results/empty")
