#!/usr/bin/env python3
import sys, json, time
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/scripts")
from browser_bet_placer import ws_eval, CHROME_WS

def test_direct_click(home, away, target_md, market_col):
    target_md_js = f"'{target_md}'" if target_md else "null"
    res = ws_eval(f"""
        (() => {{
            let root = document;
            let target_md = {target_md_js};
            if (target_md) {{
                const containers = Array.from(document.querySelectorAll('.match-day'));
                const targetContainer = containers.find(c => {{
                    const bar = c.querySelector('.match-day-bar');
                    return bar && bar.innerText.includes('Match Day ' + target_md);
                }});
                if (targetContainer) root = targetContainer;
            }}
            let events = root.querySelectorAll('.virtual-event');
            for (let ev of events) {{
                let teams = ev.querySelector('.m-teams');
                if (!teams) continue;
                let txt = teams.innerText.toLowerCase();
                if (txt.includes('{home.lower()}') && txt.includes('{away.lower()}')) {{
                    let secondMarket = ev.querySelector('.second-market');
                    if (!secondMarket) return 'no_second_market';
                    let oddsEls = secondMarket.querySelectorAll('a.virtual-outcome');
                    if (oddsEls.length > {market_col}) {{
                        let el = oddsEls[{market_col}];
                        el.click();
                        return 'clicked';
                    }}
                    return 'odds_not_found';
                }}
            }}
            return 'fixture_not_found';
        }})()
    """)
    return res

def main():
    try:
        print("Clicking Leeds vs Wolverhampton...")
        print(test_direct_click("Leeds", "Wolverhampton", "20", 0))
        time.sleep(1)
        
        print("Clicking Chelsea vs Manchester Red...")
        print(test_direct_click("Chelsea", "Manchester Red", "20", 0))
        time.sleep(1)
        
        # Check betslip count
        betslip_count = ws_eval("document.querySelector('.m-count-ball')?.innerText || '0'")
        print(f"Betslip selections count: {betslip_count}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
