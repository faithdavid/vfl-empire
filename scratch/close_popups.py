from playwright.sync_api import sync_playwright
import time

def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            print(f"Page title: {page.title()}")
            
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
                            print(f"Clicking visible element: {selector}")
                            el.click(timeout=1000, force=True)
                            time.sleep(1)
                except Exception as e:
                    print(f"Selector {selector} error: {e}")
            
            page.screenshot(path="/home/ubuntu/faith-workspace/vfl-empire/logs/after_closing.png")
            print("Done closing popups and saved screenshot to /home/ubuntu/faith-workspace/vfl-empire/logs/after_closing.png")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
