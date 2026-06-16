import sys
from pathlib import Path
import hashlib
from collections import defaultdict

EMPIRE = Path("/home/ubuntu/faith-workspace/vfl-empire")
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db
sys.path.insert(0, str(EMPIRE / "scripts"))
from msport_api import get_results
from vfl_live_predictor import normalize_team

def get_md_hash(fixtures):
    for f in fixtures:
        f["home_team"] = normalize_team(f["home_team"])
        f["away_team"] = normalize_team(f["away_team"])
    fixtures.sort(key=lambda x: x["home_team"])
    md_str = "|".join([f"{f['home_team']}{f['home_goals']}-{f['away_goals']}{f['away_team']}" for f in fixtures])
    return hashlib.md5(md_str.encode()).hexdigest()

def extract_api_results(results_data):
    # API format returns a list of objects. Inside, we have homeTeam, awayTeam, result.
    fixtures = []
    for r in results_data:
        res_str = r.get("result", {}).get("1X2", "0:0")
        parts = res_str.split(":")
        hg, ag = 0, 0
        if len(parts) == 2:
            hg, ag = int(parts[0]), int(parts[1])
        fixtures.append({
            "home_team": r.get("homeTeam", ""),
            "away_team": r.get("awayTeam", ""),
            "home_goals": hg,
            "away_goals": ag
        })
    return fixtures

def main():
    # Fetch from API
    current_season = "vf:season:3100694"
    prev_season = "vf:season:3100668"
    
    s_curr_results = get_results(current_season, 1)
    s_prev_results = get_results(prev_season, 1)

    curr_md1 = extract_api_results(s_curr_results) if s_curr_results else []
    prev_md1 = extract_api_results(s_prev_results) if s_prev_results else []

    if len(curr_md1) == 8:
        curr_hash = get_md_hash(curr_md1)
    else:
        curr_hash = None
        
    if len(prev_md1) == 8:
        prev_hash = get_md_hash(prev_md1)
    else:
        prev_hash = None
        
    # Build history hashes
    sql = """
        SELECT season_name, matchday_number, home_team, away_team, home_goals, away_goals 
        FROM v_results_odd_even_ready 
        ORDER BY season_name ASC, matchday_number ASC, home_team ASC
    """
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        
    seasons = defaultdict(lambda: defaultdict(list))
    for r in rows:
        seasons[r["season_name"]][r["matchday_number"]].append(r)
        
    history_md1 = {}
    for season, mds in seasons.items():
        if 1 in mds and len(mds[1]) == 8:
            h = get_md_hash(mds[1])
            history_md1[h] = season
            
    # Check
    print(f"Current Season ({current_season}) Hash: {curr_hash}")
    match_found = False
    if curr_hash:
        for h, s in history_md1.items():
            if h == curr_hash and s != current_season:
                print(f"✅ MATCH FOUND! {current_season} perfectly matches historical season {s}")
                match_found = True
        if not match_found:
            print(f"❌ NO MATCH FOUND for {current_season}.")
            
    print(f"\nPrevious Season ({prev_season}) Hash: {prev_hash}")
    match_found = False
    if prev_hash:
        for h, s in history_md1.items():
            if h == prev_hash and s != prev_season:
                print(f"✅ MATCH FOUND! {prev_season} perfectly matches historical season {s}")
                match_found = True
        if not match_found:
            print(f"❌ NO MATCH FOUND for {prev_season}.")

if __name__ == "__main__":
    main()
