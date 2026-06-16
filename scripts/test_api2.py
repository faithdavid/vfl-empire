#!/usr/bin/env python3
"""Quick test of MSport API - focused on result format."""
import sys, json
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire')
from services.common.msport_client import fetch_json, get_season_list, get_results, BASE_URL

# Get season history to check structure
seasons = get_season_list()
print(f"Total seasons: {len(seasons)}")

# Check last few seasons
for s in seasons[-5:]:
    sid = s.get('seasonId') or s.get('id') or ''
    sname = s.get('seasonName') or s.get('name') or ''
    mds = s.get('matchDay', [])
    print(f"  {sname} ({sid}): {len(mds)} matchdays ({min(mds)}-{max(mds)})")

# Test results for a middle season
test_sid = seasons[10]['seasonId']
print(f"\nTesting results for season: {seasons[10]['seasonName']} ({test_sid})")
for md in [1, 2, 5, 10, 15, 30]:
    results = get_results(test_sid, md)
    if results:
        r = results[0]
        print(f"  MD{md}: {len(results)} matches")
        print(f"    Keys: {list(r.keys())}")
        print(f"    Sample: {json.dumps(r, indent=2)[:300]}")
        break
    else:
        print(f"  MD{md}: No results")
