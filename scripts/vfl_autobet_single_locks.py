#!/usr/bin/env python3
"""
vfl_autobet_single_locks.py
===========================
The Official Auto-Bet Daemon for the 39-Fixture Lock Strategy.
- Targets ONLY the 39 proven historical lock fixtures (≥65% Home Win rate).
- Always bets SINGLE Home Win (1 leg).
- Implements Compound Bankroll Management starting at ₦10 (2% compounding).
- Runs continuously, places bets via browser, waits for settlement, updates bank.
"""

import time
import json
import os
import sys
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
sys.path.insert(0, str(SCRIPTS_DIR))
import msport_api

def send_discord_alert(message: str):
    """Sends an alert to Discord using hermes CLI directly as requested."""
    try:
        # Route through Hermes to the new prediction thread
        # Thread: 1507922324072960031:1512636049585602682
        target = "discord:1507922324072960031:1512636049585602682"
        subprocess.run(
            ["/home/ubuntu/.local/bin/hermes", "send", "--to", target, message],
            capture_output=True,
            text=True,
            check=True
        )
    except Exception as e:
        print(f"Failed to send Discord alert via Hermes CLI: {e}")

# State and Logging
STATE_FILE = Path("/home/ubuntu/.gemini/antigravity-cli/brain/751aa9ef-b0a3-4429-8498-9c8a6b4df046/autobet_locks_state.json")
BET_PLACER = SCRIPTS_DIR / "browser_bet_placer.py"

# The 39 Lock Fixtures (Home, Away, HW%)
LOCKS = {
    ("Manchester Red", "Crystal Palace"): 83.0,
    ("Chelsea", "Bournemouth"): 82.5,
    ("Liverpool", "Bournemouth"): 82.4,
    ("Manchester Blue", "Fulham"): 82.4,
    ("Manchester Blue", "Crystal Palace"): 79.4,
    ("Chelsea", "Crystal Palace"): 78.8,
    ("Manchester Red", "Leeds"): 78.6,
    ("Manchester Red", "Fulham"): 77.9,
    ("Manchester Blue", "Leeds"): 77.5,
    ("Manchester Blue", "Bournemouth"): 75.5,
    ("Chelsea", "Fulham"): 75.0,
    ("Liverpool", "Wolverhampton"): 74.8,
    ("Tottenham", "Bournemouth"): 74.8,
    ("Chelsea", "Newcastle"): 74.3,
    ("Liverpool", "Fulham"): 74.3,
    ("Manchester Red", "Newcastle"): 74.3,
    ("Manchester Blue", "Newcastle"): 74.0,
    ("Manchester Blue", "Everton"): 73.8,
    ("London Guns", "Fulham"): 73.5,
    ("Tottenham", "Newcastle"): 73.5,
    ("Liverpool", "Newcastle"): 73.3,
    ("Liverpool", "Crystal Palace"): 72.8,
    ("Manchester Red", "Bournemouth"): 72.8,
    ("Aston Villa", "Crystal Palace"): 72.5,
    ("London Guns", "Bournemouth"): 72.0,
    ("Aston Villa", "Fulham"): 71.6,
    ("Aston Villa", "Bournemouth"): 70.9,
    ("Manchester Blue", "Wolverhampton"): 70.9,
    ("Chelsea", "Leeds"): 69.3,
    ("Manchester Red", "Wolverhampton"): 68.6,
    ("Tottenham", "Wolverhampton"): 68.3,
    ("Chelsea", "Wolverhampton"): 67.6,
    ("London Guns", "Crystal Palace"): 67.3,
    ("Tottenham", "Crystal Palace"): 67.3,
    ("London Guns", "Wolverhampton"): 67.0,
    ("Liverpool", "Leeds"): 66.7,
    ("Tottenham", "Fulham"): 65.4,
    ("Manchester Red", "Brighton"): 65.3,
    ("Manchester Red", "Everton"): 65.0,
}

def log(msg):
    full_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(full_msg, flush=True)
    
    # Forward critical events to Discord
    if "🎯" in msg or "🎉" in msg or "❌" in msg or "🚀" in msg or "🔥" in msg:
        send_discord_alert(msg)

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    # Starting configuration: ₦10 base, tracking bankroll and bets
    return {
        "bankroll": 500.0, # Simulated starting tracking bankroll to drive the 2% stake rule
        "current_stake": 10.0,
        "last_bet": None, # Tracks if we are waiting for a settlement
        "history": [],
        "total_profit": 0.0,
        "wins": 0,
        "losses": 0
    }

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def calculate_stake(bankroll):
    """2% compound, minimum ₦10"""
    stake = round(bankroll * 0.02, 2)
    return max(10.0, stake)

def place_bet_via_browser(home, away, market, odds, stake, md_num):
    log(f"🤖 Instructing browser to place: {home} vs {away} | {market} @ {odds}x | Stake: ₦{stake}")
    cmd = [
        sys.executable, str(BET_PLACER), "bet"
    ]
    input_data = {
        "parlay": False,
        "legs": [{
            "fixture": f"{home} vs {away}",
            "home": home,
            "away": away,
            "market": market,
            "odds": odds,
        }],
        "stake": stake,
        "matchday": md_num,
    }
    
    try:
        res = subprocess.run(
            cmd, input=json.dumps(input_data),
            capture_output=True, text=True, timeout=120
        )
        
        if res.returncode != 0:
            log(f"⚠️ Browser placement error: {res.stderr.strip()}")
            return False
            
        out = json.loads(res.stdout.strip())
        if out.get("success"):
            log(f"✅ Bet successfully placed on MSport!")
            return True
        else:
            log(f"❌ Bet failed: {out.get('error')}")
            log(f"Browser stderr: {res.stderr.strip()}")
            return False
            
    except Exception as e:
        log(f"⚠️ Exception running browser placer: {e}")
        return False

def check_settlement(state):
    bet = state.get("last_bet")
    if not bet:
        return
        
    log(f"🔄 Checking settlement for MD {bet['matchday']} ({bet['home']} vs {bet['away']})...")
    
    results = msport_api.get_results(bet["season_id"], bet["matchday"])
    if not results:
        log("   Results not yet available. Waiting...")
        return
        
    for r in results:
        h = msport_api._normalise_team_name(r.get("homeTeam", ""))
        a = msport_api._normalise_team_name(r.get("awayTeam", ""))
        if h == bet["home"] and a == bet["away"]:
            hg, ag = map(int, str(r.get("fullTime", "0:0")).split(":"))
            
            won = (hg > ag) # We always bet Home Win
            
            if won:
                profit = round((bet["stake"] * bet["odds"]) - bet["stake"], 2)
                state["bankroll"] += profit
                state["total_profit"] += profit
                state["wins"] += 1
                log(f"🎉 WON! {h} {hg}-{ag} {a} | +₦{profit:.2f} | Bankroll: ₦{state['bankroll']:.2f}")
            else:
                state["bankroll"] -= bet["stake"]
                state["total_profit"] -= bet["stake"]
                state["losses"] += 1
                log(f"❌ LOST. {h} {hg}-{ag} {a} | -₦{bet['stake']:.2f} | Bankroll: ₦{state['bankroll']:.2f}")
            
            # Recalculate next stake
            state["current_stake"] = calculate_stake(state["bankroll"])
            
            # Archive
            bet["won"] = won
            bet["hg"] = hg
            bet["ag"] = ag
            bet["profit"] = profit if won else -bet["stake"]
            state["history"].append(bet)
            state["last_bet"] = None
            save_state(state)
            return

    log("   Match not found in results yet.")

def run_loop():
    log("🚀 Autobet Daemon Started. Strategy: Single 39-Locks Compounding.")
    state = load_state()
    log(f"💰 Starting Bankroll (Virtual Tracker): ₦{state['bankroll']:.2f} | Next Stake: ₦{state['current_stake']:.2f}")
    
    while True:
        try:
            # 1. Check pending settlements
            if state.get("last_bet"):
                check_settlement(state)
                if state.get("last_bet"):
                    time.sleep(30) # Still waiting
                    continue
            
            # 2. Get upcoming fixtures
            info = msport_api.get_current_match_day_info()
            if not info:
                time.sleep(15)
                continue
                
            season_id = info.get("seasonId")
            
            events_data = msport_api.get_event_list()
            if not events_data:
                time.sleep(15)
                continue
                
            upcoming = msport_api.find_upcoming_match_day(events_data, min_seconds=45)
            if not upcoming:
                log("⏳ Waiting for next open matchday...")
                time.sleep(15)
                continue
                
            md_num = upcoming.get("matchDay")
            events = upcoming.get("events", [])
            
            # 3. Find locks
            available_locks = []
            for ev in events:
                h = msport_api._normalise_team_name(ev.get("homeTeam", ""))
                a = msport_api._normalise_team_name(ev.get("awayTeam", ""))
                
                if (h, a) in LOCKS:
                    # Get 1X2 odds
                    markets = msport_api.extract_all_markets(ev)
                    hw_odds = markets.get("1x2", {}).get("Home", 0.0)
                    
                    if hw_odds > 1.01:
                        available_locks.append({
                            "home": h,
                            "away": a,
                            "conf": LOCKS[(h, a)],
                            "odds": hw_odds
                        })
            
            if not available_locks:
                log(f"MD {md_num}: No lock fixtures playing. Skipping.")
                time.sleep(30)
                continue
                
            # 4. Pick highest confidence
            available_locks.sort(key=lambda x: x["conf"], reverse=True)
            best_lock = available_locks[0]
            
            # Avoid placing duplicate bets
            history_keys = [f"{b['season_id']}_{b['matchday']}" for b in state.get("history", [])]
            current_key = f"{season_id}_{md_num}"
            if current_key in history_keys:
                time.sleep(30)
                continue
                
            log(f"🎯 MD {md_num} Lock Found! {best_lock['home']} vs {best_lock['away']} ({best_lock['conf']}%) @ {best_lock['odds']}x")
            
            stake = state.get("current_stake", 10.0)
            
            # Place the bet
            success = place_bet_via_browser(
                home=best_lock["home"],
                away=best_lock["away"],
                market="1",
                odds=best_lock["odds"],
                stake=stake,
                md_num=md_num
            )
            
            if success:
                state["last_bet"] = {
                    "season_id": season_id,
                    "matchday": md_num,
                    "home": best_lock["home"],
                    "away": best_lock["away"],
                    "odds": best_lock["odds"],
                    "stake": stake,
                    "conf": best_lock["conf"],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                save_state(state)
                log("💤 Sleeping for 3 mins until settlement...")
                time.sleep(180) # Matches take 3 mins
            else:
                log("⚠️ Retrying on next tick...")
                time.sleep(20)
                
        except Exception as e:
            log(f"🔥 Critical Daemon Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    run_loop()
