#!/usr/bin/env python3
"""
vfl_live_power_parlay.py
========================
Detects "Power Matchdays" (2+ locks playing simultaneously) and automatically
places a parlay bet via browser_bet_placer.py, then sends the slip to Discord.
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
sys.path.insert(0, str(SCRIPTS_DIR))
import msport_api
from vfl_live_predictor_v2 import normalize_team
from vfl_autobet_single_locks import LOCKS, send_discord_alert

STATE_FILE = Path("/home/ubuntu/.gemini/antigravity-cli/brain/751aa9ef-b0a3-4429-8498-9c8a6b4df046/power_parlay_state.json")
BET_PLACER = SCRIPTS_DIR / "browser_bet_placer.py"

def log(msg):
    full_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(full_msg, flush=True)

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"last_matchday": None, "season_id": None}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)



def main():
    state = load_state()
    try:
        mds = msport_api.get_event_list()
        if not mds:
            return
            
        target_md = msport_api.find_upcoming_match_day(mds, min_seconds=30)
        if not target_md:
            return
            
        md_num = target_md.get("matchday") or target_md.get("matchDay")
        season_id = target_md.get("seasonId") or target_md.get("season", "Unknown")
        
        # Check if already processed
        if state.get("last_matchday") == md_num and state.get("season_id") == season_id:
            return
            
        events = target_md.get("events", [])
        if not events:
            return
            
        locks_found = []
        
        for e in events:
            raw_h = e.get("homeTeam") or e.get("homeName", "")
            raw_a = e.get("awayTeam") or e.get("awayName", "")
            home = normalize_team(raw_h)
            away = normalize_team(raw_a)
            
            if (home, away) in LOCKS:
                markets = msport_api.extract_all_markets(e)
                odds = markets.get("1x2", {}).get("Home", 1.0)
                locks_found.append({
                    "home": home,
                    "away": away,
                    "market": "1", # Home Win
                    "odds": odds,
                    "conf": LOCKS[(home, away)]
                })
        
        if len(locks_found) >= 2:
            log(f"⚡ POWER MATCHDAY DETECTED! MD {md_num} has {len(locks_found)} locks.")
            
            # Construct parlay
            combined_odds = 1.0
            legs = []
            msg_lines = [f"⚡ **POWER MATCHDAY PARLAY — MD {md_num}** ⚡"]
            msg_lines.append("We found multiple historical locks! Initiating Parlay Autobet...")
            msg_lines.append("")
            
            for lock in locks_found:
                combined_odds *= lock["odds"]
                legs.append({
                    "fixture": f"{lock['home']} vs {lock['away']}",
                    "home": lock['home'],
                    "away": lock['away'],
                    "market": lock['market'],
                    "odds": lock['odds']
                })
                msg_lines.append(f"• 🟢 **{lock['home']} vs {lock['away']}** ➔ Home Win @{lock['odds']}x (Conf: {lock['conf']}%)")
                
            stake = 10.0 # Fixed parlay stake per user instruction
            ev = (1.0) * combined_odds - 1 # Rough EV, assumes ~70% win rate per leg
            
            msg_lines.append("")
            msg_lines.append(f"🔥 **Combined Odds:** {combined_odds:.2f}x")
            msg_lines.append(f"💰 **Stake:** ₦{stake:.2f}")
            msg_lines.append(f"💸 **Potential Payout:** ₦{(stake * combined_odds):.2f}")
            
            discord_msg = "\n".join(msg_lines)
            send_discord_alert(discord_msg)
            
            # Place bet
            cmd = [sys.executable, str(BET_PLACER), "parlay"]
            payload = {
                "parlay": True,
                "legs": legs,
                "stake": stake,
                "matchday": md_num
            }
            
            log(f"Submitting {len(legs)}-leg parlay to browser_bet_placer...")
            res = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
            
            if res.returncode == 0:
                try:
                    result = json.loads(res.stdout)
                    if result.get("success"):
                        success_msg = f"✅ **Parlay Placed Successfully!**\nNew Balance: ₦{result.get('balance', 'Unknown')}"
                        send_discord_alert(success_msg)
                        log(success_msg)
                    else:
                        err_msg = f"❌ **Parlay Failed to Place!**\nReason: {result.get('error', 'Unknown')}"
                        send_discord_alert(err_msg)
                        log(err_msg)
                except:
                    log(f"Browser output parsing failed: {res.stdout}")
            else:
                log(f"Browser script error: {res.stderr}")
                
        # Mark as processed
        state["last_matchday"] = md_num
        state["season_id"] = season_id
        save_state(state)
        
    except Exception as e:
        log(f"Error in power parlay: {e}")

if __name__ == "__main__":
    main()
