import time
import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("ColabRunner")

CDP_URL = "http://localhost:9222"
COLAB_URL = "https://colab.research.google.com/drive/1Q4QXxlupvM860AEuYP-j5kaaLLNqScwG?authuser=0"

def run_notebook():
    with sync_playwright() as p:
        log.info(f"Connecting to Chrome over CDP on {CDP_URL}...")
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        
        log.info(f"Opening new page for Google Colab: {COLAB_URL}")
        page = context.new_page()
        page.goto(COLAB_URL)
        
        log.info("Waiting for Colab to load...")
        time.sleep(10)  # Wait for Colab interface to load
        
        # Take an initial screenshot
        screenshot_path = "/home/ubuntu/faith-workspace/vfl-empire/logs/colab_initial.png"
        page.screenshot(path=screenshot_path)
        log.info(f"Saved initial Colab screenshot to {screenshot_path}")
        
        # Trigger "Run all" via Keyboard Shortcut: Ctrl + F9
        log.info("Sending Ctrl+F9 to run all cells...")
        page.keyboard.press("Control+F9")
        time.sleep(2)
        
        # In case a confirmation dialog appears (e.g. "Run anyway" because it's not authored by Google)
        log.info("Checking for 'Run anyway' dialog...")
        try:
            # Colab displays a warning dialog for notebooks not created by Google.
            # The button usually has text "Run anyway" or class name containing dialog buttons.
            run_anyway = page.locator('paper-button:has-text("Run anyway"), button:has-text("Run anyway"), .paper-dialog-button:has-text("Run anyway")').first
            if run_anyway.count() > 0 and run_anyway.is_visible():
                log.info("Clicking 'Run anyway' button...")
                run_anyway.click()
                time.sleep(2)
        except Exception as e:
            log.warning(f"Error checking dialog: {e}")
            
        log.info("Letting Colab run for 15 seconds...")
        time.sleep(15)
        
        # Take a progress screenshot
        progress_screenshot = "/home/ubuntu/faith-workspace/vfl-empire/logs/colab_progress.png"
        page.screenshot(path=progress_screenshot)
        log.info(f"Saved progress screenshot to {progress_screenshot}")
        
        # Close the page to avoid leaving tabs open
        page.close()
        log.info("Colab execution script complete.")

if __name__ == "__main__":
    run_notebook()
