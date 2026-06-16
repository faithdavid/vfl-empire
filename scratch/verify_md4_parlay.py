import subprocess
import json

def get_sql_output(query):
    cmd = ["sudo", "-u", "postgres", "psql", "-d", "vfl_empire", "-t", "-A", "-c", query]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip().split('\n')

def verify_parlay(md):
    # Our parlay legs
    legs = [
        {"h": "Everton", "a": "Tottenham", "market": "Under 3.5 Goals"},
        {"h": "Manchester Blue", "a": "Newcastle", "market": "Over 1.5 Goals"},
        {"h": "Crystal Palace", "a": "Brighton", "market": "Over 1.5 Goals"},
        {"h": "Aston Villa", "a": "Bournemouth", "market": "Over 1.5 Goals"},
        {"h": "Fulham", "a": "Liverpool", "market": "Under 3.5 Goals"}
    ]
    
    query = f"""
    SELECT r.home_team, r.away_team, r.home_goals, r.away_goals
    FROM vfl_results_v2 r
    JOIN vfl_matchdays m ON r.matchday_id = m.id
    JOIN vfl_seasons s ON m.season_id = s.id
    WHERE s.season_name = 'VFLM 5148' AND m.matchday_number = {md};
    """
    rows = get_sql_output(query)
    if not rows or not rows[0]:
        return "Results not yet available in DB."

    results = {}
    for row in rows:
        h, a, hg, ag = row.split("|")
        results[tuple(sorted([h, a]))] = (int(hg), int(ag))

    verification = []
    all_won = True
    for leg in legs:
        pair = tuple(sorted([leg["h"], leg["a"]]))
        res = results.get(pair)
        if not res:
            verification.append(f"{leg['h']} vs {leg['a']}: NOT FOUND")
            all_won = False
            continue
        
        hg, ag = res
        total = hg + ag
        won = False
        if leg["market"] == "Under 3.5 Goals":
            won = total < 3.5
        elif leg["market"] == "Over 1.5 Goals":
            won = total > 1.5
            
        verification.append(f"{leg['h']} vs {leg['a']} ({hg}-{ag}): {'WON' if won else 'LOST'}")
        if not won: all_won = False

    return {
        "summary": "PARLAY WON" if all_won else "PARLAY LOST",
        "details": verification
    }

if __name__ == "__main__":
    outcome = verify_parlay(4)
    print(json.dumps(outcome, indent=2))
