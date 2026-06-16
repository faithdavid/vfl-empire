import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from msport_api import get_results

season_id = 'vf:season:3097276'
print(f"Checking results for {season_id} (VFLM 5297)")

for md in range(19, 24):
    res = get_results(season_id, md)
    if res:
        print(f"\nMatchday {md} Results:")
        for r in res:
            print(f"{r.get('homeTeam')} vs {r.get('awayTeam')} -> HT: {r.get('halfTime')}, FT: {r.get('fullTime')}")
    else:
        print(f"No results yet for Matchday {md}")
