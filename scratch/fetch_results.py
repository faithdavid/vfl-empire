import sys
import json
import os

# Add scripts to path
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
import msport_api

def fetch_results(start_md, end_md):
    info = msport_api.get_current_match_day_info()
    if not info:
        return "Failed to get current info"
    
    season_id = info.get("seasonId")
    all_results = {}
    for md in range(start_md, end_md + 1):
        results = msport_api.get_results(season_id, md)
        all_results[md] = results
    return all_results

if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 22
    results = fetch_results(start, end)
    print(json.dumps(results, indent=2))
