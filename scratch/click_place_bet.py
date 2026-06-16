#!/usr/bin/env python3
import sys, json, time
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/scripts")
from browser_bet_placer import ws_eval, ws_send, CHROME_WS

def main():
    try:
        print("Connected to Chromium via click_place_bet")
        
        # 1. Click "Place Bet"
        print("Clicking Place Bet...")
        clicked_place = ws_eval("""
            (() => {
                let btn = Array.from(document.querySelectorAll('button')).find(b => 
                    b.innerText.includes('Place Bet') && !b.innerText.includes('Add More')
                );
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            })()
        """)
        print(f"Place Bet button clicked: {clicked_place}")
        
        time.sleep(2.0)
        
        # 2. Click "Confirm Bet"
        print("Clicking Confirm Bet...")
        clicked_confirm = ws_eval("""
            (() => {
                let btn = Array.from(document.querySelectorAll('button')).find(b => 
                    b.innerText.trim() === 'Confirm Bet'
                );
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            })()
        """)
        print(f"Confirm Bet button clicked: {clicked_confirm}")
        
        time.sleep(2.0)
        
        # Take a screenshot to verify success
        res = ws_send("Page.captureScreenshot")
        with open("/home/ubuntu/faith-workspace/vfl-empire/logs/post_place_screenshot.png", "wb") as f:
            import base64
            f.write(base64.b64decode(res["data"]))
        print("Post-place screenshot saved to vfl-empire/logs/post_place_screenshot.png")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
