#!/usr/bin/env python3
import json
import logging
from pathlib import Path
import subprocess

BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
JSON_PATH = SCRIPTS_DIR / "predictions_latest.json"
RESULTS_PATH = BASE_DIR / "signals" / "results_last12h_compiled.json"
STATE_FILE = SCRIPTS_DIR / ".overquota_state"
DISCORD_TARGET = "discord:1507922324072960031:1516407526491684944"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("overquota_daemon")

def send_to_discord(title, content):
    logger.info("Sending over-quota alert to Discord...")
    try:
        subprocess.run(
            ["/home/ubuntu/.local/bin/hermes", "send", "--to", DISCORD_TARGET, f"**{title}**\n\n{content}"],
            capture_output=True, text=True, check=True
        )
        logger.info(f"Successfully posted to Discord.")
    except Exception as e:
        logger.error(f"Error posting to Discord: {e}")

def run():
    if not JSON_PATH.exists() or not RESULTS_PATH.exists():
        return

    # Load upcoming matchday
    with open(JSON_PATH, "r") as f:
        data = json.load(f)
    if not data.get('matchdays'):
        return
    md = data['matchdays'][0]
    season = md.get('season_id', 'Unknown')
    matchday = md.get('matchday', 'Unknown')
    try:
        md_num = int(matchday)
    except:
        return
        
    # Over-Quota only applies in second half of season
    if md_num < 16:
        return

    current_state = f"{season}-{matchday}"
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            last_posted = f.read().strip()
            if last_posted == current_state:
                return

    # Load all historical matches for MD15 standings and Leg 1 results
    with open(RESULTS_PATH, "r") as f:
        res_data = json.load(f)
    matches = res_data.get('matches', [])
    
    # Filter matches for THIS season only
    season_matches = [m for m in matches if m['season'] == season]
    
    # Calculate MD15 standings
    team_stats = {t: {'pts': 0, 'w': 0, 'd': 0, 'l': 0} for t in set([m['home_team'] for m in season_matches])}
    for m in season_matches:
        if m['match_day'] > 15: continue
        h, a = m['home_team'], m['away_team']
        hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
        if hg > ag:
            team_stats[h]['pts'] += 3; team_stats[h]['w'] += 1; team_stats[a]['l'] += 1
        elif hg == ag:
            team_stats[h]['pts'] += 1; team_stats[h]['d'] += 1; team_stats[a]['pts'] += 1; team_stats[a]['d'] += 1
        else:
            team_stats[a]['pts'] += 3; team_stats[a]['w'] += 1; team_stats[h]['l'] += 1

    sorted_teams = sorted(team_stats.items(), key=lambda x: x[1]['pts'], reverse=True)
    md15_ranks = {t: i+1 for i, (t, _) in enumerate(sorted_teams)}
    over_quota_teams = [t for t, s in team_stats.items() if s['pts'] > 30]

    locks_found = []
    
    for fix in md.get('fixtures', []):
        h2 = fix.get('home')
        a2 = fix.get('away')
        odds = fix.get('odds', {})
        
        # We need either home or away to be over-quota
        if h2 not in over_quota_teams and a2 not in over_quota_teams:
            continue
            
        # Find Leg 1 result
        l1_matches = [m for m in season_matches if m['match_day'] == md_num - 15 and m['home_team'] == a2 and m['away_team'] == h2]
        if not l1_matches: continue
        l1 = l1_matches[0]
        
        hg1, ag1 = l1.get('home_goals', 0), l1.get('away_goals', 0)
        if hg1 == ag1: continue # Must be a win/loss in Leg 1
        
        winner1 = l1['home_team'] if hg1 > ag1 else l1['away_team']
        loser1 = l1['away_team'] if hg1 > ag1 else l1['home_team']
        
        # Check condition: Over-Quota team won Leg 1 against a non-top-6 team
        if winner1 in over_quota_teams and md15_ranks.get(loser1, 16) > 6:
            # The Sabotage Trap is triggered!
            # We fade the Over-Quota team in this reverse fixture.
            underdog = loser1
            elite = winner1
            
            if h2 == underdog:
                bet = "1X (Home Win/Draw)"
                outright = "1 (Home Win)"
                dc_odds = round(1.0 / ((1.0/float(odds.get('home_win', 1))) + (1.0/float(odds.get('draw', 1)))), 2) if float(odds.get('home_win', 0)) > 0 else "2.20+"
            else:
                bet = "X2 (Away Win/Draw)"
                outright = "2 (Away Win)"
                dc_odds = round(1.0 / ((1.0/float(odds.get('away_win', 1))) + (1.0/float(odds.get('draw', 1)))), 2) if float(odds.get('away_win', 0)) > 0 else "2.20+"
                
            locks_found.append({
                "fixture": f"{h2} vs {a2}",
                "elite": elite,
                "underdog": underdog,
                "bet": bet,
                "outright": outright,
                "dc_odds": dc_odds
            })

    if locks_found:
        content = "## 🚨 OVER-QUOTA SABOTAGE TRAP DETECTED 🚨\n\n"
        content += "The algorithm is attempting to rubber-band an Over-Quota Elite team by forcing a drop in points against an Underdog they beat in Leg 1.\n\n"
        for idx, lock in enumerate(locks_found):
            content += f"**{idx+1}. {lock['fixture']}**\n"
            content += f"**Fading:** {lock['elite']} (Over-Quota)\n"
            content += f"**Safe Bet (Double Chance):** {lock['bet']} @ ~{lock['dc_odds']}\n"
            content += f"**High-Risk / High-Reward:** {lock['outright']} @ ~6.00+\n\n"
            
        send_to_discord(f"MD {matchday} Over-Quota Fade Locks ({season})", content)
    
    with open(STATE_FILE, "w") as f:
        f.write(current_state)

if __name__ == "__main__":
    run()
