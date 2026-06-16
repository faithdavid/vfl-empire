import json

def find_md_for_fixtures(f1, f2):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    results = []
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            teams = set(fx["teams"] for fx in fixes)
            if f1 in teams and f2 in teams:
                results.append((s_name, md))
    return results

if __name__ == "__main__":
    res = find_md_for_fixtures("Liverpool vs Everton", "West Ham vs Crystal Palace")
    print(json.dumps(res, indent=2))
