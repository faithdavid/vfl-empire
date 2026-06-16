import time
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("ClosePopup")

CDP_URL = "http://localhost:9222"

def close_popup():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]
        
        log.info(f"Page URL: {page.url}")
        
        ok_btn = page.locator('button:has-text("OK"), .ui-dialog-btn-ok, .m-btn:has-text("OK")').first
        if ok_btn.count() > 0:
            log.info("Found OK button, clicking...")
            ok_btn.click(force=True)
            time.sleep(2)
        else:
            log.warning("No OK button found")
            
        page.screenshot(path="/home/ubuntu/faith-workspace/vfl-empire/logs/after_closing.png")
        log.info("Screenshot taken after closing attempt.")

if __name__ == "__main__":
    close_popup()
