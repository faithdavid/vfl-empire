from playwright.sync_api import sync_playwright
import time

p = sync_playwright().start()
try:
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    context = browser.contexts[0]
    page = context.pages[0]

    print("Checking page...")
    page.goto("https://www.msport.com/ng/web/virtual")
    page.wait_for_timeout(5000)

    # Check if Login text/button exists on the page
    login_btn = page.locator('text="Login"').first
    if login_btn.is_visible():
        print("Login form detected, logging in...")
        # Fill in phone number
        phone_input = page.locator("input[placeholder*='Mobile']").first
        phone_input.fill("09038426877")
        page.wait_for_timeout(1000)

        # Fill in password
        pass_input = page.locator("input[type='password']").first
        pass_input.fill("fadava2002")
        page.wait_for_timeout(1000)

        # Click submit button
        submit_btn = page.locator("button:has-text('Login')").first
        submit_btn.click()
        print("Login submitted, waiting for redirect...")
        page.wait_for_timeout(8000)

    # Verify if logged in by reading balance
    try:
        bal_text = page.locator('[class*="balance"], .header-balance, .wallet-balance').first.inner_text(timeout=8000)
        print("✅ Login successful! Current Balance:", bal_text)
    except Exception as e:
        print("❌ Could not read balance (login might have failed):", e)

except Exception as e:
    print("Error:", e)
finally:
    try:
        browser.close()
        p.stop()
    except:
        pass
