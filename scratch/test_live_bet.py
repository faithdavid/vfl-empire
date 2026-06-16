import sys
import logging
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from vfl_live_oracle_bot import place_bet_via_browser
from msport_api import get_event_list, _normalise_team_name

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger()

def run_test():
    log.info("Fetching live events from MSport...")
    events = get_event_list()
    if not events or not events[0].get('events'):
        log.error("Could not fetch upcoming events.")
        return

    # Grab the very first match on the board
    ev = events[0]['events'][0]
    home = ev.get('homeTeam') or ev.get('homeTeamName', '')
    away = ev.get('awayTeam') or ev.get('awayTeamName', '')
    
    home_norm = _normalise_team_name(home)
    away_norm = _normalise_team_name(away)
    
    fixture = f"{home_norm} vs {away_norm}"
    locks = [{'fixture': fixture, 'lock': 'hw'}]  # We bet Home Win
    
    stake = 10.0
    log.info(f"Test Lock Triggered: {fixture}")
    log.info(f"Attempting to place real ₦{stake} bet...")
    
    success, bal = place_bet_via_browser(locks, stake)
    
    if success:
        log.info("✅ SUCCESS! Bet was placed successfully.")
        log.info(f"Balance reported after placement attempt: {bal}")
    else:
        log.error("❌ FAILED! The browser automation failed to place the bet.")
        log.info(f"Balance reported: {bal}")

if __name__ == '__main__':
    run_test()
