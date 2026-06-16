import sys
from pathlib import Path
from collections import defaultdict
import hashlib

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

def get_md_hash(fixtures):
    # Sort by home team to ensure consistent order
    fixtures.sort(key=lambda x: x["home_team"])
    md_str = "|".join([f"{f['home_team']}{f['home_goals']}-{f['away_goals']}{f['away_team']}" for f in fixtures])
    return hashlib.md5(md_str.encode()).hexdigest()

def main():
    print("Hunting for Reused Season Tapes (Global Cycles)...")
    
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
        
    md1_hashes = defaultdict(list)
    
    for season, mds in seasons.items():
        if 1 in mds and len(mds[1]) == 8:
            h = get_md_hash(mds[1])
            md1_hashes[h].append(season)
            
    repeated_tapes = {h: s_list for h, s_list in md1_hashes.items() if len(s_list) > 1}
    
    print(f"Total Unique Seasons scanned: {len(seasons)}")
    print(f"Unique MD1 Outcomes found: {len(md1_hashes)}")
    
    if not repeated_tapes:
        print("No MD1s were perfectly identical across any two seasons.")
        print("The RNG does not reuse full season tapes or MD1 tapes verbatim.")
        return
        
    print(f"\n🚨 FOUND {len(repeated_tapes)} MATCHDAY 1 SEQUENCES THAT REPEATED MULTIPLE SEASONS! 🚨\n")
    
    for h, s_list in repeated_tapes.items():
        print(f"MD1 Hash: {h[:8]} occurred in {len(s_list)} seasons: {s_list}")
        
        # Check if MD2 is also identical among these seasons
        md2_hashes = set()
        for s in s_list:
            if 2 in seasons[s] and len(seasons[s][2]) == 8:
                md2_hashes.add(get_md_hash(seasons[s][2]))
                
        if len(md2_hashes) == 1:
            print("  --> 🤯 HOLY GRAIL: MATCHDAY 2 WAS ALSO 100% IDENTICAL ACROSS THESE SEASONS!")
            # Check the whole season!
            identical_to_the_end = True
            for md in range(3, 31):
                md_h = set()
                for s in s_list:
                    if md in seasons[s] and len(seasons[s][md]) == 8:
                        md_h.add(get_md_hash(seasons[s][md]))
                if len(md_h) > 1:
                    identical_to_the_end = False
                    print(f"  --> Tape divergence happened at MD {md}.")
                    break
            if identical_to_the_end:
                print("  --> 💣 NUCLEAR LOCK: THE ENTIRE 30-MATCHDAY SEASON TAPE WAS REUSED VERBATIM!")
        else:
            print("  --> MD2 diverged. MD1 can repeat, but the rest of the season changes.")
        print("-" * 40)

if __name__ == "__main__":
    main()
