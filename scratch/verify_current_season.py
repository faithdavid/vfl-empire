import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
import msport_api
import json
import pandas as pd
import numpy as np

with open('/home/ubuntu/faith-workspace/vfl-empire/data/phase_fixture_locks_bulletproof.json', 'r') as f:
    locks_list = json.load(f)
locks_db = { (str(l['home']), str(l['away']), str(l['home_tier']), str(l['away_tier']), int(l['phase'])): l['lock'] for l in locks_list }

seasons = msport_api.get_season_list()
if not seasons:
    print("Failed to fetch seasons")
    sys.exit(1)

# Check the last 3 seasons available in the API
for season_info in seasons[:3]:
    sid = season_info['seasonId']
    print(f"\n--- Checking Season: {sid} ---")
    
    found_any = False
    for md in range(3, 31):
        try:
            standings_raw = msport_api.get_standings(sid, md-2)
            if not standings_raw: continue
            
            table = msport_api.extract_standings_table(standings_raw)
            if not table: continue
            
            sorted_table = sorted(table, key=lambda x: (x['points'], x['goalDifference'], x['goalsFor']), reverse=True)
            tiers = {}
            for i, t in enumerate(sorted_table):
                if i < 4: tiers[t['teamName']] = 'T1'
                elif i < 8: tiers[t['teamName']] = 'T2'
                elif i < 12: tiers[t['teamName']] = 'T3'
                else: tiers[t['teamName']] = 'T4'
                
            events = msport_api.get_results(sid, md)
            if not events: continue
            
            phase = int(np.ceil(md / 2.0))
            
            for event in events:
                home = msport_api._normalise_team_name(event.get('homeTeamName', ''))
                away = msport_api._normalise_team_name(event.get('awayTeamName', ''))
                
                h_tier = tiers.get(home)
                a_tier = tiers.get(away)
                
                key = (home, away, h_tier, a_tier, phase)
                if key in locks_db:
                    ft = event.get('fullTime', '0:0').split(':')
                    hg, ag = int(ft[0]), int(ft[1])
                    if hg > ag: actual = 'hw'
                    elif hg == ag: actual = 'dr'
                    else: actual = 'aw'
                    
                    status = "✅ WON" if actual == locks_db[key] else "❌ LOST"
                    print(f"FOUND LOCK! MD {md}: {home} vs {away} | Pick: {locks_db[key]} | Score: {hg}-{ag} | {status}")
                    found_any = True
        except Exception as e:
            continue
            
    if not found_any:
        print(f"No locks found in season {sid}")
