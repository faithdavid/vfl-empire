#!/usr/bin/env python3
"""Quick test of MSport API."""
import sys
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire')
from services.common.msport_client import fetch_json, get_season_list, get_results, BASE_URL
import json

# Test season list
seasons = get_season_list()
print(f"Seasons returned: {type(seasons).__name__}")
if seasons:
    print(f"Count: {len(seasons)}")
    print(f"First item: {json.dumps(seasons[0], indent=2)[:500]}")
    print(f"Last item: {json.dumps(seasons[-1], indent=2)[:500]}")
    
    # Test results for first season, MD 1
    first_season = seasons[0]
    sid = first_season.get('seasonId') or first_season.get('id') or first_season.get('season_id') or ''
    sname = first_season.get('seasonName') or first_season.get('name') or first_season.get('season_name') or ''
    print(f"\nFirst season: id={sid}, name={sname}")
    
    if sid:
        results = get_results(sid, 1)
        print(f"\nResults for {sid} MD1: {type(results).__name__}")
        if results:
            print(f"Count: {len(results)}")
            print(f"First result keys: {list(results[0].keys()) if isinstance(results[0], dict) else 'not dict'}")
            print(f"First result: {json.dumps(results[0], indent=2)[:800]}")
else:
    print("No seasons returned - check connection")
