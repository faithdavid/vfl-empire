import time
import json
import logging
import sys
import os
import requests
import pandas as pd
from datetime import datetime
from playwright.sync_api import sync_playwright

sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
import msport_api

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("VFL_Sniper_Bot")

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
CDP_URL = "http://localhost:9222"
PHONE_NUMBER = "09038426877"
PASSWORD = "fadava2002"

MACRO_FILE = '/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json'
MICRO_FILE = '/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json'

STATE_FILE = '/home/ubuntu/faith-workspace/vfl-empire/data/sniper_state.json'

# TELEGRAM
TELEGRAM_TOKEN = "8939731870:AAGIPK4PYrR2Nfmxeir1t7iS7sn68uxVBHA"
TELEGRAM_CHAT_ID = "5705670725"

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload)
    except Exception as e:
        log.error(f"Failed to send Telegram message: {e}")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        "last_bet_md": None, 
        "last_bet_season": None,
        "current_stake": 10.0,
        "cycle_step": 1,
        "banked_profit": 0.0,
        "pending_bet": None
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

def load_patterns(filepath: str) -> dict:
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        lookup = {}
        for row in data:
            if row['occurrences'] < 10: continue
            key = (row['home'], row['away'], row['home_tier'], row['away_tier'])
            lookup[key] = row
        return lookup
    except:
        return {}

def get_tiers_from_live_standings():
    try:
        raw_standings = msport_api.get_standings()
        if not raw_standings: return None, None
        table = msport_api.extract_standings_table(raw_standings)
        if not table: return None, None
        
        df = pd.DataFrame(table)
        df.sort_values(['points', 'goalDifference', 'goalsFor'], ascending=[False, False, False], inplace=True)
        df['rank'] = range(1, len(df) + 1)
        
        df['macro_tier'] = pd.cut(df['rank'], bins=[0, 4, 8, 12, 16], labels=['T1', 'T2', 'T3', 'T4'])
        df['micro_tier'] = pd.cut(df['rank'], bins=[0, 2, 4, 6, 8, 10, 12, 14, 16], labels=['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'])
        
        macro_map = dict(zip(df['teamName'], df['macro_tier']))
        micro_map = dict(zip(df['teamName'], df['micro_tier']))
        return macro_map, micro_map
    except Exception as e:
        log.error(f"Error getting tiers: {e}")
        return None, None

def playwright_login_and_balance(page):
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
        
    try:
        bal_text = page.locator('[class*="balance"], .header-balance, .wallet-balance').first.inner_text(timeout=5000)
        return bal_text
    except:
        return "Unknown"

def place_single_bet_browser(home, away, selection, stake=10):
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL, timeout=5000)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            
            if "web/virtual" not in page.url:
                page.goto("https://www.msport.com/ng/web/virtual")
                time.sleep(5)
                
            bal_text = playwright_login_and_balance(page)
            
            clear_btn = page.locator('text="Remove all"')
            if clear_btn.count() > 0 and clear_btn.first.is_visible():
                clear_btn.first.click(force=True)
                time.sleep(1)
                
            match_found = False
            events = page.locator('.virtual-event').all()
            for ev in events:
                teams = ev.locator('.m-teams')
                if teams.count() > 0 and home.lower() in teams.inner_text().lower() and away.lower() in teams.inner_text().lower():
                    opts = ev.locator('.virtual-outcome').all()
                    if selection == "1" and len(opts) > 0: opts[0].click()
                    elif selection == "X" and len(opts) > 1: opts[1].click()
                    elif selection == "2" and len(opts) > 2: opts[2].click()
                    match_found = True
                    break
                    
            if not match_found: 
                log.error(f"Could not find match {home} vs {away} on DOM.")
                return False
                
            time.sleep(1)
            
            betslip_toggle = page.locator('.m-float-betslip, .betslip-btn, .betslip-icon').first
            if betslip_toggle.count() > 0 and betslip_toggle.is_visible():
                betslip_toggle.click(force=True)
                time.sleep(1)
            else:
                betslip_text = page.locator('text="Betslip"').first
                if betslip_text.count() > 0 and betslip_text.is_visible():
                    betslip_text.click(force=True)
                    time.sleep(1)
                    
            import math
            stake_input = page.locator('input.v-input--inner, .bet-input input, input[type="tel"]').first
            exact_stake = math.floor(stake * 100) / 100.0
            stake_input.fill(f"{exact_stake:.2f}")
            time.sleep(1)
            
            place_btn = page.locator('.m-place-btn, .m-btn.m-btn-place, button.place-bet, button.btn-place, button.btn-submit').first
            if place_btn.count() > 0:
                place_btn.click() # REAL BET PLACED
                log.info(f"✅ Placed sniper bet: {home} vs {away} [{selection}] Stake: {stake} N")
                return True
            return False
        except Exception as e:
            log.error(f"Playwright error: {e}")
            return False

def main_loop():
    log.info("🎯 VFL Sniper Protocol Booting Up...")
    state = load_state()
    
    macro_patterns = load_patterns(MACRO_FILE)
    micro_patterns = load_patterns(MICRO_FILE)
    log.info("Loaded patterns. Awaiting transition window...")
    
    while True:
        try:
            # 1. RESOLVE PENDING BET IF ANY
            if state.get('pending_bet'):
                pb = state['pending_bet']
                # Check results for the pending bet
                results_data = msport_api.get_results(pb['season'], pb['md'])
                if results_data:
                    won = False
                    found = False
                    for r in results_data:
                        if msport_api._normalise_team_name(r['homeTeam']) == pb['home'] and msport_api._normalise_team_name(r['awayTeam']) == pb['away']:
                            found = True
                            ft = r.get('fullTime', '0:0').split(':')
                            hg, ag = int(ft[0]), int(ft[1])
                            if pb['selection'] == "1" and hg > ag: won = True
                            elif pb['selection'] == "X" and hg == ag: won = True
                            elif pb['selection'] == "2" and hg < ag: won = True
                            break
                            
                    if found:
                        if won:
                            payout = pb['expected_return']
                            log.info(f"✅ PENDING BET WON! Payout: {payout} N")
                            send_telegram(f"✅ *SNIPER WIN!*\nMatchday {pb['md']} {pb['home']} won.\nPayout: ₦{payout:.2f}")
                            if state['cycle_step'] == 5:
                                state['banked_profit'] += payout * 0.60
                                state['current_stake'] = payout * 0.40
                                state['cycle_step'] = 1
                                log.info(f"🎉 CYCLE COMPLETE! Banked 60%. New base: {state['current_stake']:.2f}")
                                send_telegram(f"🎉 *SNIPER CYCLE COMPLETE!*\nBanked 60% of profits.\nRestarting new cycle with ₦{state['current_stake']:.2f}")
                            else:
                                state['current_stake'] = payout
                                state['cycle_step'] += 1
                                log.info(f"🔄 Rolling over to Step {state['cycle_step']} with {state['current_stake']:.2f} N")
                                send_telegram(f"🔄 *SNIPER ROLLOVER*\nAdvancing to Step {state['cycle_step']} with ₦{state['current_stake']:.2f}")
                        else:
                            log.info(f"❌ PENDING BET LOST. Cycle Crashed.")
                            if state['banked_profit'] >= 1000:
                                state['current_stake'] = 200.0
                                state['banked_profit'] -= 200.0
                                log.info("  🔄 Bank > 1000 N. Restarting with 200 N from bank.")
                                send_telegram(f"❌ *SNIPER CRASH*\nRestarting from bank reserves with ₦200 base.")
                            else:
                                state['current_stake'] = 10.0
                                state['banked_profit'] -= 10.0
                                log.info("  🔄 Bank < 1000 N. Restarting with 10 N.")
                                send_telegram(f"❌ *SNIPER CRASH*\nRestarting with ₦10 base.")
                            state['cycle_step'] = 1
                            
                        state['pending_bet'] = None
                        save_state(state)

            info = msport_api.get_current_match_day_info()
            if not info:
                time.sleep(3)
                continue
                
            season = info.get('seasonName', 'Unknown')
            target_md = info.get('matchDay')
            status = info.get('status')
            
            # We ONLY execute when status == 0 (Betting is Open/Upcoming)
            # This is exactly the 35-second transition window.
            # If status == 1 (Playing), we sleep.
            if status == 1:
                time.sleep(5)
                continue
            
            events_data = msport_api.get_event_list()
            if not events_data:
                time.sleep(3)
                continue
                
            upcoming = events_data[0]
            target_md = upcoming.get('matchDay')
            season = upcoming.get('seasonName', 'Unknown')
            
            # Prevent duplicate betting
            if state['last_bet_md'] == target_md and state['last_bet_season'] == season:
                time.sleep(10)
                continue
                
            est_start = upcoming.get('estimateStartTime', 0)
            now_ms = time.time() * 1000
            time_left = (est_start - now_ms) / 1000.0
            
            # The Sniper Window is OPEN because status == 0
            log.info(f"🎯 SNIPER WINDOW OPEN! Fetching synced table for MD {target_md}...")
            
            macro_map, micro_map = get_tiers_from_live_standings()
            if not macro_map:
                log.error("Failed to fetch synced table in time.")
                time.sleep(3)
                continue
                
            matches = upcoming.get('events', [])
            bet_placed = False
            
            for ev in matches:
                home_raw = ev.get('homeTeam') or ev.get('homeTeamName', '')
                away_raw = ev.get('awayTeam') or ev.get('awayTeamName', '')
                home = msport_api._normalise_team_name(home_raw)
                away = msport_api._normalise_team_name(away_raw)
                
                h_mac = macro_map.get(home)
                a_mac = macro_map.get(away)
                h_mic = micro_map.get(home)
                a_mic = micro_map.get(away)
                
                if not (h_mac and a_mac and h_mic and a_mic):
                    continue
                    
                mac_row = macro_patterns.get((home, away, h_mac, a_mac), {})
                mic_row = micro_patterns.get((home, away, h_mic, a_mic), {})
                
                # Look for Extreme Home Win Trap
                mac_1 = mac_row.get('w_1_rate', 0)
                mic_1 = mic_row.get('w_1_rate', 0)
                
                if mac_1 >= 0.85 or mic_1 >= 0.85:
                    log.info(f"🚨 TRAP DETECTED: {home} vs {away} (Home Win | Mac:{mac_1*100:.0f}% Mic:{mic_1*100:.0f}%)")
                    
                    stake_amount = state['current_stake']
                    send_telegram(f"🎯 *SNIPER TRAP DETECTED!*\n{home} vs {away}\nWin Probability: >85%\n\n🤖 Executing Playwright to stake ₦{stake_amount:.2f}")
                    
                    # FIRE THE SNIPER
                    success = place_single_bet_browser(home, away, "1", stake=stake_amount)
                    if success:
                        # Parse odds to predict expected return
                        odds_val = msport_api.extract_1x2_odds(ev)
                        target_odds = odds_val.get('1', 1.85)
                        
                        state['last_bet_md'] = target_md
                        state['last_bet_season'] = season
                        state['pending_bet'] = {
                            'season': season,
                            'md': target_md,
                            'home': home,
                            'away': away,
                            'selection': "1",
                            'stake': stake_amount,
                            'expected_return': stake_amount * target_odds
                        }
                        save_state(state)
                        bet_placed = True
                        send_telegram(f"✅ *SNIPER BET PLACED SUCCESSFULLY!*\nStake: ₦{stake_amount:.2f}\nExpected Return: ₦{stake_amount * target_odds:.2f}")
                        break # Only place one bet per MD
            
            if not bet_placed:
                log.info(f"No >85% Home Win traps found for MD {target_md}.")
                state['last_bet_md'] = target_md
                state['last_bet_season'] = season
                save_state(state)
                    
            time.sleep(5)
                
        except Exception as e:
            log.error(f"Sniper loop error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main_loop()
