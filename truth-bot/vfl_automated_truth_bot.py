import time
import json
import os
import csv
import subprocess
import sys
import msport_api
from datetime import datetime

# Path definitions
LOCKS_FILE = 'oracle_locks.json'
LOG_CSV = '../data/prematch_odds_and_bets.csv'
BET_PLACER = '/home/ubuntu/faith-workspace/vfl-empire/scripts/browser_bet_placer.py'
STATE_FILE = '../data/stake_state.json'

# High-variance guard — blocks anomalies like 2.70-odds locks (verified in test_accuracy.py)
MAX_LOCK_ODDS = 1.60

def send_discord_alert(message: str):
    """Sends an alert to Discord/Telegram via Hermes."""
    try:
        # Route through Hermes to the new prediction thread
        target = "discord:1507922324072960031:1512636049585602682"
        subprocess.run(
            ["/home/ubuntu/.local/bin/hermes", "send", "--to", target, message],
            capture_output=True,
            text=True,
            check=True
        )
    except Exception as e:
        print(f"Failed to send Discord alert via Hermes CLI: {e}")

MILESTONES = [100000, 300000, 500000, 700000, 1000000]

def check_milestones(balance, bot_state):
    hit_list = bot_state.get("milestones_hit", [])
    for m in MILESTONES:
        if balance >= m and m not in hit_list:
            msg = f"🚀 **MILESTONE ALERT!** Your MSport Balance has crossed ₦{m:,}! (Current Balance: ₦{balance:,.2f}). Go withdraw!"
            print(msg)
            send_discord_alert(msg)
            hit_list.append(m)
    bot_state["milestones_hit"] = hit_list


# 1. Load the locks
if not os.path.exists(LOCKS_FILE):
    print(f"Error: {LOCKS_FILE} not found!")
    exit(1)

with open(LOCKS_FILE, 'r') as f:
    oracle_locks = json.load(f)

print(f"[{datetime.now().strftime('%H:%M:%S')}] Started Truth Engine Bot. Loaded {len(oracle_locks)} locks.")

# Ensure data directory exists
os.makedirs('../data', exist_ok=True)

# Initialize CSV log file if it doesn't exist
if not os.path.exists(LOG_CSV):
    with open(LOG_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'timestamp', 'season', 'matchday', 'home_team', 'home_tier',
            'away_team', 'away_tier', 'odds_home', 'odds_draw', 'odds_away',
            'is_lock', 'lock_outcome', 'lock_confidence', 'bet_placed',
            'bet_status', 'bet_error'
        ])

def calculate_x2_tiers(md_current):
    """Fetches X-2 standings and computes Tiers."""
    if md_current <= 2:
        # Before MD3, everyone is T0
        return {t: "T0" for t in msport_api.TEAM_ALIASES.values()}
        
    x2_md = md_current - 2
    standings_data = msport_api.get_standings(match_day=x2_md)
    if not standings_data:
        return None
        
    table = msport_api.extract_standings_table(standings_data)
    
    tiers = {}
    for i, row in enumerate(table):
        team = row['teamName']
        if i < 4: tiers[team] = 'T1'
        elif i < 8: tiers[team] = 'T2'
        elif i < 12: tiers[team] = 'T3'
        else: tiers[team] = 'T4'
        
    return tiers

def log_to_csv(row_data):
    """Safely appends a row to the log CSV."""
    try:
        with open(LOG_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row_data)
    except Exception as e:
        print(f"Error logging to CSV: {e}")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        "state": "IDLE",
        "current_stake": 150.0,
        "pending_return": 0.0,
        "target_balance": 0.0,
        "waiting_since_md": 0,
        "milestones_hit": []
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

def check_balance():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking balance for settlement...")
    cmd = [sys.executable, BET_PLACER, "balance"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(res.stdout.strip())
        if data.get("success"):
            raw_bal = data.get("balance", "0")
            import re
            clean_bal_str = re.sub(r'[^\d.]', '', str(raw_bal))
            return float(clean_bal_str) if clean_bal_str else 0.0
    except Exception as e:
        print(f"Failed to check balance: {e}")
    return None

def run_loop():
    last_processed = None  # Tuple of (season, target_md)
    bot_state = load_state()
    
    while True:
        try:
            # Get current match day info
            info = msport_api.get_current_match_day_info()
            if not info:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for MSport API/Network...")
                time.sleep(10)
                continue
                
            current_md = info.get("matchDay")
            season = info.get("seasonName")
            
            # Fetch event list
            events_data = msport_api.get_event_list()
            if not events_data:
                time.sleep(10)
                continue
                
            # Find the upcoming matchday
            upcoming = msport_api.find_upcoming_match_day(events_data, min_seconds=10)
            if not upcoming:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] MD {current_md} in progress... waiting for next betting window.")
                time.sleep(10)
                continue
                
            target_md = upcoming.get("matchDay")
            
            # If we already processed this matchday, skip
            if last_processed == (season, target_md):
                time.sleep(5)
                continue
                
            print(f"\n==================================================")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] NEW BETTING WINDOW: SEASON {season} | TARGET MD: {target_md}")
            print(f"==================================================")
            
            # Dynamic Tiers from X-2 form standings
            tiers = calculate_x2_tiers(target_md)
            if not tiers:
                print("Failed to calculate tiers. Retrying in next check.")
                time.sleep(10)
                continue
                
            # If waiting for settlement, check balance
            if bot_state["state"] == "WAITING":
                # Ensure at least 2 matchdays have passed since the bet was placed to allow MSport settlement delays
                waiting_since = bot_state.get("waiting_since_md", 0)
                wait_time = target_md - waiting_since
                if wait_time < 0:
                    wait_time += 30 # Season wrap around (30 matchdays per season)
                    
                if wait_time >= 2:
                    current_bal = check_balance()
                    if current_bal is not None:
                        check_milestones(current_bal, bot_state)
                        print(f"Current Balance: ₦{current_bal} | Target Balance: ₦{bot_state['target_balance']}")
                        # Allow a small floating point margin (e.g., 0.1)
                        if current_bal >= bot_state["target_balance"] - 0.1:
                            print(f"✅ BET WON! Adding profit. Next Stake will be ₦{bot_state['pending_return']:.2f}")
                            bot_state["current_stake"] = bot_state["pending_return"]
                        else:
                            fallback_stake = min(100.0, current_bal) if current_bal > 0 else 100.0
                            print(f"❌ BET LOST! Resetting stake to ₦{fallback_stake:.2f}")
                            bot_state["current_stake"] = fallback_stake
                            
                        bot_state["state"] = "IDLE"
                        bot_state["pending_return"] = 0.0
                        bot_state["target_balance"] = 0.0
                        save_state(bot_state)
                    else:
                        print("Could not fetch balance. Will retry next tick.")
                        time.sleep(10)
                        continue
                else:
                    print(f"Still waiting for MD {target_md} to finish before checking settlement.")
                    # We can still process matches just for logging, but we won't bet.
                    
            events = upcoming.get("events", [])
            
            for ev in events:
                home = msport_api._normalise_team_name(ev.get("homeTeam", ""))
                away = msport_api._normalise_team_name(ev.get("awayTeam", ""))
                
                home_tier = tiers.get(home, 'T0')
                away_tier = tiers.get(away, 'T0')
                
                # Format fingerprint exactly as keyed in oracle_locks.json
                fingerprint = f"MD{target_md} | {home}({home_tier}) vs {away}({away_tier})"
                
                markets = msport_api.extract_all_markets(ev)
                odds = markets.get("1x2", {})
                odds_home = odds.get('Home', 0.0)
                odds_draw = odds.get('Draw', 0.0)
                odds_away = odds.get('Away', 0.0)
                
                is_lock = fingerprint in oracle_locks
                lock_outcome = ""
                lock_confidence = ""
                bet_placed = False
                bet_status = "N/A"
                bet_error = ""
                
                if is_lock:
                    lock = oracle_locks[fingerprint]
                    lock_outcome = lock['outcome']
                    lock_confidence = lock['confidence']
                    
                    print(f"\n🚨🚨🚨 ORACLE LOCK FOUND! 🚨🚨🚨")
                    print(f"Match: {home} ({home_tier}) vs {away} ({away_tier})")
                    print(f"Guaranteed Outcome: {lock_outcome} ({lock_confidence})")
                    print(f"Pre-Match Odds: Home {odds_home} | Draw {odds_draw} | Away {odds_away}")
                    
                    # Map outcome to placer selection
                    outcome_map = {
                        "HOME WIN": "1",
                        "AWAY WIN": "2",
                        "DRAW": "X"
                    }
                    placer_market = outcome_map.get(lock_outcome)
                    
                    if placer_market:
                        if bot_state["state"] == "WAITING":
                            print(f"Skipping bet because we are waiting for a previous bet to settle.")
                            continue

                        odds_to_use = odds_home if placer_market == "1" else (odds_away if placer_market == "2" else odds_draw)

                        if not odds_to_use or float(odds_to_use) >= MAX_LOCK_ODDS:
                            print(f"⏭️ Skipping bet: odds {odds_to_use} >= {MAX_LOCK_ODDS} (high-variance guard).")
                            bet_status = "FILTERED_ODDS"
                            bet_error = f"Odds {odds_to_use} >= {MAX_LOCK_ODDS}"
                        else:
                            stake = bot_state["current_stake"]
                            print(f"Placing ₦{stake:.2f} bet via Browser Bet Placer...")

                            payload = {
                                "parlay": False,
                                "legs": [{
                                    "fixture": f"{home} vs {away}",
                                    "home": home,
                                    "away": away,
                                    "market": placer_market,
                                    "odds": odds_to_use
                                }],
                                "stake": stake,
                                "matchday": target_md
                            }

                            cmd = [sys.executable, BET_PLACER, "bet", json.dumps(payload)]
                            try:
                                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                                try:
                                    res_data = json.loads(res.stdout.strip())
                                    if res_data.get("success"):
                                        bet_placed = True
                                        bet_status = "SUCCESS"

                                        raw_bal = res_data.get('balance', '0')
                                        import re
                                        clean_bal_str = re.sub(r'[^\d.]', '', str(raw_bal))
                                        current_bal = float(clean_bal_str) if clean_bal_str else 0.0

                                        expected_return = stake * float(odds_to_use)

                                        bot_state["state"] = "WAITING"
                                        bot_state["waiting_since_md"] = target_md
                                        bot_state["pending_return"] = expected_return
                                        bot_state["target_balance"] = current_bal + expected_return
                                        save_state(bot_state)

                                        print(f"✅ Bet Placed Successfully! Balance info: {raw_bal}")
                                        print(f"Expected Return: ₦{expected_return:.2f}. Target Balance: ₦{bot_state['target_balance']:.2f}")
                                    else:
                                        bet_status = "FAILED"
                                        bet_error = res_data.get("error", "Unknown placement failure")
                                        print(f"❌ Bet Placement Failed: {bet_error}")
                                except Exception as json_err:
                                    bet_status = "ERROR"
                                    bet_error = f"JSON Parse error of browser output: {json_err}"
                                    print(f"❌ Error parsing bet placer output: {json_err}")
                                    print("Raw STDOUT:", res.stdout)
                                    if res.stderr:
                                        print("Raw STDERR:", res.stderr)
                            except subprocess.TimeoutExpired:
                                bet_status = "TIMEOUT"
                                bet_error = "Browser bet placer subprocess timed out (120s limit)"
                                print("❌ Timeout executing browser bet placer.")
                            except Exception as e:
                                bet_status = "ERROR"
                                bet_error = str(e)
                                print(f"❌ Error executing browser bet placer: {e}")
                    else:
                        print(f"⚠️ Warning: Unknown outcome type {lock_outcome}. Cannot place bet.")
                        bet_status = "UNKNOWN_OUTCOME"
                
                # Log this fixture's details and betting result to CSV
                log_to_csv([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    season,
                    target_md,
                    home,
                    home_tier,
                    away,
                    away_tier,
                    odds_home,
                    odds_draw,
                    odds_away,
                    is_lock,
                    lock_outcome,
                    lock_confidence,
                    bet_placed,
                    bet_status,
                    bet_error
                ])
            
            # Mark this matchday as fully processed
            last_processed = (season, target_md)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Finished processing all matches for Season {season} | MD {target_md}.\n")
            
        except Exception as e:
            print(f"Error in daemon loop iteration: {e}")
            
        time.sleep(10)

if __name__ == "__main__":
    try:
        run_loop()
    except KeyboardInterrupt:
        print("\nTruth Bot stopped by user.")
