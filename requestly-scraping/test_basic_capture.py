#!/usr/bin/env python3
"""
test_basic_capture.py — Quick validation that Requestly SDK injection works.

Injects the Requestly web-sdk into a simple test page (example.com),
creates a SessionRecorder, records for 3 seconds, and saves session data.
"""

import json
import sys
import os

from playwright.sync_api import sync_playwright

# Path to the Requestly web-sdk dist file (pre-installed in /tmp/node_modules)
SDK_PATH = "/tmp/node_modules/@requestly/web-sdk/dist/requestly-web-sdk.min.js"


def main():
    if not os.path.exists(SDK_PATH):
        print(f"ERROR: Requestly SDK not found at {SDK_PATH}")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to a simple test page
        page.goto("https://example.com", wait_until="networkidle")
        print(f"[OK] Navigated to {page.url}")

        # Inject the Requestly SDK
        page.add_script_tag(path=SDK_PATH)
        print("[OK] Injected Requestly web-sdk")

        # Verify the SDK loaded
        sdk_ok = page.evaluate("typeof window.Requestly !== 'undefined' && typeof window.Requestly.SessionRecorder !== 'undefined'")
        if not sdk_ok:
            print("ERROR: Requestly SDK did not load properly")
            browser.close()
            sys.exit(1)
        print("[OK] Requestly.SessionRecorder is available")

        # Create a SessionRecorder with network + console recording, max 30s duration
        page.evaluate("""
            window.__recorder = new Requestly.SessionRecorder({
                network: true,
                console: true,
                maxDuration: 30000
            });
            window.__recorder.start();
        """)
        print("[OK] SessionRecorder created and started")

        # Wait 3 seconds to capture some activity
        page.wait_for_timeout(3000)

        # Stop recording and get session data
        result_json = page.evaluate("""
            window.__recorder.stop();
            JSON.stringify(window.__recorder.getSession());
        """)

        session = json.loads(result_json)

        # Save the full session
        output_path = "/tmp/requestly_test_session.json"
        with open(output_path, "w") as f:
            json.dump(session, f, indent=2)
        print(f"[OK] Full session saved to {output_path}")

        # Print summary
        events = session.get("events", {})
        network_events = events.get("network", [])
        rrweb_events = events.get("rrweb", [])

        print(f"\n--- Summary ---")
        print(f"  URL: {session.get('attributes', {}).get('url', 'N/A')}")
        print(f"  Duration: {session.get('attributes', {}).get('duration', 'N/A')}ms")
        print(f"  Network events captured: {len(network_events)}")
        print(f"  RRWeb events captured: {len(rrweb_events)}")

        if network_events:
            print(f"\n  First network event: {network_events[0].get('method')} {network_events[0].get('url')[:80]}")
        if rrweb_events:
            print(f"  First RRWeb event type: {rrweb_events[0].get('type')}")

        browser.close()
        print("\n[DONE] Basic capture test completed successfully")


if __name__ == "__main__":
    main()
