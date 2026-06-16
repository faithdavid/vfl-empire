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
        
        # Dump the first virtual event's second-market HTML
        res = ws_eval("""
            (() => {
                let ev = document.querySelector('.virtual-event');
                if (!ev) return 'No event found';
                let teams = ev.querySelector('.m-teams')?.innerText || 'No teams';
                let second = ev.querySelector('.second-market')?.outerHTML || 'No second market';
                return { teams, second };
            })()
        """)
        print(json.dumps(res, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
