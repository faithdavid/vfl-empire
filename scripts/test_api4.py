#!/usr/bin/env python3
"""Test the msport_api.py implementation directly."""
import sys, json, os
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')
os.environ['MSPORT_DEVICE_ID'] = '260524012204pdid09992064'
from msport_api import get_season_list, get_results

seasons = get_season_list()
print(f"Seasons: {len(seasons) if seasons else 0}")

if seasons:
    # Try newest season that should have results
    for s in seasons[-3:]:
        sid = s.get('seasonId') or s.get('id') or ''
        sname = s.get('seasonName') or s.get('name') or ''
        mds = s.get('matchDay', [])
        print(f"\n{sname} ({sid}): {len(mds)} matchdays")
        # Try first matchday
        if mds:
            results = get_results(sid, mds[0])
            if results:
                print(f"  MD{mds[0]}: {len(results)} results")
                r = results[0]
                print(f"  Keys: {list(r.keys())}")
                print(f"  Sample: {json.dumps(r, indent=2)[:500]}")
                break
            else:
                print(f"  MD{mds[0]}: No results")
