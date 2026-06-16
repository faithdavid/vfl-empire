from playwright.sync_api import sync_playwright
import time

def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            
            # Try to find a specifier dropdown
            events = page.locator('.virtual-event').all()
            print(f"Found {len(events)} virtual events")
            if events:
                ev = events[0]
                teams = ev.locator('.m-teams').inner_text().replace('\n', ' vs ')
                print(f"First event: {teams}")
                spec = ev.locator('.m-specifier, .m-specifier-select .m-value, [class*="specifier"]').first
                if spec.count() > 0:
                    print("Found specifier button, clicking it...")
                    spec.click()
                    time.sleep(1)
                    
                    # Dump options visible
                    opts = page.locator('.v-select-option, .m-popup-panel .item, .specifier-dropdown .item, li').all()
                    print(f"Found {len(opts)} options in dropdown:")
                    for idx, opt in enumerate(opts):
                        print(f"  Option {idx}: '{opt.inner_text()}' (visible: {opt.is_visible()})")
                        
                    # Take a screenshot of the dropdown open
                    page.screenshot(path="/home/ubuntu/faith-workspace/vfl-empire/logs/specifier_debug.png")
                    print("Saved screenshot to /home/ubuntu/faith-workspace/vfl-empire/logs/specifier_debug.png")
                    
                    # Close dropdown
                    spec.click()
                else:
                    print("Specifier button not found on first event")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
