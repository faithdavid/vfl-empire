import sys
import json
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
import msport_api

info = msport_api.get_current_match_day_info()
sid = info.get("seasonId")
results = msport_api.get_results(sid, 21)

print("Results for Season", sid, "Matchday 21:")
for r in results:
    home = r.get("homeTeam")
    away = r.get("awayTeam")
    ft = r.get("fullTime")
    print(f"{home} vs {away} : {ft}")
