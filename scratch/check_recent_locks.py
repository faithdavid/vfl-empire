import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from msport_api import get_results, _normalise_team_name

seasons = ['vf:season:3097274', 'vf:season:3097275', 'vf:season:3097276'] # 5295, 5296, 5297

for season_id in seasons:
    print(f"--- Season {season_id} ---")
    for md in range(1, 31):
        res = get_results(season_id, md)
        if not res: continue
        for r in res:
            home = _normalise_team_name(r.get('homeTeam',''))
            away = _normalise_team_name(r.get('awayTeam',''))
            score = r.get('fullTime', '')
            if (home == 'London Guns' and away == 'Everton') or (home == 'Wolverhampton' and away == 'Newcastle'):
                print(f"MD {md}: {home} vs {away} -> Score: {score}")
