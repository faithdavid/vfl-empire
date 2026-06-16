import json
from collections import defaultdict

def analyze_odds_fidelity():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    # fixture -> list of (u35_odds, result)
    fixture_stats = defaultdict(list)
    
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            for fx in fixes:
                teams = fx["teams"]
                u35 = fx.get("odds", {}).get("u35")
                if u35:
                    fixture_stats[teams].append({
                        "season": s_name,
                        "md": md,
                        "u35": u35,
                        "result": fx["result"]
                    })
                    
    # Find fixtures with multiple entries
    fidelity_report = []
    for teams, entries in fixture_stats.items():
        if len(entries) > 2:
            # Check if same odds produce same results
            odds_map = defaultdict(list)
            for e in entries:
                odds_map[e["u35"]].append(e["result"])
            
            fidelity_report.append({
                "teams": teams,
                "odds_variations": len(odds_map),
                "total_entries": len(entries),
                "samples": list(odds_map.items())[:3]
            })
            
    return sorted(fidelity_report, key=lambda x: x["total_entries"], reverse=True)

if __name__ == "__main__":
    report = analyze_odds_fidelity()
    print(json.dumps(report[:10], indent=2))
