import sys
from pathlib import Path
import hashlib
from collections import defaultdict

EMPIRE = Path("/home/ubuntu/faith-workspace/vfl-empire")
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

def normalize_team(name):
    name = name.strip()
    mapping = {
        "Man Blue": "Man Blue", "Man Red": "Man Red",
        "Merseyside Red": "Merseyside Red", "London Reds": "London Reds"
    }
    return mapping.get(name, name)

def get_md_hash(fixtures):
    for f in fixtures:
        f["home_team"] = normalize_team(f["home_team"])
        f["away_team"] = normalize_team(f["away_team"])
    fixtures.sort(key=lambda x: x["home_team"])
    md_str = "|".join([f"{f['home_team']}{f['home_goals']}-{f['away_goals']}{f['away_team']}" for f in fixtures])
    return hashlib.md5(md_str.encode()).hexdigest()

def get_1x2(hg, ag):
    if hg > ag: return "1"
    elif hg == ag: return "X"
    else: return "2"

def main():
    print("Loading DB history...")
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
        
    # Get sorted season list
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
    
    # Build history hashes (all seasons)
    history_md1 = defaultdict(list)
    for sid, s in sorted_season_ids:
        mds = seasons[s]
        if 1 in mds and len(mds[1]) == 8:
            h = get_md_hash(mds[1])
            history_md1[h].append(s)

    # Pick the last 30 complete seasons
    # "complete" = has MD1 with 8 games
    valid_seasons = [s for sid, s in sorted_season_ids if 1 in seasons[s] and len(seasons[s][1]) == 8]
    if not valid_seasons:
        print("No valid seasons found in DB.")
        return
        
    last_30 = valid_seasons[-30:]
    
    print(f"Testing the last {len(last_30)} seasons...\n")
    
    matches_found = 0
    total_profit = 0
    stake = 150
    avg_odds = 2.0  # Conservative estimate per leg, parlay of 8 = 256.0 odds
    
    for live_s in last_30:
        md1 = seasons[live_s][1]
        h = get_md_hash(md1)
        
        # Check if hash exists in history (excluding itself)
        matched_history_seasons = [hs for hs in history_md1[h] if hs != live_s]
        
        if not matched_history_seasons:
            continue
            
        history_s = matched_history_seasons[0]  # Take the first matched tape
        matches_found += 1
        print(f"🚨 TAPE MATCH! Live Season: {live_s} matches History: {history_s}")
        
        streak = 0
        for md in range(2, 31):
            if md not in seasons[live_s] or md not in seasons[history_s]:
                break
            
            live_games = seasons[live_s][md]
            hist_games = seasons[history_s][md]
            
            if len(live_games) != 8 or len(hist_games) != 8:
                break
                
            # Compare 1X2 outcomes
            live_games.sort(key=lambda x: normalize_team(x["home_team"]))
            hist_games.sort(key=lambda x: normalize_team(x["home_team"]))
            
            perfect = True
            for lg, hg in zip(live_games, hist_games):
                if get_1x2(lg["home_goals"], lg["away_goals"]) != get_1x2(hg["home_goals"], hg["away_goals"]):
                    perfect = False
                    break
                    
            if perfect:
                streak += 1
            else:
                break
                
        print(f"  🛑 Ending bet cycle for this tape. Winning Streak: {streak} perfect Matchdays.")
        
        # Calculate rough profit
        if streak > 0:
            # We bet 'stake' for each matchday until the streak breaks.
            # We win 'streak' times, and lose 1 time (the breaking matchday).
            # If streak = 0, we lose 1 time.
            profit = (stake * (2.0 ** 8) * streak) - (stake * (streak + 1))
        else:
            profit = -stake
            
        total_profit += profit

    print(f"\n--- SUMMARY OVER LAST 30 SEASONS ---")
    print(f"Tapes Found: {matches_found}")
    print(f"Estimated Net Profit (₦{stake} stakes): ₦{total_profit:,.2f}")

if __name__ == "__main__":
    main()
