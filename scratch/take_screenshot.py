from playwright.sync_api import sync_playwright
import time

def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0]
            print(f"Page title: {page.title()}")
            path = "/home/ubuntu/faith-workspace/vfl-empire/logs/live_screenshot.png"
            page.screenshot(path=path)
            print(f"Screenshot saved to {path}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
