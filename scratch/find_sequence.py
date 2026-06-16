import json

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def find_sequence_match(md_results):
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    target_sequence = []
    for md in sorted(md_results.keys()):
        if md_results[md]:
            target_sequence.append(set(normalize_fixture(f"{r['homeTeam']} vs {r['awayTeam']}") for r in md_results[md]))
    
    matches = []
    for s_name, seasons in data.items():
        if s_name == "VFLM 5147": continue
        
        md_keys = sorted(seasons.keys(), key=lambda x: int(x))
        season_fixtures = []
        for k in md_keys:
            season_fixtures.append(set(normalize_fixture(fix["teams"]) for fix in seasons[k]))
        
        for i in range(len(season_fixtures) - len(target_sequence) + 1):
            match = True
            for j in range(len(target_sequence)):
                if not target_sequence[j].issubset(season_fixtures[i+j]) and not season_fixtures[i+j].issubset(target_sequence[j]):
                    match = False
                    break
            if match:
                matches.append({"season": s_name, "start_md": md_keys[i], "offset": i})
                
    return matches

if __name__ == "__main__":
    results_17 = [
        {"homeTeam": "Crystal Palace", "awayTeam": "London Guns"},
        {"homeTeam": "Liverpool", "awayTeam": "Bournemouth"},
        {"homeTeam": "Aston Villa", "awayTeam": "Wolverhampton"},
        {"homeTeam": "West Ham", "awayTeam": "Fulham"},
        {"homeTeam": "Newcastle", "awayTeam": "Leeds"},
        {"homeTeam": "Brighton", "awayTeam": "Tottenham"},
        {"homeTeam": "Manchester Red", "awayTeam": "Everton"},
        {"homeTeam": "Chelsea", "awayTeam": "Manchester Blue"}
    ]
    results_18 = [
        {"homeTeam": "London Guns", "awayTeam": "Chelsea"},
        {"homeTeam": "Everton", "awayTeam": "Crystal Palace"},
        {"homeTeam": "Fulham", "awayTeam": "Brighton"},
        {"homeTeam": "Aston Villa", "awayTeam": "Manchester Red"},
        {"homeTeam": "Tottenham", "awayTeam": "Newcastle"},
        {"homeTeam": "Wolverhampton", "awayTeam": "Bournemouth"},
        {"homeTeam": "Leeds", "awayTeam": "Liverpool"},
        {"homeTeam": "Manchester Blue", "awayTeam": "West Ham"}
    ]
    results_19 = [
        {"homeTeam": "Bournemouth", "awayTeam": "Leeds"},
        {"homeTeam": "Brighton", "awayTeam": "Manchester Blue"},
        {"homeTeam": "Crystal Palace", "awayTeam": "Aston Villa"},
        {"homeTeam": "Chelsea", "awayTeam": "Everton"},
        {"homeTeam": "West Ham", "awayTeam": "London Guns"},
        {"homeTeam": "Newcastle", "awayTeam": "Fulham"},
        {"homeTeam": "Manchester Red", "awayTeam": "Wolverhampton"},
        {"homeTeam": "Liverpool", "awayTeam": "Tottenham"}
    ]
    
    md_results = {17: results_17, 18: results_18, 19: results_19}
    matches = find_sequence_match(md_results)
    print(json.dumps(matches, indent=2))
