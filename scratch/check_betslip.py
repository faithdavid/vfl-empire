import sys
import time
import json
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("CheckBetslip")

CDP_URL = "http://localhost:9222"

def check():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]
        
        log.info(f"Page URL: {page.url}")
        log.info(f"Page Title: {page.title()}")
        
        # Take a screenshot to see what is currently open on the browser
        screenshot_path = "/home/ubuntu/faith-workspace/vfl-empire/logs/live_screenshot.png"
        page.screenshot(path=screenshot_path)
        log.info(f"Screenshot saved to {screenshot_path}")
        
        # Look for popups/modals
        log.info("Checking for open dialogs or overlays...")
        dialogs = page.locator('.ui-dialog, .m-dialog, .popup, .modal').all()
        for idx, d in enumerate(dialogs):
            if d.is_visible():
                log.info(f"Visible Dialog {idx}: {d.inner_text()}")
                
        # Look at the betslip text
        betslip = page.locator('aside, .betslip, .m-betslip, #betslip').all()
        for idx, b in enumerate(betslip):
            if b.is_visible():
                log.info(f"Visible Betslip {idx} Text: {b.inner_text()}")

if __name__ == "__main__":
    check()
