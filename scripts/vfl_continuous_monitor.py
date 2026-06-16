#!/usr/bin/env python3
"""VFL Continuous Monitor — Keeps the Akamai pipeline running, detecting matchdays and goals in real-time."""
import json, urllib.request, time, os, sys, subprocess, sqlite3
from datetime import datetime

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Origin': 'https://www.msport.com',
    'Referer': 'https://www.msport.com/ng/virtual/soccer',
}

AKAMAI_LIVE = "https://vfdirectdatalive-vs001.akamaized.net//46215/msportnigeriavflm/en/Europe:Berlin"
MSPORT_INFO = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/current/match/day/info"
MSPORT_EVENTS = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/event/list?sportId=vf:sport:1"

LOG_DIR = os.path.expanduser("~/faith-workspace/vfl-empire/logs/akamai_monitor")
os.makedirs(LOG_DIR, exist_ok=True)

def fetch(url, timeout=10):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except Exception as e:
        return None

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)
    with open(f"{LOG_DIR}/monitor.log", "a") as f:
        f.write(f"[{ts}] {msg}\n")

def log_event(event_type, data):
    with open(f"{LOG_DIR}/events.jsonl", "a") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(), "type": event_type, **data}) + "\n")

log("🔭 VFL Akamai Monitor STARTED")
log(f"   Logging to {LOG_DIR}")

last_md = None
last_goal_count = {}
team_map = {}

while True:
    try:
        # 1. Get current match info
        info = fetch(MSPORT_INFO)
        if not info:
            time.sleep(10)
            continue
        
        md = info['data']['matchDay']
        season_id = info['data']['seasonId']
        clean_sid = season_id.replace("vf:season:", "")
        status = info['data']['status']
        
        # 2. If new matchday detected, log it
        if md != last_md:
            log(f"📅 Matchday {md} detected (status={status})")
            log_event("matchday_detected", {"md": md, "season": season_id, "status": status})
            last_md = md
            last_goal_count = {}
            
            # Fetch team names for this MD
            ev_list = fetch(MSPORT_EVENTS)
            if ev_list and ev_list.get('data'):
                for md_entry in (ev_list['data'].get('matchDays') or []):
                    if md_entry.get('matchDay') == md:
                        for ev in (md_entry.get('events') or []):
                            team_map[ev.get('eventId','')] = (ev.get('homeTeam','?'), ev.get('awayTeam','?'))
                        break
                        
            # Run the EV Engine / Live Tracker on the new matchday
            try:
                log("⚡ Triggering EV Prediction and Settlement Engine...")
                script_path = os.path.expanduser("~/faith-workspace/vfl-empire/scripts/track_30_md.py")
                subprocess.run(["python3", script_path], check=True)
                
                # Connect to vfl_ev.db to log EV opportunities and alert on high-EV picks
                db_ev_path = os.path.expanduser("~/faith-workspace/vfl-empire/databases/vfl_ev.db")
                if os.path.exists(db_ev_path):
                    conn = sqlite3.connect(db_ev_path)
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT home_team, away_team, market, market_odds, ev_pct 
                        FROM market_ev 
                        WHERE season_name = ? AND match_day = ?;
                    """, (f"VFLM {clean_sid}", md))
                    ev_rows = cursor.fetchall()
                    conn.close()
                    
                    for home, away, market, odds, ev_pct in ev_rows:
                        if ev_pct >= 20.0:
                            log(f"🚨 ALERT: HIGH EV (>=20%) OPPORTUNITY DETECTED! {home} vs {away} | Market: {market} | Odds: {odds} | EV: {ev_pct:.1f}%")
                        elif ev_pct >= 10.0:
                            log(f"📈 EV Opportunity Detected: {home} vs {away} | Market: {market} | Odds: {odds} | EV: {ev_pct:.1f}%")
            except Exception as ev_err:
                log(f"⚠️ EV Engine Trigger Error: {ev_err}")
        
        # 3. If matchday is live, poll events feed for goals
        if status in ("MATCH", "FIRST_HALF", "SECOND_HALF"):
            url = f"{AKAMAI_LIVE}/vf_liveevents/{clean_sid}/league/{md}"
            events_resp = fetch(url, timeout=10)
            
            if events_resp:
                events = events_resp.get('data', {}).get('events', [])
                for e in events:
                    if e.get('type') == 'goal':
                        match_id = str(e['matchid'])
                        goal_key = f"{match_id}_{e.get('time')}"
                        
                        if goal_key not in last_goal_count:
                            last_goal_count[goal_key] = True
                            home, away = team_map.get(match_id, ('?','?'))
                            team = 'HOME' if e.get('team') == 'home' else 'AWAY'
                            log(f"🔥 GOAL! {home} vs {away} — {team} scores ({e.get('time')}min)")
                            log_event("goal_detected", {
                                "match_id": match_id, "home": home, "away": away,
                                "team": e.get('team'), "time": e.get('time')
                            })
        
        # 4. Check if scores updated (settlement)
        scores_url = f"{AKAMAI_LIVE}/vf_livescore/{clean_sid}/league/{md}"
        scores = fetch(scores_url, timeout=10)
        if scores and scores.get('data', {}).get('matches'):
            all_finished = True
            for mid, m in scores['data']['matches'].items():
                ft = m.get('periods', {}).get('ft', {})
                st = m.get('status', 100)
                if st != 100:
                    all_finished = False
                if st == 100 and m.get('_logged') is None:
                    m['_logged'] = True
                    home, away = team_map.get(mid, ('?','?'))
                    log(f"🏁 FT: {home} {ft.get('home',0)} - {ft.get('away',0)} {away}")
                    log_event("match_finished", {
                        "match_id": mid, "home": home, "away": away,
                        "score": f"{ft.get('home',0)}-{ft.get('away',0)}"
                    })
            if all_finished and len(scores['data']['matches']) >= 8:
                log("📊 All matches finished for this matchday")
                
    except Exception as e:
        log(f"⚠️ Error: {e}")
    
    time.sleep(5)
