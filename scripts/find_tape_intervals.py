import sys
from pathlib import Path
import hashlib
from collections import defaultdict

EMPIRE = Path("/home/ubuntu/faith-workspace/vfl-empire")
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

def get_md_hash(fixtures):
    fixtures.sort(key=lambda x: x["home_team"])
    md_str = "|".join([f"{f['home_team']}{f['home_goals']}-{f['away_goals']}{f['away_team']}" for f in fixtures])
    return hashlib.md5(md_str.encode()).hexdigest()

def main():
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
        
    hash_to_seasons = defaultdict(list)
    
    # We want to sort seasons numerically to see the intervals
    sorted_season_ids = []
    for s in seasons.keys():
        try:
            if "VFLM" in s:
                sid = int(s.split()[-1])
            else:
                sid = int(s.split(":")[-1])
            sorted_season_ids.append((sid, s))
        except:
            pass
            
    sorted_season_ids.sort()
    
    for sid, season in sorted_season_ids:
        mds = seasons[season]
        if 1 in mds and len(mds[1]) == 8:
            h = get_md_hash(mds[1])
            hash_to_seasons[h].append(sid)
            
    print("Recycled Tape Intervals (Seasons that share the exact same Matchday 1):\\n")
    
    recycled_count = 0
    for h, sids in hash_to_seasons.items():
        if len(sids) > 1:
            recycled_count += 1
            print(f"Tape Hash: {h[:8]}... found in {len(sids)} seasons:")
            for i, sid in enumerate(sids):
                if i == 0:
                    print(f"  - Season {sid} (Original)")
                else:
                    diff = sid - sids[i-1]
                    print(f"  - Season {sid} (Recycled, gap: {diff} seasons)")
            print("")
            
    print(f"Total Unique Tapes that were recycled: {recycled_count}")

if __name__ == "__main__":
    main()
