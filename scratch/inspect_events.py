#!/usr/bin/env python3
import sys, json
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/scripts")
from browser_bet_placer import ws_eval, CHROME_WS

def inspect_all():
    res = ws_eval("""
        (() => {
            let info = [];
            const containers = Array.from(document.querySelectorAll('.match-day'));
            for (let c of containers) {
                let bar = c.querySelector('.match-day-bar')?.innerText.replace(/\\n/g, ' ') || 'no_bar';
                let events = c.querySelectorAll('.virtual-event');
                for (let ev of events) {
                    let teams = ev.querySelector('.m-teams')?.innerText.replace(/\\n/g, ' - ') || 'no_teams';
                    let specText = ev.querySelector('.m-specifier-select .m-text')?.innerText || 'no_spec';
                    
                    // Over button
                    let secondMarket = ev.querySelector('.second-market');
                    let oddsEls = secondMarket ? secondMarket.querySelectorAll('a.virtual-outcome') : [];
                    let over_coords = 'no_over';
                    if (oddsEls.length > 0) {
                        let r = oddsEls[0].getBoundingClientRect();
                        over_coords = { x: r.x + r.width/2, y: r.y + r.height/2, width: r.width, height: r.height };
                    }
                    
                    info.push({
                        bar,
                        teams,
                        specText,
                        over_coords
                    });
                }
            }
            return info;
        })()
    """)
    return res

def main():
    try:
        print(json.dumps(inspect_all(), indent=2))
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
