#!/usr/bin/env python3
"""
vfl_autobet_1x_beast.py
===========================
The Official Auto-Bet Daemon for the 1X Beast Strategy (Tier 1/2 vs Tier 3).
- Targets ONLY Tier 1 or Tier 2 (Home) vs Tier 3 (Away).
- Always bets 1X (Double Chance).
- Implements 30% Fractional Kelly Bankroll Management.
- Runs continuously, places bets via browser, waits for settlement, updates bank.
"""

import time
import json
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
sys.path.insert(0, str(SCRIPTS_DIR))
import msport_api

def send_discord_alert(message: str):
    try:
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
STATE_FILE = Path("/home/ubuntu/.gemini/antigravity-cli/brain/autobet_1x_state.json")
BET_PLACER = SCRIPTS_DIR / "browser_bet_placer.py"
TIERS_JSON = SCRIPTS_DIR / "intrinsic_tiers.json"

def get_team_tiers():
    team_tiers = {}
    if TIERS_JSON.exists():
        with open(TIERS_JSON, "r") as f:
            tiers_data = json.load(f)
            for team, val in tiers_data.items():
                team_tiers[team] = int(val[1])
    return team_tiers

def log(msg):
    full_msg = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(full_msg, flush=True)
    if "🎯" in msg or "🎉" in msg or "❌" in msg or "🚀" in msg or "🔥" in msg:
        send_discord_alert(msg)

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "bankroll": 3000.0,
        "current_stake": 10.0,
        "last_bet": None,
        "history": [],
        "total_profit": 0.0,
        "wins": 0,
        "losses": 0
    }

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def calculate_kelly_stake(bankroll, dc_odds):
    """25% Fractional Kelly, hit rate 84.9%"""
    if dc_odds <= 1.0: return 10.0
    p = 0.849
    q = 1 - p
    b = dc_odds - 1.0
    f_star = (b * p - q) / b
    if f_star <= 0: return 10.0
    stake = bankroll * (f_star * 0.25)
    return max(10.0, min(stake, bankroll * 0.50)) # Cap at 50%

def place_bet_via_browser(home, away, market, odds, stake, md_num):
    log(f"🤖 Instructing browser to place: {home} vs {away} | {market} @ {odds}x | Stake: ₦{stake:.2f}")
    cmd = [sys.executable, str(BET_PLACER), "bet"]
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
        res = subprocess.run(cmd, input=json.dumps(input_data), capture_output=True, text=True, timeout=120)
        if res.stderr.strip():
            log(f"Browser logs: {res.stderr.strip()}")
        if res.returncode != 0:
            log(f"⚠️ Browser placement error: {res.stderr.strip()}")
            return False
        out = json.loads(res.stdout.strip())
        if out.get("success"):
            log(f"✅ Bet successfully placed on MSport!")
            return out
        else:
            log(f"❌ Bet failed: {out.get('error')}")
            return {"success": False, "error": out.get("error")}
    except Exception as e:
        log(f"⚠️ Exception running browser placer: {e}")
        return {"success": False, "error": str(e)}

def check_settlement(state):
    bet = state.get("last_bet")
    if not bet: return
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
            won = False
            if bet["market"] == "1X":
                won = (hg >= ag) # Home win or draw
            
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
            
            bet["won"] = won
            bet["hg"] = hg
            bet["ag"] = ag
            bet["profit"] = profit if won else -bet["stake"]
            state["history"].append(bet)
            state["last_bet"] = None
            save_state(state)
            return
    log("   Match not found in results yet.")

def calculate_dc_odds(hw, dw, aw):
    if not hw or not dw or not aw: return 0.0
    try:
        home_p = 1 / float(hw)
        draw_p = 1 / float(dw)
        prob = home_p + draw_p
        return (1 / prob) * 0.95
    except:
        return 0.0

def calculate_form_score(form_list):
    if not form_list: return 1.0 # Default if matchday 1
    score_map = {'W': 1.0, 'D': 0.33, 'L': 0.0}
    return sum(score_map.get(res, 0.0) for res in form_list) / len(form_list)

def run_loop():
    log("🚀 Autobet 1X Beast Daemon Started. Strategy: Tier 1/2 Home vs Tier 3 Away.")
    state = load_state()
    team_tiers = get_team_tiers()
    
    # Sync initial balance from MSport
    log("🔄 Syncing real bank balance from MSport...")
    try:
        res = subprocess.run([sys.executable, str(BET_PLACER), "balance"], capture_output=True, text=True, timeout=60)
        out = json.loads(res.stdout.strip())
        if out.get("success"):
            bal_str = str(out["balance"]).replace("NGN", "").replace(",", "").strip()
            state["bankroll"] = float(bal_str)
            save_state(state)
            log(f"💰 Initial synced bankroll: ₦{state['bankroll']:.2f}")
        else:
            log(f"⚠️ Failed to sync balance: {out.get('error')}. Using saved balance: ₦{state.get('bankroll', 3000.0):.2f}")
    except Exception as e:
        log(f"⚠️ Exception syncing balance: {e}")
    
    while True:
        try:
            current_br = state.get("bankroll", 3000.0)
            if current_br <= 1800.0:  # 60% stop loss of the original ₦3000
                log("🚨 STOP LOSS TRIGGERED: Bankroll has dropped to or below 60% (₦1800). HALTING BEAST DAEMON.")
                time.sleep(3600) # Sleep for an hour and stop betting
                continue
                
            if state.get("last_bet"):
                check_settlement(state)
                if state.get("last_bet"):
                    time.sleep(30)
                    continue
            
            info = msport_api.get_current_match_day_info()
            if not info:
                time.sleep(15)
                continue
            season_id = info.get("seasonId")
            
            events_data = msport_api.get_event_list()
            if not events_data:
                time.sleep(15)
                continue
                
            upcoming = msport_api.find_upcoming_match_day(events_data, min_seconds=90)
            if not upcoming:
                time.sleep(15)
                continue
                
            md_num = upcoming.get("matchDay")
            events = upcoming.get("events", [])
            
            # Get Standings to calculate Form Score
            standings_data = msport_api.get_standings(season_id)
            standings = standings_data.get("standings", []) if standings_data else []
            team_forms = {}
            for t in standings:
                name = msport_api._normalise_team_name(t.get("teamName", ""))
                form_list = t.get("lastFive", []) or t.get("form", [])
                team_forms[name] = calculate_form_score(form_list)
            
            # Find eligible matches
            available_locks = []
            for ev in events:
                h = msport_api._normalise_team_name(ev.get("homeTeam", ""))
                a = msport_api._normalise_team_name(ev.get("awayTeam", ""))
                h_tier = team_tiers.get(h, 4)
                a_tier = team_tiers.get(a, 4)
                
                # Check Strategy: Tier 1/2 Home vs Tier 3 Away
                if h_tier in [1, 2] and a_tier == 3:
                    # NEW HIGH-ACCURACY FILTER: Check Home Form Score
                    home_form = team_forms.get(h, 1.0)
                    if home_form < 0.50:
                        log(f"   ⏩ Skipping {h} vs {a} - Home form too low ({home_form:.2f})")
                        continue
                    markets = ev.get("markets", [])
                    hw, dw, aw = msport_api.extract_1x2_odds(markets)
                    if hw and dw and aw:
                        dc_odds = calculate_dc_odds(hw, dw, aw)
                        if dc_odds > 0:
                            available_locks.append({
                                "home": h,
                                "away": a,
                                "odds": dc_odds
                            })
            
            if not available_locks:
                time.sleep(15)
                continue
                
            best_lock = max(available_locks, key=lambda x: x["odds"])
            stake = calculate_kelly_stake(current_br, best_lock["odds"])
            
            log(f"🎯 1X BEAST MATCH FOUND: {best_lock['home']} vs {best_lock['away']} | Odds: {best_lock['odds']:.2f} | Stake: ₦{stake:.2f}")
            
            res = place_bet_via_browser(
                home=best_lock["home"],
                away=best_lock["away"],
                market="1X",
                odds=best_lock["odds"],
                stake=stake,
                md_num=md_num
            )
            
            if res.get("success"):
                raw_bal = res.get("balance", current_br)
                if isinstance(raw_bal, str):
                    bal_str = raw_bal.replace("NGN", "").replace(",", "").strip()
                    new_bal = float(bal_str)
                else:
                    new_bal = float(raw_bal)
                state["bankroll"] = new_bal
                state["last_bet"] = {
                    "season_id": season_id,
                    "matchday": md_num,
                    "home": best_lock["home"],
                    "away": best_lock["away"],
                    "market": "1X",
                    "odds": best_lock["odds"],
                    "stake": stake
                }
                save_state(state)
                log(f"💰 Bet Placed! New Bank Balance: ₦{new_bal:.2f}", to_discord=True)
                time.sleep(60) # Wait for matchday to advance
            else:
                log("⚠️ Browser failed to place bet. Retrying next tick...")
                time.sleep(20)
                
        except Exception as e:
            log(f"🔥 Critical Daemon Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    run_loop()
