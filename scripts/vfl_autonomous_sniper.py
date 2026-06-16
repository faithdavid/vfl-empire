#!/usr/bin/env python3
import time
import json
import logging
import subprocess
import requests
import sys
from pathlib import Path
from collections import defaultdict

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db
sys.path.insert(0, str(EMPIRE / "scripts"))
from msport_api import get_event_list
from vfl_live_predictor import extract_odds, normalize_team

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("autonomous_sniper")

# Replace these with your actual Telegram bot token and chat ID if needed, 
# or fall back to Discord if that's what was set up.
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1310617631627055114/aH2l-0B-YV6b3q15b_8Bw99mJ6261mNnKj5uT21L0IeLz351kQ2V75k_O8H9oT2fB-z"

def send_alert(message):
    logger.info(f"ALERT: {message}")
    # Discord Fallback
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=5)
    except:
        pass
    
    # Telegram
    if TELEGRAM_BOT_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN":
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.warning(f"Telegram alert failed: {e}")

def get_md_hash(fixtures):
    for f in fixtures:
        f["home_team"] = normalize_team(f["home_team"])
        f["away_team"] = normalize_team(f["away_team"])
    fixtures.sort(key=lambda x: x["home_team"])
    md_str = "|".join([f"{f['home_team']}{f['home_goals']}-{f['away_goals']}{f['away_team']}" for f in fixtures])
    import hashlib
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

def check_balance():
    try:
        cmd = ["python3", str(EMPIRE / "scripts" / "browser_bet_placer.py"), "balance"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        for line in res.stdout.split('\n'):
            if line.startswith('{'):
                data = json.loads(line)
                return data.get("balance", "Unknown")
    except Exception as e:
        logger.warning(f"Failed to check balance: {e}")
    return "Unknown"

def place_parlay(legs, stake, target_md):
    payload = {
        "target_md": target_md,
        "stake": stake,
        "legs": legs
    }
    try:
        cmd = ["python3", str(EMPIRE / "scripts" / "browser_bet_placer.py"), "parlay", json.dumps(payload)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        for line in res.stdout.split('\n'):
            if line.startswith('{'):
                data = json.loads(line)
                return data
    except Exception as e:
        logger.warning(f"Failed to place parlay: {e}")
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "No JSON response"}

def main():
    logger.info("=========================================")
    logger.info("🤖 AUTONOMOUS VFL TAPE SNIPER ONLINE 🤖")
    logger.info("=========================================")
    
    seasons, history_md1 = build_history()
    
    current_season = None
    matched_hist_season = None
    last_bet_md = 0
    highest_logged_md = 0
    checked_current_season = False
    STAKE = 150  # Start with 150 Naira
    
    bal = check_balance()
    send_alert(f"🤖 Autonomous Sniper Online.\nInitial MSport Balance: ₦{bal}\nStake configured to ₦{STAKE} per matchday.")
    
    while True:
        try:
            match_days = get_event_list()
            if not match_days:
                time.sleep(10)
                continue
                
            md_live = match_days[0]
            live_s_id = md_live.get("seasonId", "Unknown")
            live_md = md_live.get("matchDay", 0)
            
            # Reset on new season
            if current_season != live_s_id:
                current_season = live_s_id
                matched_hist_season = None
                last_bet_md = 0
                highest_logged_md = 0
                checked_current_season = False
                logger.info(f"\n--- NEW LIVE SEASON: {current_season} ---")
                
            if live_md > highest_logged_md:
                highest_logged_md = live_md
                logger.info(f"👀 Polling MSport: Tracking Season {current_season} - MatchDay {live_md} Active.")
                
            if not checked_current_season and live_md >= 1:
                # Wait for MD1 results to appear in DB
                sql_curr_md1 = """
                    SELECT home_team, away_team, home_goals, away_goals 
                    FROM v_results_odd_even_ready 
                    WHERE season_name = %s AND matchday_number = 1
                """
                with get_db() as cur:
                    cur.execute(sql_curr_md1, (current_season,))
                    curr_md1_rows = [dict(r) for r in cur.fetchall()]
                
                # FALLBACK: Poll MSport API directly if DB is missing MD1 results
                if len(curr_md1_rows) < 8:
                    try:
                        from msport_api import get_results
                        api_results = get_results(current_season, 1)
                        if api_results and len(api_results) == 8:
                            curr_md1_rows = []
                            for r in api_results:
                                hg, ag = r['fullTime'].split(':')
                                curr_md1_rows.append({
                                    "home_team": r['homeTeam'],
                                    "away_team": r['awayTeam'],
                                    "home_goals": int(hg),
                                    "away_goals": int(ag)
                                })
                            logger.info("🎯 Fetched MD1 results directly from MSport API (DB Fallback).")
                    except Exception as e:
                        pass
                    
                if len(curr_md1_rows) == 8:
                    checked_current_season = True
                    curr_hash = get_md_hash(curr_md1_rows)
                    # Find match
                    for h, s in history_md1.items():
                        if h == curr_hash and s != current_season:
                            matched_hist_season = s
                            break
                            
                    if matched_hist_season and last_bet_md == 0:
                        last_bet_md = live_md if live_md > 1 else 1
                        msg = f"🚨 TAPE MATCH DETECTED! 🚨\nLive Season {current_season} matches Historical Tape {matched_hist_season}.\nInitiating automated Parley accumulation..."
                        send_alert(msg)
                else:
                    logger.info(f"Waiting for MD1 results... ({len(curr_md1_rows)}/8)")
            
            elif matched_hist_season and live_md > last_bet_md:
                # First check if the previous MD diverged
                if live_md > 2:
                    prev_md = live_md - 1
                    sql_prev = "SELECT home_team, away_team, home_goals, away_goals FROM v_results_odd_even_ready WHERE season_name = %s AND matchday_number = %s"
                    with get_db() as cur:
                        cur.execute(sql_prev, (current_season, prev_md))
                        prev_rows = [dict(r) for r in cur.fetchall()]
                        
                    if len(prev_rows) == 8:
                        live_prev_hash = get_md_hash(prev_rows)
                        hist_prev_hash = get_md_hash(seasons[matched_hist_season][prev_md])
                        if live_prev_hash != hist_prev_hash:
                            msg = f"🛑 TAPE DIVERGED on MD {prev_md}. The winning streak has ended. Parley lost.\nStanding down until next season."
                            send_alert(msg)
                            matched_hist_season = None
                            continue
                
                # Tape is still active, place bet for current live_md
                hist_md = seasons[matched_hist_season].get(live_md)
                if hist_md and len(hist_md) == 8:
                    legs = []
                    for f in hist_md:
                        ht = normalize_team(f["home_team"])
                        at = normalize_team(f["away_team"])
                        hg = f["home_goals"]
                        ag = f["away_goals"]
                        pred_1x2 = "1" if hg > ag else "2" if ag > hg else "X"
                        legs.append({"home": ht, "away": at, "market": pred_1x2})
                        
                    logger.info(f"Placing 8-game 1X2 Parlay for MD {live_md} (Stake: ₦{STAKE})...")
                    res = place_parlay(legs, STAKE, live_md)
                    
                    if res.get("success"):
                        bal_after = res.get("balance", "Unknown")
                        msg = f"✅ MD {live_md}: 8-Game 1X2 Parlay Placed Successfully!\nStake: ₦{STAKE}\nNew MSport Balance: ₦{bal_after}"
                        send_alert(msg)
                    else:
                        err = res.get("error", "Unknown Error")
                        msg = f"❌ MD {live_md} Bet Placement FAILED: {err}"
                        send_alert(msg)
                        
                    last_bet_md = live_md
                else:
                    matched_hist_season = None
                    
        except Exception as e:
            logger.error(f"Engine Loop Error: {e}")
            
        time.sleep(15)

if __name__ == "__main__":
    main()
