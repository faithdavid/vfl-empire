import msport_api
import json

def fetch_md_16_results():
    info = msport_api.get_current_match_day_info()
    if not info:
        return "Failed to get current info"
    
    season_id = info.get("seasonId")
    # We want MD 16
    results = msport_api.get_results(season_id, 16)
    return results

if __name__ == "__main__":
    results = fetch_md_16_results()
    print(json.dumps(results, indent=2))
