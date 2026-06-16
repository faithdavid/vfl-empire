import json

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def audit_season_fixtures(s_name):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    season = data.get(s_name)
    if not season: return None
    
    all_fixtures = []
    for md, fixes in season.items():
        for fx in fixes:
            all_fixtures.append(normalize_fixture(fx["teams"]))
    return sorted(all_fixtures)

if __name__ == "__main__":
    f5146 = audit_season_fixtures("VFLM 5146")
    f5145 = audit_season_fixtures("VFLM 5145")
    
    if f5146 and f5145:
        print(f"Season 5146 total fixtures: {len(f5146)}")
        print(f"Season 5145 total fixtures: {len(f5145)}")
        print(f"Identical fixture set? {f5146 == f5145}")
    else:
        print("Season data missing.")
