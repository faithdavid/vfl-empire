import time
import json
import logging
import sys
import os
import subprocess
import pandas as pd
from datetime import datetime

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from msport_api import get_current_match_day_info, get_standings, get_event_list, extract_standings_table

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("GoalSniperBot")

PILLARS_PATH = '/home/ubuntu/faith-workspace/vfl-empire/data/goal_pillars.json'
BET_PLACER_PATH = '/home/ubuntu/faith-workspace/vfl-empire/scripts/browser_bet_placer.py'
STATE_FILE = '/home/ubuntu/faith-workspace/vfl-empire/data/goal_sniper_state.json'

MIN_OCCURRENCES = 100
REQUIRED_CONFIDENCE = "100%"

def load_state():
    default_state = {
        "cycle_step": 0,
        "banked_amount": 0.0,
        "last_bet_md": None,
        "last_bet_season": None
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                for k, v in default_state.items():
                    if k not in state:
                        state[k] = v
                return state
        except Exception as e:
            log.warning(f"Failed to parse state file, using defaults: {e}")
    return default_state

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

def get_msport_balance():
    try:
        result = subprocess.run(["python3", BET_PLACER_PATH, "balance"], capture_output=True, text=True)
        out = result.stdout.strip()
        if out:
            data = json.loads(out.splitlines()[-1])
            if data.get("success") and "balance" in data:
                # Handle possible string formatting with commas and NGN
                bal_str = str(data["balance"]).replace(',', '').replace('NGN ', '').replace('₦', '').strip()
                return float(bal_str)
    except Exception as e:
        log.error(f"Failed to fetch MSport balance: {e}")
    return None

try:
    with open(PILLARS_PATH, 'r') as f:
        pillars_list = json.load(f)
    ELITE_PILLARS = {}
    count = 0
    for p in pillars_list:
        if p['confidence'] == REQUIRED_CONFIDENCE and p['occurrences'] >= MIN_OCCURRENCES:
            key = (p['home'], p['away'], p['home_tier'], p['away_tier'])
            if key not in ELITE_PILLARS:
                ELITE_PILLARS[key] = p
                count += 1
    log.info(f"Loaded {count} ELITE 100% Goal Pillars (Min 100 Occurrences).")
except Exception as e:
    log.error(f"Failed to load pillars: {e}")
    sys.exit(1)

def get_tiers_from_live_standings(season_id, target_md):
    try:
        raw_standings = get_standings(season_id=season_id, match_day=target_md)
        if not raw_standings: return None
        table = extract_standings_table(raw_standings)
        if not table: return None
        
        df = pd.DataFrame(table)
        df.sort_values(['points', 'goalDifference', 'goalsFor'], ascending=[False, False, False], inplace=True)
        df['rank'] = range(1, len(df) + 1)
        df['tier'] = pd.cut(df['rank'], bins=[0, 4, 8, 12, 16], labels=['T1', 'T2', 'T3', 'T4'])
        return dict(zip(df['teamName'], df['tier']))
    except Exception as e:
        log.error(f"Error fetching live standings: {e}")
        return None

def execute_parlay(legs, target_md, stake):
    payload = {
        "stake": stake,
        "target_md": target_md,
        "legs": legs
    }
    log.info(f"Executing Parlay with {len(legs)} legs at ₦{stake:.2f} via Browser Placer...")
    try:
        result = subprocess.run(
            ["python3", BET_PLACER_PATH, "parlay", json.dumps(payload)],
            capture_output=True, text=True, check=False
        )
        for line in result.stderr.splitlines():
            if "INFO" in line or "ERROR" in line:
                log.info(f"[Browser] {line}")
                
        out = result.stdout.strip()
        if out:
            res_json = json.loads(out.splitlines()[-1])
            return res_json.get("success", False)
    except Exception as e:
        log.error(f"Execution error: {e}")
    return False

def main_loop():
    log.info("🎯 Starting VFL Goal Sniper Bot (6-Cycle Compounding / 30% Base Stake)...")
    state = load_state()
    
    while True:
        try:
            info = get_current_match_day_info()
            if not info:
                time.sleep(10)
                continue
                
            season = info.get('seasonName')
            season_id = info.get('seasonId')
            current_md = info.get('matchDay')
            
            matchdays = get_event_list()
            if not matchdays:
                time.sleep(10)
                continue
                
            target_md = matchdays[0].get('matchDay')
            events = matchdays[0].get('events', [])
            
            if state['last_bet_season'] == season and state['last_bet_md'] == target_md:
                time.sleep(20)
                continue
                
            lagged_md = target_md - 1
            if lagged_md < 1:
                time.sleep(20)
                continue
                
            tier_map = get_tiers_from_live_standings(season_id, lagged_md)
            if not tier_map:
                time.sleep(10)
                continue
                
            legs = []
            for ev in events:
                home = ev.get('homeTeam')
                away = ev.get('awayTeam')
                h_tier = tier_map.get(home)
                a_tier = tier_map.get(away)
                
                if not h_tier or not a_tier: continue
                key = (home, away, h_tier, a_tier)
                
                if key in ELITE_PILLARS:
                    pillar = ELITE_PILLARS[key]
                    legs.append({
                        "home": home,
                        "away": away,
                        "market": pillar['market']
                    })
                    
            if len(legs) > 0:
                log.info(f"🚨 FOUND {len(legs)} ELITE PILLARS for MD {target_md}. Preparing to place...")
                
                # Dynamic Stake Calculation based on Real Wallet Balance
                bal = get_msport_balance()
                if bal is None:
                    log.error("Failed to fetch balance. Aborting this placement.")
                    time.sleep(10)
                    continue
                    
                log.info(f"Current MSport Balance: ₦{bal:,.2f}")
                
                # Check if previous bet lost or if cycle is broken
                # If bal <= state['banked_amount'], it means we lost our staked amount
                if bal <= state.get('banked_amount', 0.0) + 1.0: # 1 Naira buffer
                    if state['cycle_step'] > 0:
                        log.warning("Previous bet lost or balance withdrew. Resetting cycle.")
                    state['cycle_step'] = 0
                
                if state['cycle_step'] == 0:
                    stake = max(10.0, bal * 0.30)
                    state['banked_amount'] = bal - stake
                    log.info(f"🔄 STARTING CYCLE 1/6 | Staking 30% of ₦{bal:,.2f} -> ₦{stake:,.2f}")
                else:
                    stake = max(10.0, bal - state['banked_amount'])
                    log.info(f"🔥 COMPOUNDING CYCLE {state['cycle_step']+1}/6 | Banked: ₦{state['banked_amount']:,.2f} | Staking: ₦{stake:,.2f}")

                success = execute_parlay(legs, target_md, stake)
                
                state['last_bet_season'] = season
                state['last_bet_md'] = target_md
                
                if success:
                    log.info("✅ Parlay Successfully Placed!")
                    state['cycle_step'] += 1
                    if state['cycle_step'] >= 6:
                        log.info("🎉 6-CYCLE COMPLETED! Resetting to base stake for next target.")
                        state['cycle_step'] = 0
                        # banked amount will be recalculated on next bet
                else:
                    log.error("❌ Failed to place parlay.")
                    # Keep same cycle step so it tries again, or reset?
                    # Let's not reset cycle step if it was a placement failure (not a loss)
                    pass
                    
                save_state(state)
            else:
                # Silently mark as checked so we don't loop it
                state['last_bet_season'] = season
                state['last_bet_md'] = target_md
                save_state(state)
                
            time.sleep(20)
            
        except KeyboardInterrupt:
            log.info("Bot shutting down...")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    main_loop()
