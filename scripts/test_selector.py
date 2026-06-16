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
        
        # Click first odds to open betslip
        ws_eval("""
            (() => {
                let ev = document.querySelector('.virtual-event');
                let odds = ev.querySelector('.second-market').querySelectorAll('a.virtual-outcome .odds')[0];
                odds.click();
            })()
        """)
        time.sleep(2)
        
        # Test the selector
        selector = "aside input[placeholder*='min.']"
        found = ws_eval(f"document.querySelector(`{selector}`) !== null")
        print(f"Selector '{selector}' found: {found}")
        
        if not found:
            # Try broader search
            any_input = ws_eval("document.querySelector('input') !== null")
            print(f"Any input found on page: {any_input}")
            if any_input:
                input_details = ws_eval("""
                    (() => {
                        let i = document.querySelector('input');
                        return { placeholder: i.placeholder, outerHTML: i.outerHTML };
                    })()
                """)
                print(f"First input details: {json.dumps(input_details, indent=2)}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
