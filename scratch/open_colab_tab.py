import logging
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("ColabOpener")

CDP_URL = "http://localhost:9222"
COLAB_URL = "https://colab.research.google.com/drive/1Q4QXxlupvM860AEuYP-j5kaaLLNqScwG?authuser=0"

def open_notebook():
    with sync_playwright() as p:
        log.info(f"Connecting to Chrome over CDP on {CDP_URL}...")
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        
        log.info(f"Opening Google Colab in a new tab: {COLAB_URL}")
        page = context.new_page()
        page.goto(COLAB_URL)
        log.info("Tab opened and page loaded successfully.")

if __name__ == "__main__":
    open_notebook()
