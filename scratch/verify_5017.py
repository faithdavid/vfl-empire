import json

def get_md_fixtures(season, md):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    if season in data and md in data[season]:
        return set(sorted(f["teams"].split(" vs "))[0] + " vs " + sorted(f["teams"].split(" vs "))[1] for f in data[season][md])
    return None

if __name__ == "__main__":
    fixtures_18_live = set(["London Guns vs Chelsea", "Everton vs Crystal Palace", "Fulham vs Brighton", "Aston Villa vs Manchester Red", "Tottenham vs Newcastle", "Wolverhampton vs Bournemouth", "Leeds vs Liverpool", "Manchester Blue vs West Ham"])
    fixtures_18_live_norm = set()
    for f in fixtures_18_live:
        ts = sorted(f.split(" vs "))
        fixtures_18_live_norm.add(f"{ts[0]} vs {ts[1]}")
        
    fixtures_19_hist = get_md_fixtures("VFLM 5017", "19")
    
    print(f"Match 5017 MD 19? {fixtures_18_live_norm == fixtures_19_hist}")
    if not fixtures_18_live_norm == fixtures_19_hist:
        print(f"Live: {sorted(list(fixtures_18_live_norm))}")
        print(f"Hist: {sorted(list(fixtures_19_hist)) if fixtures_19_hist else 'None'}")
