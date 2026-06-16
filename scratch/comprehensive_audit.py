import json
from collections import defaultdict

def normalize_fixture(f):
    teams = sorted(f.split(" vs "))
    return f"{teams[0]} vs {teams[1]}"

def get_md_data(fixtures):
    # Sort fixtures by normalized name to ensure consistent signature
    sorted_fixes = sorted(fixtures, key=lambda x: normalize_fixture(x["teams"]))
    sig = tuple(normalize_fixture(f["teams"]) for f in sorted_fixes)
    results = tuple(f["result"] for f in sorted_fixes)
    # Get odds if available (specifically u35 as a proxy for the 'odds state')
    odds = tuple(f.get("odds", {}).get("u35", 0) for f in sorted_fixes)
    return sig, results, odds

def audit_exact_duplications():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    # 1. Full Matchday Recycle (Schedule + Results)
    # { (sig, results): [ (season, md), ... ] }
    md_recycle = defaultdict(list)
    
    # 2. Fixture-Result Persistence
    # { fixture: { result: count } }
    fixture_persistence = defaultdict(lambda: defaultdict(int))
    
    # 3. Odds-Fixture-Result Fidelity
    # { (fixture, u35_odds): { result: count } }
    odds_fidelity = defaultdict(lambda: defaultdict(int))
    
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            if not fixes or len(fixes) < 8: continue
            
            sig, results, odds_tuple = get_md_data(fixes)
            md_recycle[(sig, results)].append((s_name, md))
            
            for fx in fixes:
                f_name = normalize_fixture(fx["teams"])
                res = fx["result"]
                fixture_persistence[f_name][res] += 1
                
                u35 = fx.get("odds", {}).get("u35")
                if u35:
                    odds_fidelity[(f_name, u35)][res] += 1
                    
    # --- Analyze Findings ---
    
    # A. Report Full MD Recycles (Schedule AND Results are identical)
    full_md_dupes = {k: v for k, v in md_recycle.items() if len(v) > 1}
    
    # B. Report Fixtures that ALWAYS produce the same result (N > 5)
    always_fixtures = []
    for f_name, res_counts in fixture_persistence.items():
        total = sum(res_counts.values())
        if total >= 10 and len(res_counts) == 1:
            always_fixtures.append({"fixture": f_name, "result": list(res_counts.keys())[0], "count": total})
            
    # C. Report Odds-Fixture Locks (Specific odds + fixture ALWAYS produce same result, N > 5)
    odds_locks = []
    for (f_name, odds), res_counts in odds_fidelity.items():
        total = sum(res_counts.values())
        if total >= 5 and len(res_counts) == 1:
            odds_locks.append({"fixture": f_name, "odds": odds, "result": list(res_counts.keys())[0], "count": total})
            
    return {
        "full_matchday_duplications": list(full_md_dupes.values()),
        "absolute_fixture_locks": always_fixtures,
        "odds_fixture_locks": odds_locks
    }

if __name__ == "__main__":
    results = audit_exact_duplications()
    
    print("=== CATEGORY 1: FULL MATCHDAY DUPLICATIONS (Identical Schedule + Identical Results) ===")
    if not results["full_matchday_duplications"]:
        print("None found. MSport likely scrambles the results even if the schedule repeats.")
    else:
        for group in results["full_matchday_duplications"]:
            print(f"Matchdays: {group}")

    print("\n=== CATEGORY 2: ABSOLUTE FIXTURE LOCKS (Fixture ALWAYS produces same score regardless of odds) ===")
    if not results["absolute_fixture_locks"]:
        print("None found. Fixtures alone do not dictate results.")
    else:
        for lock in results["absolute_fixture_locks"]:
            print(f"  {lock['fixture']} -> ALWAYS {lock['result']} ({lock['count']} times)")

    print("\n=== CATEGORY 3: ODDS-FIXTURE LOCKS (Specific Odds + Fixture ALWAYS produce same score) ===")
    if not results["odds_fixture_locks"]:
        print("None found.")
    else:
        # Sort by count
        sorted_locks = sorted(results["odds_fixture_locks"], key=lambda x: x["count"], reverse=True)
        for lock in sorted_locks[:20]:
            print(f"  {lock['fixture']} (u35 Odds: {lock['odds']}) -> ALWAYS {lock['result']} ({lock['count']} times)")
