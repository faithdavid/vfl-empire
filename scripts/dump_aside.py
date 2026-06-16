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
        
        # Click first odds
        ws_eval("""
            (() => {
                let ev = document.querySelector('.virtual-event');
                let second = ev.querySelector('.second-market');
                let odds = second.querySelectorAll('a.virtual-outcome .odds')[0];
                odds.click();
            })()
        """)
        time.sleep(2)
        
        # Dump the aside HTML
        aside_html = ws_eval("document.querySelector('aside')?.outerHTML || 'Aside not found'")
        with open("/home/ubuntu/faith-workspace/vfl-empire/logs/aside_after_click.html", "w") as f:
            f.write(aside_html)
        print("Aside HTML saved.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
