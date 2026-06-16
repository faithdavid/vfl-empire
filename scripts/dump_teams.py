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
        
        teams = ws_eval("""
            (() => {
                let events = document.querySelectorAll('.virtual-event');
                return Array.from(events).map(ev => ev.querySelector('.m-teams')?.innerText);
            })()
        """)
        print(json.dumps(teams, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
