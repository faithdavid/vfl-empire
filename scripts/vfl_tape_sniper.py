#!/usr/bin/env python3
import json
import logging
import sys
import hashlib
from pathlib import Path
from collections import defaultdict

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
try:
    from common.db_manager import get_db
except ImportError:
    print("Could not import get_db")
    sys.exit(1)

sys.path.insert(0, str(EMPIRE / "scripts"))
try:
    from msport_api import get_event_list
    from vfl_live_predictor import extract_odds, normalize_team
except ImportError as e:
    print(f"Could not import live modules: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tape_sniper")

def get_md_hash(fixtures):
    # Ensure canonical team names
    for f in fixtures:
        f["home_team"] = normalize_team(f["home_team"])
        f["away_team"] = normalize_team(f["away_team"])
        
    fixtures.sort(key=lambda x: x["home_team"])
    md_str = "|".join([f"{f['home_team']}{f['home_goals']}-{f['away_goals']}{f['away_team']}" for f in fixtures])
    return hashlib.md5(md_str.encode()).hexdigest()

def build_history():
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
            
    return seasons, history_md1

def main():
    logger.info("=========================================")
    logger.info("🎰 VFL TAPE SNIPER ENGINE INITIATED 🎰")
    logger.info("=========================================")
    
    seasons, history_md1 = build_history()
    
    match_days = get_event_list()
    if not match_days:
        logger.warning("No live events found. MSport API might be between cycles.")
        return
        
    md_live = match_days[0]
    season_live = md_live.get("seasonId", "Unknown")
    matchday_live = md_live.get("matchDay", "Unknown")
    
    logger.info(f"Live Season: {season_live} | Live Matchday: {matchday_live}")
    
    if matchday_live < 2:
        logger.info("Waiting for Matchday 1 to complete so we can hash the tape...")
        return
        
    # Get current season MD1 results from DB
    sql_curr_md1 = """
        SELECT home_team, away_team, home_goals, away_goals 
        FROM v_results_odd_even_ready 
        WHERE season_name = %s AND matchday_number = 1
    """
    
    with get_db() as cur:
        cur.execute(sql_curr_md1, (season_live,))
        curr_md1_rows = [dict(r) for r in cur.fetchall()]
        
    if len(curr_md1_rows) != 8:
        logger.info(f"MD1 results not fully saved yet in DB for {season_live}. Only {len(curr_md1_rows)} records found.")
        return
        
    curr_hash = get_md_hash(curr_md1_rows)
    logger.info(f"Current Season MD1 Hash: {curr_hash[:8]}")
    
    # Exclude the current season from historical matches (in case it's already there)
    matched_season = None
    for h, s in history_md1.items():
        if h == curr_hash and s != season_live:
            matched_season = s
            break
            
    if matched_season:
        logger.info(f"🚨 TAPE MATCH DETECTED! Historical Tape: {matched_season}")
        logger.info(f"Deploying Oracle for Matchday {matchday_live}...\n")
        
        hist_mds = seasons.get(matched_season, {})
        target_hist_md = hist_mds.get(matchday_live, [])
        
        if not target_hist_md or len(target_hist_md) != 8:
            logger.warning(f"Tape divergence or missing data in history at MD {matchday_live}.")
            return
            
        # Build the exact predictions
        predictions = {}
        for f in target_hist_md:
            ht = normalize_team(f["home_team"])
            at = normalize_team(f["away_team"])
            predictions[(ht, at)] = f"{f['home_goals']}:{f['away_goals']}"
            
        # Match them to live MSport odds
        for event in md_live.get("events", []):
            home = normalize_team(event.get("homeTeamName", "Unknown"))
            away = normalize_team(event.get("awayTeamName", "Unknown"))
            
            cs_pred = predictions.get((home, away))
            if not cs_pred:
                continue
                
            odds_dict = extract_odds(event)
            msport_cs_odds = odds_dict.get("Correct Score", {})
            
            book_odds = None
            if cs_pred in msport_cs_odds:
                book_odds = msport_cs_odds[cs_pred]
            else:
                hyphen_sl = cs_pred.replace(":", "-")
                if hyphen_sl in msport_cs_odds:
                    book_odds = msport_cs_odds[hyphen_sl]
                    
            logger.info(f"[{home} vs {away}] -> GUARANTEED SCORE: {cs_pred}")
            logger.info(f"   => Available Odds: @{book_odds if book_odds else 'N/A'}")
            
        logger.info("\n🚨 LOCK THESE IN NOW. TAPE IS ACTIVE. 🚨")
    else:
        logger.info("No historical tape match found. This is a unique season seed. Stand down.")
        
    logger.info("=========================================\n")

if __name__ == "__main__":
    main()
