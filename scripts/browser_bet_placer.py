import sys
import time
import json
import logging
import argparse
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("PlaywrightBetPlacer")

CDP_URL = "http://localhost:9222"

def clean_bal(s):
    if not s: return 0.0
    import re
    return float(re.sub(r'[^\d.]', '', s))

def connect_and_get_page(p):
    try:
        browser = p.chromium.connect_over_cdp(CDP_URL, timeout=5000)
        context = browser.contexts[0] if browser.contexts else None
        if not context:
            context = browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.set_viewport_size({"width": 1440, "height": 900})
        except:
            pass
        return browser, page
    except Exception as e:
        log.warning(f"CDP connection failed/timed out: {e}. Falling back to local persistent context.")
        context = p.chromium.launch_persistent_context(
            user_data_dir="/home/ubuntu/faith-workspace/vfl-empire/chrome_data",
            headless=True,
            viewport={"width": 1440, "height": 900}
        )
        page = context.pages[0] if context.pages else context.new_page()
        return context, page

def login_if_needed(page):
    try:
        body_text = page.locator('body').inner_text()
        if "Login" not in body_text and "Welcome" not in body_text:
            log.info("Already logged in (no Login/Welcome text)")
            return True
        if "Welcome" in body_text and "Login" not in body_text:
            log.info("Already logged in (Welcome detected)")
            return True
            
        log.info("Form sign-info detected in header. Filling login form...")
        
        # Check if the header login form is present and fill it natively
        phone_input = page.locator('form.sign-info input[type="tel"]').first
        if phone_input.count() > 0:
            phone_input.fill("09038426877")
        else:
            # Fallback placeholder selector
            page.locator('input[placeholder*="Phone"], input[placeholder*="Mobile"]').first.fill("09038426877")
            
        pwd_input = page.locator('form.sign-info input[type="password"]').first
        if pwd_input.count() > 0:
            pwd_input.fill("fadava2002")
        else:
            page.locator('input[type="password"]').first.fill("fadava2002")
            
        time.sleep(0.5)
        
        # Click the Login submit button in the form
        submit_btn = page.locator('form.sign-info button[type="submit"]').first
        if submit_btn.count() > 0:
            submit_btn.click()
            log.info("Natively clicked form submit button.")
        else:
            # Fallback button selection
            page.locator('button.btn.login, button.popper-input-button').first.click(force=True)
            
        time.sleep(5)
    except Exception as e:
        log.warning(f"Error during login_if_needed: {e}")

def get_balance():
    with sync_playwright() as p:
        browser, page = connect_and_get_page(p)
        if "web/virtual" not in page.url:
            log.info("Page is not on Virtuals. Navigating...")
            page.goto("https://www.msport.com/ng/web/virtual")
            time.sleep(5)
        login_if_needed(page)
        log.info("Checking balance...")
        bal_text = page.locator('[class*="balance"], .header-balance, .wallet-balance').first.inner_text()
        return bal_text

def get_betting_matchdays():
    with sync_playwright() as p:
        browser, page = connect_and_get_page(p)
        if "web/virtual" not in page.url:
            log.info("Page is not on Virtuals. Navigating...")
            page.goto("https://www.msport.com/ng/web/virtual")
            time.sleep(5)
        login_if_needed(page)
        log.info("Getting active matchdays...")
        els = page.locator('.match-day-bar').all()
        mds = []
        import re
        for el in els:
            txt = el.inner_text()
            m = re.search(r'Match Day\s+(\d+)', txt)
            if m: mds.append(int(m.group(1)))
        return mds

def select_matchday_tab(page, target_md):
    log.info(f"Selecting Match Day {target_md}...")
    tabs = page.locator('.match-day-bar').all()
    for tab in tabs:
        if f"Match Day {target_md}" in tab.inner_text():
            tab.click()
            time.sleep(1)
            try:
                page.locator('.virtual-event').first.wait_for(timeout=5000)
            except Exception as e:
                log.warning(f"Timeout waiting for virtual events to load: {e}")
            return True
    return False

def select_specifier_line(page, home, away, target_line, target_md=None):
    if target_md:
        select_matchday_tab(page, target_md)
        
    events = page.locator('.virtual-event').all()
    for ev in events:
        teams = ev.locator('.m-teams')
        if teams.count() > 0 and home.lower() in teams.inner_text().lower() and away.lower() in teams.inner_text().lower():
            spec = ev.locator('.m-specifier, .m-specifier-select .m-value, [class*="specifier"]').first
            if spec.count() > 0:
                if target_line in spec.inner_text():
                    log.info(f"Specifier is already at target line {target_line}. Skipping change.")
                    return True
                spec.click()
                time.sleep(0.5)
                opts = page.locator('.v-select-option, .m-popup-panel .item, .specifier-dropdown .item, li').all()
                for opt in opts:
                    if target_line in opt.inner_text():
                        opt.click()
                        time.sleep(0.8)
                        return True
    return False

def place_parlay(legs, stake, target_md=None):
    with sync_playwright() as p:
        browser, page = connect_and_get_page(p)
        if "web/virtual" not in page.url:
            log.info("Page is not on Virtuals. Navigating...")
            page.goto("https://www.msport.com/ng/web/virtual")
            time.sleep(5)
        login_if_needed(page)
        log.info(f"Placing {len(legs)}-leg parlay (stake: ₦{stake}) on MD{target_md}")
        
        # Read initial balance
        initial_bal = None
        try:
            bal_text = page.locator('[class*="balance"], .header-balance, .wallet-balance').first.inner_text(timeout=5000)
            initial_bal = clean_bal(bal_text)
            log.info(f"Initial balance: ₦{initial_bal}")
        except Exception as e:
            log.warning(f"Could not read initial balance: {e}")
        
        # Close any annoying popups intercepting clicks (like promo popups or success popups)
        for selector in [
            '.virtual-push-dialog .close', 
            '.virtual-push-dialog [class*="close"]',
            '.ui-dialog-btn-close',
            '.ui-dialog--wrap button:has-text("OK")',
            'button:has-text("OK")'
        ]:
            try:
                els = page.locator(selector).all()
                for el in els:
                    if el.is_visible():
                        el.click(timeout=1000, force=True)
                        time.sleep(1)
            except:
                pass
            
        # Clear betslip - robust version with verification
        def _clear_betslip_robust(page):
            """Attempt to clear the bet slip, with verification."""
            for attempt in range(3):
                try:
                    clear_btn = page.locator('text="Remove all"')
                    if clear_btn.count() > 0 and clear_btn.first.is_visible():
                        clear_btn.first.click(force=True, timeout=2000)
                        time.sleep(1.5)
                except Exception:
                    pass

                # Verify slip is empty by checking for common "empty slip" indicators
                empty_indicators = page.locator('text=/no.*bet|empty|add.*selection/i')
                if empty_indicators.count() > 0:
                    log.info("Betslip confirmed clear.")
                    return True

                # Alternative: check if "Place Bet" button is disabled or no stake visible
                stake_visible = page.locator('input[type="text"], .bet-input, [class*="stake"]').count()
                if stake_visible == 0:
                    return True

            log.warning("Could not fully confirm betslip is empty after clearing attempts.")
            return False

        _clear_betslip_robust(page)
            
        if target_md:
            select_matchday_tab(page, target_md)

        for i, leg in enumerate(legs, 1):
            home = leg["home"]
            away = leg["away"]
            market = leg.get("market", leg.get("selection", ""))
            log.info(f"Leg {i}/{len(legs)}: {home} vs {away} → {market}")

            is_over = "Over" in market
            is_under = "Under" in market
            is_dc = market in ["1 X", "1 2", "X 2", "1X", "12", "X2"]
            is_1x2 = market in ["1", "X", "2"]
            
            if is_dc:
                # Open Deep Markets
                events = page.locator('.virtual-event').all()
                for ev in events:
                    teams = ev.locator('.m-teams')
                    if teams.count() > 0 and home.lower() in teams.inner_text().lower() and away.lower() in teams.inner_text().lower():
                        plus_btns = ev.locator(r'text=/^\+/').all()
                        if plus_btns:
                            plus_btns[0].click()
                            time.sleep(2)
                            break
                            
                # Find Double Chance block
                dc_blocks = page.locator('.m-market').all()
                for dc in dc_blocks:
                    if "Double Chance" in dc.inner_text():
                        opts = dc.locator('.m-outcome, .virtual-outcome').all()
                        for opt in opts:
                            if market.replace(" ", "") in opt.inner_text().replace(" ", ""):
                                opt.click()
                                time.sleep(1)
                                break
                        break

            elif is_1x2:
                events = page.locator('.virtual-event').all()
                found_match = False
                for ev in events:
                    teams = ev.locator('.m-teams, .teams')
                    if teams.count() > 0:
                        teams_text = teams.inner_text().lower()
                        if home.lower() in teams_text and away.lower() in teams_text:
                            found_match = True
                            outcomes = ev.locator('.virtual-outcome, .m-outcome').all()
                            idx = -1
                            if market == "1": idx = 0
                            elif market == "X": idx = 1
                            elif market == "2": idx = 2
                            if idx >= 0 and len(outcomes) > idx:
                                log.info(f"Clicking outcome {idx} for {home} vs {away}")
                                outcomes[idx].click()
                                time.sleep(1)
                            else:
                                log.error(f"Could not find outcome {idx} for {home} vs {away}. Found {len(outcomes)} outcomes.")
                            break
                if not found_match:
                    log.error(f"Could not find match event for {home} vs {away}")

            elif is_over or is_under:
                import re
                m = re.search(r'([\d.]+)', market)
                target_line = m.group(1) if m else "2.5"
                select_specifier_line(page, home, away, target_line, None)
                
                market_col = 0 if is_over else 1
                events = page.locator('.virtual-event').all()
                for ev in events:
                    teams = ev.locator('.m-teams')
                    if teams.count() > 0 and home.lower() in teams.inner_text().lower() and away.lower() in teams.inner_text().lower():
                        second_market = ev.locator('.second-market')
                        if second_market.count() > 0:
                            outcomes = second_market.locator('a.virtual-outcome').all()
                            if len(outcomes) > market_col:
                                outcomes[market_col].click()
                                time.sleep(1)
                        break

        # Open floating betslip if present (mobile/responsive mode)
        try:
            floating_btn = page.locator('.m-bet-slip-bar, .virtual-bet-slip-bar, .bet-slip-btn, .m-layout-bottom').first
            if floating_btn.count() > 0 and floating_btn.is_visible(timeout=1000):
                floating_btn.click(force=True)
                time.sleep(1)
        except:
            pass

        # Enter stake
        is_multi = len(legs) > 1
        tabs = page.locator('.m-mode-option, .m-bet-slip-tabs .tab, .bet-slip-tabs .tab, [class*="bet-slip-tabs"] [class*="tab"]').all()
        for t in tabs:
            txt = t.inner_text().lower()
            if is_multi and ("multiple" in txt or "multiples" in txt):
                t.click()
                time.sleep(1)
                break
            elif not is_multi and ("single" in txt or "standard" in txt):
                t.click()
                time.sleep(1)
                break
                    
        time.sleep(1)
        # Robustly find stake input based on parlay legs count
        stake_input = None
        if is_multi:
            # Multiples mode is active. Let's find the specific multiple input (e.g. Doubles, Trebles, 4-Folds)
            leg_count = len(legs)
            # Map leg count to expected labels
            target_labels = []
            if leg_count == 2:
                target_labels = ["double"]
            elif leg_count == 3:
                target_labels = ["treble"]
            else:
                target_labels = [f"{leg_count}-fold", f"{leg_count} fold", f"{leg_count}fold"]
            
            # Find the rows in the multiples betslip
            # Looking at the html, each row is inside .virtual-mutiple-normal or a container with bet-input
            rows = page.locator('.virtual-mutiple-normal, .m-item-wrap, [class*="mutiple-normal"]').all()
            log.info(f"Searching for parlay input for {leg_count} legs in {len(rows)} rows...")
            for row in rows:
                try:
                    row_text = row.inner_text().lower()
                    if any(label in row_text for label in target_labels):
                        input_el = row.locator('input[type="text"], input.v-input--inner, input').first
                        if input_el.count() > 0:
                            stake_input = input_el
                            log.info(f"Found matching parlay input for label {target_labels} in row: '{row_text.strip()}'")
                            break
                except Exception as e:
                    log.warning(f"Error checking row: {e}")
            
            # Fallback 1: Try "Play All" if we didn't find the specific fold input
            if not stake_input:
                log.info("Specific parlay input not found, searching for 'Play All'...")
                for row in rows:
                    try:
                        row_text = row.inner_text().lower()
                        if "play all" in row_text:
                            input_el = row.locator('input[type="text"], input.v-input--inner, input').first
                            if input_el.count() > 0:
                                stake_input = input_el
                                log.info("Found 'Play All' input row")
                                break
                    except Exception as e:
                        pass
        
        # Fallback 2: Default standard input locator
        if not stake_input:
            log.info("Using fallback standard stake inputs selector...")
            stake_inputs = page.locator('aside .v-input--inner, aside .v-input input, .m-virtual-multiple-stake-input input, aside .m-virtual-mutiple-edit .bet-input input, aside input, .bet-slip input, input[placeholder*="Stake"], input[placeholder*="stake"], input[type="tel"]').all()
            if stake_inputs:
                stake_input = stake_inputs[-1]
                log.info("Selected last input element from general list")
        
        if stake_input:
            stake_input.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            time.sleep(0.2)
            stake_input.type(str(stake), delay=100)
            time.sleep(0.5)
            # Click betslip title to trigger blur/change events
            try:
                page.locator(".virtual-main-betslip2--title, .m-bet-slip-title, .bet-slip-title, .title").first.click(force=True, timeout=2000)
            except:
                pass
            time.sleep(0.5)
        else:
            log.error("Could not find stake input.")
            # Take a screenshot for debugging
            try:
                page.screenshot(path="/home/ubuntu/faith-workspace/vfl-empire/logs/debug_screenshot.png")
                with open("/home/ubuntu/faith-workspace/vfl-empire/logs/debug_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
            except:
                pass
            return {"success": False, "error": "Stake input not found"}

        time.sleep(1)
        place_btn = page.locator('text="Place Bet", text="Place bet", button.place-btn, button:has-text("Place Bet")').first
        placed = False
        error_msg = "Unknown placement failure"
        
        if place_btn.count() > 0:
            place_btn.click(force=True)
            time.sleep(2)
            
            # Check if success modal appeared immediately (no confirmation dialog needed)
            success_modal = page.locator('text="Bet Successful!"').first
            if success_modal.count() > 0 and success_modal.is_visible():
                placed = True
                log.info("Bet Successful popup detected immediately!")
                ok_btn = page.locator('button:has-text("OK"), .ui-dialog-btn-ok, .m-btn:has-text("OK")').first
                if ok_btn.count() > 0:
                    ok_btn.click(force=True)
                    time.sleep(1)
            else:
                confirm_btn = None
                for selector in [
                    'button:has-text("Confirm Bet")',
                    'button:has-text("Confirm")',
                    'text="Confirm Bet"',
                    'text="Confirm"'
                ]:
                    try:
                        btn = page.locator(selector).first
                        if btn.count() > 0 and btn.is_visible():
                            confirm_btn = btn
                            break
                    except Exception:
                        pass
                
                if confirm_btn:
                    confirm_btn.click(force=True)
                    time.sleep(3)
                    
                    # Check for "Balance insufficient"
                    try:
                        insufficient_modal = page.locator('text="Balance insufficient"').first
                        if insufficient_modal.count() > 0 and insufficient_modal.is_visible(timeout=2000):
                            log.error("Insufficient balance popup detected!")
                            return {"success": False, "error": "Balance insufficient"}
                    except:
                        pass
                    
                    # Check for "Bet Successful!"
                    try:
                        success_modal = page.locator('text="Bet Successful!"').first
                        if success_modal.count() > 0 and success_modal.is_visible(timeout=5000):
                            placed = True
                            log.info("Bet Successful popup detected!")
                            # Click the OK button to close the popup
                            ok_btn = page.locator('button:has-text("OK"), .ui-dialog-btn-ok, .m-btn:has-text("OK")').first
                            if ok_btn.count() > 0:
                                ok_btn.click(force=True)
                                time.sleep(1)
                    except Exception as e:
                        log.warning(f"Error checking success dialog: {e}")
                else:
                    log.error("Confirm button not found, and no immediate success popup.")
                    error_msg = "Confirm button not found"
        else:
            log.error("Place Bet button not found.")
            error_msg = "Place Bet button not found"
        
        # Check final balance
        try:
            bal = page.locator('[class*="balance"], .header-balance, .wallet-balance').first.inner_text(timeout=5000)
            final_bal = clean_bal(bal)
            log.info(f"Final balance: ₦{final_bal}")
        except Exception as e:
            log.warning(f"Could not read final balance: {e}")
            bal = "Unknown"
            final_bal = None
            
        # Balance deduction fallback check
        if not placed and initial_bal is not None and final_bal is not None:
            deduction = initial_bal - final_bal
            if deduction >= float(stake) - 0.01:
                log.info(f"Bet placement confirmed via balance deduction: ₦{initial_bal} -> ₦{final_bal} (stake: ₦{stake})")
                placed = True

        return {"success": placed, "leg_count": len(legs), "stake": stake, "balance": bal} if placed else {"success": False, "error": error_msg}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Playwright Bet Placer")
    parser.add_argument("command", choices=["balance", "matchdays", "parlay", "bet"])
    parser.add_argument("payload", nargs="?", help="JSON payload for parlay")
    
    args = parser.parse_args()
    
    try:
        if args.command == "balance":
            bal = get_balance()
            mds = []
            current_md = None
            try:
                mds = get_betting_matchdays()
                if mds:
                    current_md = mds[0]
            except Exception as e:
                log.warning(f"Failed to get matchdays during balance call: {e}")
            print(json.dumps({
                "success": True, 
                "balance": bal,
                "matchday": current_md,
                "available_mds": mds
            }))
        elif args.command == "matchdays":
            print(json.dumps({"success": True, "matchdays": get_betting_matchdays()}))
        elif args.command in ("parlay", "bet"):
            payload = args.payload if args.payload else sys.stdin.read()
            data = json.loads(payload)
            if "legs" not in data and "home" in data:
                legs = [{
                    "home": data["home"],
                    "away": data["away"],
                    "market": data["market"]
                }]
            else:
                legs = data.get("legs", [])
            target_md = data.get("target_md") or data.get("matchday")
            res = place_parlay(legs, data.get("stake", 0), target_md)
            print(json.dumps(res))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
