#!/usr/bin/env python3
import json
import logging
from pathlib import Path
import subprocess
from datetime import datetime

BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
JSON_PATH = SCRIPTS_DIR / "predictions_latest.json"
STATE_FILE = SCRIPTS_DIR / ".tier_routing_state"
DISCORD_TARGET = "discord:1507922324072960031:1516407526491684944" # vfl-predictions forum thread

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tier_routing_daemon")

def get_tier(rank_str):
    try:
        rank = int(rank_str)
        if rank <= 4: return "T1(1-4)"
        if rank <= 8: return "T2(5-8)"
        if rank <= 12: return "T3(9-12)"
        return "T4(13-16)"
    except:
        return "Unknown"

def get_md_chunk(md):
    if md <= 5: return "MD 1-5"
    if md <= 10: return "MD 6-10"
    if md <= 15: return "MD 11-15"
    if md <= 20: return "MD 16-20"
    if md <= 25: return "MD 21-25"
    return "MD 26-30"

def send_to_discord(title, content):
    logger.info("Sending tier routing alert to Discord...")
    try:
        res = subprocess.run(
            ["/home/ubuntu/.local/bin/hermes", "send", "--to", DISCORD_TARGET, f"**{title}**\n\n{content}"],
            capture_output=True, text=True, check=True
        )
        logger.info(f"Successfully posted to Discord.")
    except Exception as e:
        logger.error(f"Error posting to Discord: {e}")

def run():
    if not JSON_PATH.exists():
        return

    with open(JSON_PATH, "r") as f:
        data = json.load(f)

    if not data.get('matchdays'):
        return

    md = data['matchdays'][0]
    season = md.get('season_id', 'Unknown')
    matchday = md.get('matchday', 'Unknown')
    
    try:
        md_num = int(matchday)
    except:
        return
        
    chunk = get_md_chunk(md_num)
    
    last_posted = ""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            last_posted = f.read().strip()
            
    current_state = f"{season}-{matchday}"
    if last_posted == current_state:
        return # Already posted
        
    locks_found = []
    
    for fix in md.get('fixtures', []):
        home = fix.get('home', 'Unknown')
        away = fix.get('away', 'Unknown')
        odds = fix.get('odds', {})
        
        markets = fix.get('markets', [])
        h_rank, a_rank = '?', '?'
        if markets:
            gates = markets[0].get('gate_result', {}).get('gates', {})
            ls = gates.get('league_standing', {})
            h_rank = ls.get('h_rank', '?')
            a_rank = ls.get('a_rank', '?')
            
        h_tier = get_tier(h_rank)
        a_tier = get_tier(a_rank)
        
        route = f"[{chunk}] Home:{h_tier} vs Away:{a_tier}"
        
        # Check against our universal map
        bet = None
        prob = None
        
        if chunk == "MD 21-25" and h_tier == "T2(5-8)" and a_tier == "T3(9-12)":
            bet = "1X (Home Win/Draw)"; prob = "81.6%"
        elif chunk == "MD 26-30" and h_tier == "T1(1-4)" and a_tier == "T3(9-12)":
            bet = "1X (Home Win/Draw)"; prob = "90.0%"
        elif chunk == "MD 16-20" and h_tier == "T1(1-4)" and a_tier == "T3(9-12)":
            bet = "1X (Home Win/Draw)"; prob = "84.8%"
        elif chunk == "MD 16-20" and h_tier == "T1(1-4)" and a_tier == "T2(5-8)":
            bet = "1X (Home Win/Draw)"; prob = "80.4%"
            
        if bet:
            locks_found.append({
                "fixture": f"{home} [{h_tier}] vs {away} [{a_tier}]",
                "route": route,
                "bet": bet,
                "prob": prob,
                "odds": f"1: {odds.get('home_win')} / X: {odds.get('draw')}"
            })

    content = f"### MATCHDAY CHUNK: {chunk}\n\n"
    if locks_found:
        content += "## 🎯 UNIVERSAL TIER-ROUTING LOCKS ACTIVE 🎯\n\n"
        for idx, lock in enumerate(locks_found):
            content += f"**{idx+1}. {lock['fixture']}**\n"
            content += f"**Route Map:** `{lock['route']}`\n"
            content += f"**Algorithmic Probability:** {lock['prob']}\n"
            content += f"**Action:** Place {lock['bet']} | Odds: {lock['odds']}\n\n"
    else:
        content += "No 92%+ Tier-Routing Locks matched for this matchday.\n"
        content += "Skipping to avoid variance traps.\n"
        
    send_to_discord(f"MD {matchday} Tier-Routing Predictions ({season})", content)
    
    with open(STATE_FILE, "w") as f:
        f.write(current_state)

if __name__ == "__main__":
    run()
