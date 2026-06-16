#!/usr/bin/env python3
"""
msport_token_refresher.py — Refresh MSport auth tokens for Go agent
Uses document.cookie + localStorage to extract real auth tokens
(broken Playwright ctx.cookies() API returns 0 on CDP connections)
"""
import json, os, sys, time, re
from playwright.sync_api import sync_playwright

TOKEN_FILE = "/home/ubuntu/faith-workspace/vfl-empire/data/msport_tokens.json"
PHONE = "09038426877"
PASS = "fadava2002"

# Keys we care about from cookies
COOKIE_KEYS = {"accessToken", "refreshToken", "userId", "deviceId", "device-id", "did", "highFreqToken"}

def parse_cookies(cookie_str):
    """Parse document.cookie string into a dict."""
    result = {}
    if not cookie_str:
        return result
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, val = item.split("=", 1)
            result[key.strip()] = val.strip()
    return result

def login_if_needed(page):
    """Check login state; if not logged in, perform login."""
    page.goto("https://www.msport.com/ng/web/virtual", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    cookie_str = page.evaluate("() => document.cookie")
    cookies = parse_cookies(cookie_str)

    if cookies.get("accessToken"):
        print("Already logged in — refreshing tokens inline")
        return True

    print("Not logged in — performing login flow...")
    page.goto("https://www.msport.com/ng/web/virtual", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    # Try clicking login button if present
    try:
        login_btn = page.locator("button:has-text('Login'), a:has-text('Login'), button:has-text('Sign In')")
        if login_btn.count() > 0:
            login_btn.first.click()
            page.wait_for_timeout(2000)
    except Exception:
        pass

    # Navigate directly to login page
    page.goto("https://www.msport.com/ng/web/login", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Fill credentials
    try:
        phone_input = page.locator("input[type='tel'], input[name='phone'], input[placeholder*='phone'], input[placeholder*='Phone'], input#phone")
        if phone_input.count() > 0:
            phone_input.first.fill(PHONE)
        else:
            # Try any visible input
            inputs = page.locator("input:visible")
            if inputs.count() >= 2:
                inputs.nth(0).fill(PHONE)
    except Exception as e:
        print(f"Warning: could not fill phone: {e}")

    page.wait_for_timeout(500)

    try:
        pass_input = page.locator("input[type='password'], input[name='password'], input[placeholder*='password'], input[placeholder*='Password'], input#password")
        if pass_input.count() > 0:
            pass_input.first.fill(PASS)
        else:
            inputs = page.locator("input:visible")
            if inputs.count() >= 2:
                inputs.nth(1).fill(PASS)
    except Exception as e:
        print(f"Warning: could not fill password: {e}")

    page.wait_for_timeout(500)

    # Click submit
    try:
        submit_btn = page.locator("button[type='submit'], button:has-text('Login'), button:has-text('Sign In'), button:has-text('Submit')")
        if submit_btn.count() > 0:
            submit_btn.first.click()
    except Exception:
        pass

    page.wait_for_timeout(5000)
    print("Login form submitted, waiting for redirect...")

    # Wait for redirect to virtual page
    try:
        page.wait_for_url("**/virtual**", timeout=15000)
    except Exception:
        pass

    page.wait_for_timeout(3000)
    return True

def extract_device_id(page):
    """Extract deviceId from localStorage."""
    try:
        did = page.evaluate("() => localStorage.getItem('deviceId')")
        return did if did else None
    except Exception as e:
        print(f"Warning: could not get deviceId from localStorage: {e}")
        return None

def refresh():
    """Login to MSport and extract fresh auth tokens via document.cookie + localStorage."""
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Login if needed
        login_if_needed(page)

        # --- Extract tokens from document.cookie ---
        cookie_str = page.evaluate("() => document.cookie")
        print(f"Raw cookie string: {cookie_str[:200]}..." if len(cookie_str) > 200 else f"Raw cookie string: {cookie_str}")

        cookies = parse_cookies(cookie_str)
        print(f"Parsed cookies: {json.dumps(cookies, indent=2)}")

        tokens = {}
        for key in COOKIE_KEYS:
            if key in cookies:
                tokens[key] = cookies[key]

        # --- Extract deviceId from localStorage ---
        local_device_id = extract_device_id(page)
        if local_device_id:
            tokens["deviceId_localStorage"] = local_device_id
            if "deviceId" not in tokens:
                tokens["deviceId"] = local_device_id

        # --- Also try to get tokens from localStorage (some SPAs store them there) ---
        try:
            for ls_key in ["accessToken", "refreshToken", "userId", "deviceId", "highFreqToken"]:
                val = page.evaluate(f"(k) => localStorage.getItem(k)", ls_key)
                if val:
                    tokens[f"{ls_key}_localStorage"] = val
        except Exception as e:
            print(f"Warning: localStorage scan: {e}")

        # Save tokens
        if tokens:
            tokens["refreshed_at"] = time.time()
            with open(TOKEN_FILE, "w") as f:
                json.dump(tokens, f, indent=2)
            print(f"Tokens saved to {TOKEN_FILE}")
            print(f"Extracted keys: {list(tokens.keys())}")
            for k, v in tokens.items():
                if k != "refreshed_at":
                    print(f"  {k}: {str(v)[:60]}...")
            return tokens
        else:
            print("WARNING: No tokens found from cookies or localStorage!")
            return None

if __name__ == "__main__":
    refresh()
