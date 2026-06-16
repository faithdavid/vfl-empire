import time
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("InspectBetslip")

CDP_URL = "http://localhost:9222"

def inspect():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]
        
        # 1. Clear betslip
        clear_btn = page.locator('text="Remove all"')
        if clear_btn.count() > 0:
            clear_btn.first.click(force=True)
            log.info("Cleared betslip")
            time.sleep(1)
            
        # 2. Find a virtual outcome and click it
        outcome = page.locator('a.virtual-outcome').first
        if outcome.count() > 0:
            log.info(f"Adding leg to betslip: {outcome.inner_text()}")
            outcome.click(force=True)
            time.sleep(2)
        else:
            log.warning("No virtual outcomes found to click!")
            return
            
        # 3. Print HTML of the betslip area
        aside_html = page.locator('aside').inner_html()
        # Save to logs for manual review if needed
        with open("/home/ubuntu/faith-workspace/vfl-empire/logs/aside_dump.html", "w") as f:
            f.write(aside_html)
        log.info("Dumped aside HTML to logs/aside_dump.html")
        
        # Look for buttons in aside
        buttons = page.locator('aside button, aside a, aside input').all()
        for idx, btn in enumerate(buttons):
            log.info(f"Aside Element {idx}: tag={btn.evaluate('el => el.tagName')}, class={btn.get_attribute('class')}, text={btn.inner_text()}")
            
        # 4. Fill stake with 10 (don't place yet)
        stake_inputs = page.locator('aside .v-input--inner, aside .v-input input, .m-virtual-multiple-stake-input input, aside .m-virtual-mutiple-edit .bet-input input, aside input').all()
        log.info(f"Found {len(stake_inputs)} stake inputs.")
        for idx, inp in enumerate(stake_inputs):
            log.info(f"Stake Input {idx}: tag={inp.evaluate('el => el.tagName')}, class={inp.get_attribute('class')}, value={inp.get_attribute('value')}")
            
        if stake_inputs:
            stake_inputs[-1].fill("10")
            log.info("Filled stake with 10")
            time.sleep(1)
            
            # Click Place Bet button (but don't confirm yet)
            place_btn = page.locator('text="Place Bet"').first
            if place_btn.count() > 0:
                log.info("Clicking Place Bet...")
                place_btn.click(force=True)
                time.sleep(2)
                
                # Check what pops up!
                page.screenshot(path="/home/ubuntu/faith-workspace/vfl-empire/logs/aside_after_click.png")
                log.info("Screenshot taken after clicking Place Bet: logs/aside_after_click.png")
                
                # Let's inspect any new dialog or overlay
                dialogs = page.locator('.ui-dialog, .m-dialog, .popup, .modal, .m-popup-panel, [class*="dialog"]').all()
                for idx, d in enumerate(dialogs):
                    if d.is_visible():
                        log.info(f"Visible Dialog {idx}: class={d.get_attribute('class')}, text={d.inner_text()}")
                        # print the html of this dialog
                        log.info(f"Dialog HTML: {d.inner_html()}")
                
                # Find all buttons with text Confirm
                confirms = page.locator('text="Confirm", [class*="confirm"], button:has-text("Confirm")').all()
                log.info(f"Found {len(confirms)} potential confirm elements:")
                for idx, c in enumerate(confirms):
                    log.info(f"Confirm Element {idx}: tag={c.evaluate('el => el.tagName')}, class={c.get_attribute('class')}, text={c.inner_text()}, visible={c.is_visible()}")
                
                # Click cancel/close or remove selections to clean up
                cancel_btn = page.locator('text="Cancel", button:has-text("Cancel"), .ui-dialog-btn-cancel').first
                if cancel_btn.count() > 0 and cancel_btn.is_visible():
                    log.info("Clicking Cancel to clean up...")
                    cancel_btn.click(force=True)
                    time.sleep(1)
                else:
                    log.info("No Cancel button found to click, clearing betslip instead")
                    
        # Clear betslip again to clean up
        clear_btn = page.locator('text="Remove all"')
        if clear_btn.count() > 0:
            clear_btn.first.click(force=True)
            log.info("Cleared betslip after inspection")

if __name__ == "__main__":
    inspect()
