#!/usr/bin/env python3
import sys, json
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/scripts")
from browser_bet_placer import ws_eval, CHROME_WS

def main():
    try:
        print("Connected to Chromium via debug_dom")
        
        # 1. Check all elements with class '.match-day' or similar
        match_days = ws_eval("""
            (() => {
                let els = document.querySelectorAll('*');
                let found = [];
                for (let el of els) {
                    let cls = el.className;
                    if (cls && typeof cls === 'string' && (cls.includes('match-day') || cls.includes('matchday'))) {
                        found.push({ tag: el.tagName, class: cls, text: el.innerText.substring(0, 100) });
                    }
                }
                return found;
            })()
        """)
        print("=== MATCH DAY / MATCHDAY CLASSES ===")
        print(json.dumps(match_days, indent=2))
        
        # 2. Check virtual events
        events = ws_eval("""
            (() => {
                let events = document.querySelectorAll('.virtual-event');
                let found = [];
                for (let ev of events) {
                    let teams = ev.querySelector('.m-teams')?.innerText || '';
                    let specText = ev.querySelector('.m-specifier-select .m-text')?.innerText || 'not found';
                    found.push({ teams, specText });
                }
                return found;
            })()
        """)
        print("\n=== VIRTUAL EVENTS ===")
        print(json.dumps(events, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
