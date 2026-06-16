import sys
sys.path.append("/home/ubuntu/faith-workspace/vfl-empire/scripts")
import msport_api
import json

events = msport_api.get_event_list()
upcoming_md = msport_api.find_upcoming_match_day(events)
matches = upcoming_md.get("events", [])
if matches:
    print(json.dumps(matches[0], indent=2))
