import sys
sys.path.append("/home/ubuntu/faith-workspace/vfl-empire/scripts")
import vfl_live_standing_predictor
import json

patterns = vfl_live_standing_predictor.load_patterns()
live_tiers = vfl_live_standing_predictor.get_live_tiers()

print("Live Tiers Names:", list(live_tiers.keys())[:5])
db_names = set([k[0] for k in patterns.keys()])
print("DB Names:", list(db_names)[:5])

print("Overlap:", set(live_tiers.keys()).intersection(db_names))

import msport_api
events = msport_api.get_event_list()
upcoming_md = msport_api.find_upcoming_match_day(events)
print("Matches in upcoming matchday:")
for match in upcoming_md.get("events", []):
    home = match.get("homeTeamName")
    away = match.get("awayTeamName")
    home_t = live_tiers.get(home)
    away_t = live_tiers.get(away)
    print(f"  {home} ({home_t}) vs {away} ({away_t})")
