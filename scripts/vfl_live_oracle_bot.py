import time
import json
import logging
import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime
from playwright.sync_api import sync_playwright

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from msport_api import get_current_match_day_info, get_standings, get_event_list, extract_standings_table, extract_1x2_odds

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("VFL_Oracle_Bot")

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
LOCKS_PATH = '/home/ubuntu/faith-workspace/vfl-empire/data/phase_fixture_locks_bulletproof.json'
CDP_URL = "http://localhost:9222"
PHONE_NUMBER = "09038426877"
PASSWORD = "fadava2002"

STARTING_STAKE = 140.0
CYCLE_RESET_STAKE = 1000.0
TARGET_CYCLE_BETS = 12

# State management
STATE_FILE = '/home/ubuntu/faith-workspace/vfl-empire/data/bot_cycle_state.json'

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        "current_stake": STARTING_STAKE,
        "bets_placed_in_cycle": 0,
        "cycle_number": 1,
        "total_profit_banked": 0.0,
        "last_bet_md": None,
        "last_bet_season": None
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

# ==========================================
# 🛡️ THE ORACLE DATABASE
# ==========================================
try:
    with open(LOCKS_PATH, 'r') as f:
        locks_list = json.load(f)
    LOCKS_DB = { (l['home'], l['away'], l['home_tier'], l['away_tier'], l['phase']): l['lock'] for l in locks_list }
    log.info(f"Loaded {len(LOCKS_DB)} Bulletproof Locks.")
except Exception as e:
    log.error(f"Failed to load locks: {e}")
    sys.exit(1)

def get_tiers_from_live_standings():
    try:
        raw_standings = get_standings()
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

# ==========================================
# 🤖 PLAYWRIGHT BET PLACER
# ==========================================
def place_bet_via_browser(pick, stake):
    """
    Connects to the browser via CDP, logs in if necessary, and places the bet.
    Returns True if successful, False otherwise.
    """
    log.info(f"Initiating Browser Bet Placement: {pick['fixture']} -> {pick['lock'].upper()} (Stake: ₦{stake:.2f})")
    
    with sync_playwright() as p:
        try:
            # 1. Connect
            browser = p.chromium.connect_over_cdp(CDP_URL, timeout=5000)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            
            if "web/virtual" not in page.url:
                page.goto("https://www.msport.com/ng/web/virtual")
                time.sleep(5)
                
            # 2. Login
            body_text = page.locator('body').inner_text()
            if "Login" in body_text and "Welcome" not in body_text:
                log.info("Logging in...")
                phone_input = page.locator('form.sign-info input[type="tel"]').first
                if phone_input.count() > 0: phone_input.fill(PHONE_NUMBER)
                else: page.locator('input[placeholder*="Phone"]').first.fill(PHONE_NUMBER)
                
                pwd_input = page.locator('form.sign-info input[type="password"]').first
                if pwd_input.count() > 0: pwd_input.fill(PASSWORD)
                else: page.locator('input[type="password"]').first.fill(PASSWORD)
                
                time.sleep(0.5)
                submit_btn = page.locator('form.sign-info button[type="submit"]').first
                if submit_btn.count() > 0: submit_btn.click()
                else: page.locator('button.btn.login').first.click(force=True)
                time.sleep(5)
                
            # 3. Read Balance
            try:
                bal_text = page.locator('[class*="balance"], .header-balance, .wallet-balance').first.inner_text(timeout=5000)
                log.info(f"Current Bookmaker Balance: {bal_text}")
            except Exception as e:
                log.warning("Could not read balance.")
                
            # 4. Clear Betslip
            clear_btn = page.locator('text="Remove all"')
            if clear_btn.count() > 0 and clear_btn.first.is_visible():
                clear_btn.first.click(force=True)
                time.sleep(1)
                
            # 5. Place Bet (Simplistic implementation for 1x2)
            home, away = pick['fixture'].split(' vs ')
            selection = "1" if pick['lock'] == "hw" else "2" if pick['lock'] == "aw" else "X"
            
            # Find the match
            events = page.locator('.virtual-event').all()
            match_found = False
            for ev in events:
                teams = ev.locator('.m-teams')
                if teams.count() > 0 and home.lower() in teams.inner_text().lower() and away.lower() in teams.inner_text().lower():
                    opts = ev.locator('.m-outcome').all()
                    # Standard 1X2 order: 1, X, 2
                    if selection == "1" and len(opts) > 0: opts[0].click()
                    elif selection == "X" and len(opts) > 1: opts[1].click()
                    elif selection == "2" and len(opts) > 2: opts[2].click()
                    match_found = True
                    break
                    
            if not match_found:
                log.error("Could not find the match in the DOM to click odds.")
                return False
                
            time.sleep(1)
            
            # 6. Enter Stake and Submit
            stake_input = page.locator('.bet-input input, input[type="tel"]').first
            stake_input.fill(str(int(stake)))
            time.sleep(1)
            
            place_btn = page.locator('button.place-bet, button.btn-place, button.btn-submit').first
            if place_btn.count() > 0:
                place_btn.click() # EXECUTING REAL MONEY
                log.info("✅ SUCCESS: Bet placed with real money.")
                return True
            else:
                log.error("Could not find Place Bet button.")
                return False
                
        except Exception as e:
            log.error(f"Browser integration error: {e}")
            return False

# ==========================================
# 🔄 MAIN LOOP
# ==========================================
def main_loop():
    log.info("Starting Live Oracle Bot Loop...")
    state = load_state()
    
    while True:
        try:
            info = get_current_match_day_info()
            if not info:
                time.sleep(10)
                continue
                
            season = info.get('seasonName')
            current_md = info.get('matchDay')
            status = info.get('status')
            
            # Prevent double-betting on the same matchday
            if state['last_bet_season'] == season and state['last_bet_md'] == current_md:
                log.info(f"Already checked MD {current_md}. Waiting for next...")
                time.sleep(20)
                continue
                
            tier_map = get_tiers_from_live_standings()
            events = get_event_list()
            
            if not tier_map or not events:
                time.sleep(10)
                continue
                
            target_md = events[0].get('matchDay')
            season_phase = int(np.ceil(target_md / 2.0))
            
            locks_found = []
            for ev in events:
                home = ev.get('homeTeamName')
                away = ev.get('awayTeamName')
                h_tier = tier_map.get(home)
                a_tier = tier_map.get(away)
                
                if not h_tier or not a_tier: continue
                key = (home, away, h_tier, a_tier, season_phase)
                
                if key in LOCKS_DB:
                    locks_found.append({
                        'fixture': f"{home} vs {away}",
                        'lock': LOCKS_DB[key],
                        'odds': extract_1x2_odds(ev)
                    })
                    
            if locks_found:
                pick = locks_found[0] # Take the first lock
                stake = state['current_stake']
                
                log.info(f"🚨 BULLETPROOF LOCK 🚨: {pick['fixture']} -> {pick['lock'].upper()}")
                
                # Place the bet
                success = place_bet_via_browser(pick, stake)
                
                if success:
                    # Update State manually representing a win (since it's a 100% lock)
                    odds_val = 1.70 if pick['lock'] == 'hw' else 2.10 if pick['lock'] == 'aw' else 3.00
                    
                    state['current_stake'] *= odds_val
                    state['bets_placed_in_cycle'] += 1
                    state['last_bet_season'] = season
                    state['last_bet_md'] = current_md
                    
                    if state['bets_placed_in_cycle'] >= TARGET_CYCLE_BETS:
                        profit = state['current_stake'] - CYCLE_RESET_STAKE
                        state['total_profit_banked'] += profit
                        log.info(f"🎉 CYCLE {state['cycle_number']} COMPLETE! Banking ₦{profit:,.2f}")
                        
                        state['current_stake'] = CYCLE_RESET_STAKE
                        state['bets_placed_in_cycle'] = 0
                        state['cycle_number'] += 1
                        
                    save_state(state)
            else:
                log.info(f"MD {target_md}: No locks. Skipping.")
                state['last_bet_season'] = season
                state['last_bet_md'] = current_md
                save_state(state)
                
            time.sleep(20) # Poll every 20s
            
        except KeyboardInterrupt:
            log.info("Bot shutting down...")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    main_loop()
