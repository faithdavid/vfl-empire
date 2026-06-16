import sys
from pathlib import Path
import hashlib
from collections import defaultdict

EMPIRE = Path("/home/ubuntu/faith-workspace/vfl-empire")
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db
sys.path.insert(0, str(EMPIRE / "scripts"))
from msport_api import get_event_list
from vfl_live_predictor import normalize_team

def get_md_hash(fixtures):
    for f in fixtures:
        f["home_team"] = normalize_team(f["home_team"])
        f["away_team"] = normalize_team(f["away_team"])
    fixtures.sort(key=lambda x: x["home_team"])
    md_str = "|".join([f"{f['home_team']}{f['home_goals']}-{f['away_goals']}{f['away_team']}" for f in fixtures])
    return hashlib.md5(md_str.encode()).hexdigest()

def main():
    # 1. Get live season
    try:
        live_events = get_event_list()
        current_season = live_events[0]["seasonId"]
        print(f"Current Live Season: {current_season}")
    except Exception as e:
        print(f"Could not fetch live season: {e}")
        return

    # 2. Build history hashes
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
            
    # 3. Check if current season MD1 is in DB
    if current_season not in seasons or 1 not in seasons[current_season] or len(seasons[current_season][1]) != 8:
        print(f"MD1 results for {current_season} are not fully captured in the database yet.")
        return

    curr_md1 = seasons[current_season][1]
    curr_hash = get_md_hash(curr_md1)
    
    print(f"\nCurrent Season Hash: {curr_hash}")
    
    match_found = False
    for h, s in history_md1.items():
        if h == curr_hash and s != current_season:
            print(f"✅ MATCH FOUND! {current_season} perfectly matches historical season {s}")
            match_found = True
            
    if not match_found:
        print(f"❌ NO MATCH FOUND. This season's MD1 is a completely unique seed.")

if __name__ == "__main__":
    main()
