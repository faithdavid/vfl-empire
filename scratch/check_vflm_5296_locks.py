import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from msport_api import get_results, _normalise_team_name

season_id = 'vf:season:3097275'
print(f"Checking results for {season_id} (VFLM 5296)")

results = []
for md in range(1, 31):
    res = get_results(season_id, md)
    if res:
        for r in res:
            r['md'] = md
            results.append(r)

for r in results:
    home = _normalise_team_name(r.get('homeTeam',''))
    away = _normalise_team_name(r.get('awayTeam',''))
    score = r.get('fullTime', '')
    
    if home == 'London Guns' and away == 'Everton':
        print(f"Matchday {r.get('md')}: London Guns vs Everton -> Score: {score}")
        
    if home == 'Wolverhampton' and away == 'Newcastle':
        print(f"Matchday {r.get('md')}: Wolverhampton vs Newcastle -> Score: {score}")
