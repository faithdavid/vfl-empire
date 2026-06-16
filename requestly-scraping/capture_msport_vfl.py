#!/usr/bin/env python3
"""
capture_msport_vfl.py — Full MSport VFL network capture using Requestly SDK.

Navigates to https://www.msport.com/ng/web/virtual, injects the Requestly
web-sdk, records network traffic for ~30 seconds with page interactions,
and extracts all NETWORK events to a separate JSON file.

Includes stealth measures to mitigate Cloudflare/anti-bot detection.
"""

import json
import sys
import os

from playwright.sync_api import sync_playwright

SDK_PATH = "/tmp/node_modules/@requestly/web-sdk/dist/requestly-web-sdk.min.js"
MSPORT_URL = "https://www.msport.com/ng/web/virtual"
RECORD_DURATION_MS = 35000


def main():
    if not os.path.exists(SDK_PATH):
        print(f"ERROR: Requestly SDK not found at {SDK_PATH}")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
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
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {} };
        """)

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

        try:
            title = page.title()[:80]
        except Exception:
            title = "N/A"
        print(f"[OK] Title: {title}")

        # Inject Requestly SDK
        page.add_script_tag(path=SDK_PATH)
        print("[OK] Injected Requestly web-sdk")

        sdk_ok = page.evaluate(
            "typeof window.Requestly !== 'undefined' && "
            "typeof window.Requestly.SessionRecorder !== 'undefined'"
        )
        if not sdk_ok:
            print("ERROR: Requestly SDK did not load properly")
            browser.close()
            sys.exit(1)
        print("[OK] Requestly.SessionRecorder is available")

        # Start recording
        page.evaluate("""
            window.__recorder = new Requestly.SessionRecorder({
                network: true,
                maxDuration: 120000
            });
            window.__recorder.start();
        """)
        print("[OK] SessionRecorder started")

        # Wait for network activity
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            print("[!] networkidle timeout")
        page.wait_for_timeout(3000)

        # Try to navigate to virtual football if not already there
        current_url = page.url
        if "welcome" in current_url:
            print("[*] On welcome page, looking for virtual/sports links...")
            # Try clicking nav links that might go to virtual
            for link_text in ["Virtual", "Sports", "Football", "VFL"]:
                try:
                    link = page.get_by_role("link", name=link_text, exact=False).first
                    if link:
                        link.click(timeout=5000)
                        print(f"  Clicked '{link_text}' link")
                        page.wait_for_timeout(3000)
                        break
                except Exception:
                    pass

        # Simple scrolling
        print("[*] Scrolling...")
        for _ in range(3):
            page.evaluate("window.scrollBy(0, window.innerHeight * 0.6)")
            page.wait_for_timeout(1000)

        # Wait remaining time
        print(f"[*] Waiting for network capture...")
        page.wait_for_timeout(RECORD_DURATION_MS - 15000)

        # Stop recording and get session
        print("[*] Fetching session data...")
        try:
            result_json = page.evaluate("""
                try {
                    window.__recorder.stop();
                    JSON.stringify(window.__recorder.getSession());
                } catch(e) {
                    JSON.stringify({error: e.message});
                }
            """)
            session = json.loads(result_json)
        except Exception as e:
            print(f"[!] Failed to get session: {e}")
            session = {"attributes": {}, "events": {}}

        # Save full session
        full_path = "/tmp/requestly_msport_full.json"
        with open(full_path, "w") as f:
            json.dump(session, f, indent=2, default=str)
        print(f"[OK] Full session saved to {full_path}")

        # Extract and save network events
        events = session.get("events", {})
        network_events = events.get("network", [])

        net_path = "/tmp/requestly_msport_network.json"
        with open(net_path, "w") as f:
            json.dump(network_events, f, indent=2, default=str)
        print(f"[OK] Network events saved to {net_path}")

        # Print summary
        print(f"\n{'='*60}")
        print(f"  MSport Capture Summary")
        print(f"{'='*60}")
        print(f"  Final URL:  {session.get('attributes', {}).get('url', page.url)}")
        print(f"  Duration:   {session.get('attributes', {}).get('duration', 'N/A')}ms")
        print(f"  Network events: {len(network_events)}")
        print(f"{'='*60}")

        if network_events:
            print(f"\n  {'URL':<60} {'Method':<8} {'Status':<6}")
            print(f"  {'-'*60} {'-'*8} {'-'*6}")
            for ev in network_events:
                url = str(ev.get("url", ""))[:57]
                method = str(ev.get("method", "?"))
                status = str(ev.get("status", "?"))
                print(f"  {url:<60} {method:<8} {status:<6}")

        browser.close()
        print(f"\n[DONE] MSport capture completed")


if __name__ == "__main__":
    main()
