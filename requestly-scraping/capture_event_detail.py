#!/usr/bin/env python3
"""
capture_event_detail.py — Capture and save the decompressed JSON response
from the MSport VFL /event/detail API endpoint.

Intercepts the `/facts-center/query/frontend/virtual/event/detail` network
response using Playwright's native routing, automatically handles gzip/deflate
decompression, and saves the raw JSON to a file.

Usage:
    python3 capture_event_detail.py

Output:
    /home/ubuntu/faith-workspace/vfl-empire/data/raw/event_detail_capture.json
"""

import json
import sys
import os
import time

from playwright.sync_api import sync_playwright

# ── Configuration ──────────────────────────────────────────────────────────────
TARGET_URL_PATTERN = "/facts-center/query/frontend/virtual/event/detail"
MSPORT_URL = "https://www.msport.com/ng/web/virtual"
OUTPUT_PATH = "/home/ubuntu/faith-workspace/vfl-empire/data/raw/event_detail_capture.json"
TIMEOUT_SECONDS = 60
POLL_INTERVAL_MS = 500

# Requestly SDK path (optional — for fallback; primary uses native routing)
SDK_PATH = "/tmp/node_modules/@requestly/web-sdk/dist/requestly-web-sdk.min.js"


def main():
    captured_data = {
        "captured": False,
        "url": None,
        "data": None,
        "error": None,
    }

    with sync_playwright() as p:
        # ── Launch browser with stealth args ──────────────────────────────
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-GB",
            timezone_id="Africa/Lagos",
        )

        page = context.new_page()

        # Stealth: hide automation markers
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {} };
        """)

        # ── Flag to signal capture completion ─────────────────────────────
        captured_event = {"done": False}

        def handle_response(response):
            """Intercept every response and check for our target URL."""
            if captured_event["done"]:
                return

            url = response.url
            if TARGET_URL_PATTERN not in url:
                return

            print(f"[*] Matched target URL: {url}")
            print(f"[*] Response status: {response.status} {response.status_text}")
            print(f"[*] Content-Type: {response.headers.get('content-type', 'N/A')}")

            try:
                # `response.body()` automatically decompresses gzip/deflate/brotli
                body_bytes = response.body()
                print(f"[*] Raw body size: {len(body_bytes)} bytes")

                # Attempt JSON parse
                try:
                    data = json.loads(body_bytes)
                except json.JSONDecodeError:
                    # If not valid JSON, try decoding as text and report
                    text = body_bytes.decode("utf-8", errors="replace")
                    print(f"[!] Response is not valid JSON. Raw preview (first 300 chars):")
                    print(f"    {text[:300]}")
                    data = {"_raw_text": text, "_note": "Response was not valid JSON"}

                captured_data["captured"] = True
                captured_data["url"] = url
                captured_data["data"] = data
                captured_event["done"] = True

                print(f"[OK] Successfully captured and parsed response "
                      f"({len(body_bytes)} bytes)")

            except Exception as e:
                print(f"[!] Error processing response: {e}")
                captured_data["error"] = str(e)
                # Still mark done to exit
                captured_event["done"] = True

        # Register the response handler
        page.on("response", handle_response)

        # ── Also intercept request-level via route for visibility ─────────
        def handle_route(route):
            """Log matching requests before they go out (for diagnostics)."""
            if TARGET_URL_PATTERN in route.request.url:
                print(f"[*] Request detected: {route.request.method} {route.request.url}")
            route.continue_()

        page.route("**/*", handle_route)

        # ── Navigate to the VFL page ──────────────────────────────────────
        print(f"[*] Navigating to {MSPORT_URL}")
        try:
            page.goto(MSPORT_URL, wait_until="load", timeout=30000)
            print(f"[OK] Page loaded: {page.url}")
        except Exception as e:
            print(f"[!] Navigation issue: {e}")
            try:
                print(f"[*] Current URL: {page.url}")
            except Exception:
                pass

        # Print page title for diagnostics
        try:
            title = page.title()[:80]
            print(f"[OK] Page title: {title}")
        except Exception:
            pass

        # ── Page interactions to trigger API calls ────────────────────────
        # Wait a moment for initial render, then scroll/interact
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            print("[!] networkidle timeout (non-fatal)")

        # If we landed on a welcome page, try clicking navigation links
        current_url = page.url
        if "welcome" in current_url.lower() or "home" in current_url.lower():
            print("[*] On landing page, looking for Virtual/Sports links...")
            for link_text in ["Virtual", "Sports", "Football", "VFL", "Virtual Football"]:
                try:
                    link = page.get_by_role("link", name=link_text, exact=False).first
                    if link and link.is_visible():
                        link.click(timeout=5000)
                        print(f"  Clicked '{link_text}' link")
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass

        # Scroll the page to trigger lazy loads
        print("[*] Scrolling to trigger API calls...")
        for _ in range(5):
            if captured_event["done"]:
                break
            page.evaluate("window.scrollBy(0, window.innerHeight * 0.7)")
            page.wait_for_timeout(800)

        # ── Wait for capture with timeout ─────────────────────────────────
        start_time = time.time()
        print(f"[*] Waiting for {TARGET_URL_PATTERN} "
              f"(timeout: {TIMEOUT_SECONDS}s)...")

        while time.time() - start_time < TIMEOUT_SECONDS:
            if captured_event["done"]:
                elapsed = time.time() - start_time
                print(f"[OK] Target response captured after {elapsed:.1f}s")
                break
            page.wait_for_timeout(POLL_INTERVAL_MS)

        # ── Handle timeout ────────────────────────────────────────────────
        if not captured_event["done"]:
            print(f"[!] TIMEOUT: No {TARGET_URL_PATTERN} call "
                  f"intercepted within {TIMEOUT_SECONDS}s")
            # Dump some diagnostics
            print("[*] URLs seen during session (first 15):")
            seen_urls = page.evaluate("""() => {
                const entries = performance.getEntriesByType('resource');
                return entries.slice(-30).map(e => e.name);
            }""")
            if seen_urls:
                for u in seen_urls:
                    print(f"  - {u[:150]}")
            browser.close()
            sys.exit(1)

        # ── Save captured data ────────────────────────────────────────────
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(captured_data["data"], f, indent=2, default=str)
        print(f"[OK] Saved captured JSON to {OUTPUT_PATH}")
        print(f"     File size: {os.path.getsize(OUTPUT_PATH)} bytes")

        # ── Cleanup ───────────────────────────────────────────────────────
        browser.close()
        print("[DONE] Event detail capture completed successfully")


if __name__ == "__main__":
    main()
