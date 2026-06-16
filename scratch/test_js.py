#!/usr/bin/env python3
import sys, json
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/scripts")
from browser_bet_placer import ws_eval, CHROME_WS

def debug_steps():
    res = ws_eval("""
        (() => {
            let steps = {};
            const containers = Array.from(document.querySelectorAll('.match-day'));
            steps.containers_count = containers.length;
            steps.container_texts = containers.map(c => {
                let bar = c.querySelector('.match-day-bar');
                return bar ? bar.innerText.replace(/\\n/g, ' ') : 'no_bar';
            });
            
            let target_md = "20";
            const targetContainer = containers.find(c => {
                const bar = c.querySelector('.match-day-bar');
                return bar && bar.innerText.includes('Match Day ' + target_md);
            });
            steps.target_container_found = !!targetContainer;
            
            if (targetContainer) {
                let events = targetContainer.querySelectorAll('.virtual-event');
                steps.events_count = events.length;
                steps.event_teams = Array.from(events).map(ev => {
                    let teams = ev.querySelector('.m-teams');
                    return teams ? teams.innerText.replace(/\\n/g, ' - ') : 'no_teams_el';
                });
            }
            return steps;
        })()
    """)
    return res

def main():
    try:
        print(json.dumps(debug_steps(), indent=2))
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if CHROME_WS:
            CHROME_WS.close()

if __name__ == "__main__":
    main()
