#!/usr/bin/env python3
import json, sys, os, time
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/scripts")
from browser_bet_placer import ws_send, ws_eval, login, CHROME_WS

def main():
    try:
        ws_send("Page.enable")
        ws_send("Runtime.enable")
        login()
        time.sleep(2)
        
        # Try to click the first Over 1.5 odds using JS click first
        print("Attempting JS click on first Over 1.5 odds...")
        res = ws_eval("""
            (() => {
                let ev = document.querySelector('.virtual-event');
                if (!ev) return 'No event found';
                let second = ev.querySelector('.second-market');
                if (!second) return 'No second market';
                let odds = second.querySelectorAll('a.virtual-outcome .odds')[0];
                if (!odds) return 'No odds found';
                odds.click();
                return 'Clicked ' + ev.querySelector('.m-teams').innerText;
            })()
        """)
        print(f"Result: {res}")
        time.sleep(2)
        
        # Check if betslip is open
        aside_html = ws_eval("document.querySelector('aside')?.innerHTML || 'Aside not found'")
        if "input" in aside_html.lower():
            print("SUCCESS: Betslip opened with JS click!")
        else:
            print("FAILURE: Betslip NOT opened with JS click.")
            
            # Try robust click if JS failed
            print("Attempting robust click...")
            # We need a selector for ws_click. Let's find one.
            # We can use a unique path or just select by index in JS then get box.
            box = ws_eval("""
                (() => {
                    let ev = document.querySelector('.virtual-event');
                    let odds = ev.querySelector('.second-market').querySelectorAll('a.virtual-outcome .odds')[0];
                    const r = odds.getBoundingClientRect();
                    return {x: r.x + r.width/2, y: r.y + r.height/2};
                })()
            """)
            x, y = box["x"], box["y"]
            ws_send("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": x, "y": y, "button": "left",
                "clickCount": 1, "buttons": 1
            })
            ws_send("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": x, "y": y, "button": "left",
                "clickCount": 1
            })
            print("Robust click dispatched.")
            time.sleep(2)
            
            aside_html_v2 = ws_eval("document.querySelector('aside')?.innerHTML || 'Aside not found'")
            if "input" in aside_html_v2.lower():
                print("SUCCESS: Betslip opened with robust click!")
            else:
                print("FAILURE: Betslip STILL NOT opened.")
                print(f"Aside HTML snippet: {aside_html_v2[:200]}...")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
