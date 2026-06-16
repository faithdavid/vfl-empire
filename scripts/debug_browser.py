#!/usr/bin/env python3
import json, sys, os, time
from pathlib import Path

# Add the scripts dir to path
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/scripts")
from browser_bet_placer import ws_send, ws_eval, login, get_balance, CHROME_WS

def main():
    try:
        ws_send("Page.enable")
        ws_send("Runtime.enable")
        print("Connected to Chromium")
        
        login()
        bal = get_balance()
        print(f"Balance: {bal}")
        
        # Override device metrics to 1600x1000
        ws_send("Emulation.setDeviceMetricsOverride", {
            "width": 1600,
            "height": 1000,
            "deviceScaleFactor": 1,
            "mobile": False
        })
        time.sleep(2)
        
        # Take screenshot
        res = ws_send("Page.captureScreenshot")
        with open("/home/ubuntu/faith-workspace/vfl-empire/logs/debug_screenshot.png", "wb") as f:
            import base64
            f.write(base64.b64decode(res["data"]))
        print("Screenshot saved to vfl-empire/logs/debug_screenshot.png")
        
        # Dump betslip area DOM
        betslip_html = ws_eval("document.querySelector('aside')?.innerHTML || 'Aside not found'")
        print(f"Betslip HTML snippet: {betslip_html[:500]}...")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
