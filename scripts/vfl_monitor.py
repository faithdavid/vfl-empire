#!/usr/bin/env python3
"""
VFL Monitor — autonomous match results watcher.
Runs on cron, checks MSport for new match day results, scrapes + merges + bridges.
"""
import json, urllib.request, sqlite3, os, sys
from datetime import datetime

# ─── CONFIG ───
HISTORY_DB = os.path.expanduser("~/Documents/Projects/vfl-data/databases/history.db")
BRIDGE_PATH = os.path.expanduser("~/.openclaw/workspace-town-steward/angel-inbox.json")
OUTDIR = os.path.expanduser("~/Documents/Projects/vfl-data/results-all")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
REF = "https://www.msport.com/ng/web/virtual/result"
SEASON_LIST_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/result/season/selection"
RESULTS_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/result?seasonId={}&matchDay={}"
CURRENT_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/current/match/day/info"

def bridge_log(event, details):
    """Append to activity log in angel-inbox.json."""
    try:
        with open(BRIDGE_PATH) as f:
            bridge = json.load(f)
    except:
        bridge = {}
    bridge["activity_log"] = bridge.get("activity_log", [])
    bridge["activity_log"].append({
        "timestamp": datetime.now().isoformat(),
        "event": event,
        **details
    })
    bridge["latest_monitor_run"] = {
        "timestamp": datetime.now().isoformat(),
        "event": event
    }
    with open(BRIDGE_PATH, 'w') as f:
        json.dump(bridge, f, indent=2)

def scrape_results(season_id, match_day):
    """Scrape results for one season+MD. Returns list of match dicts or None."""
    url = RESULTS_URL.format(season_id, match_day)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", "Referer": REF})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        results = data.get("data", {}).get("results")
        if not results:
            return None
        matches = []
        for m in results:
            ft_h, ft_a = m.get("fullTime","0:0").split(":")
            ht_h, ht_a = m.get("halfTime","0:0").split(":")
            matches.append({
                "season_id": season_id,
                "match_day": match_day,
                "home": m.get("homeTeam"),
                "away": m.get("awayTeam"),
                "first_goal": m.get("firstGoal"),
                "hth": int(ht_h or 0), "hta": int(ht_a or 0),
                "fth": int(ft_h or 0), "fta": int(ft_a or 0)
            })
        return matches
    except Exception as e:
        return None

def main():
    print(f"[{datetime.now().isoformat()}] VFL Monitor starting...")
    
    # 1. Get current season info
    req = urllib.request.Request(CURRENT_URL, headers={"User-Agent": UA, "Referer": REF})
    current = json.loads(urllib.request.urlopen(req, timeout=15).read().decode()).get("data", {})
    current_season = current.get("seasonId")
    current_md = current.get("matchDay")
    current_status = current.get("status")
    print(f"  Current: {current.get('seasonName')} MD{current_md} ({current_status})")
    
    # 2. Get season list to know max MDs
    req = urllib.request.Request(SEASON_LIST_URL, headers={"User-Agent": UA, "Accept": "application/json", "Referer": REF})
    seasons_data = json.loads(urllib.request.urlopen(req, timeout=15).read().decode()).get("data", [])
    season_map = {s["seasonId"]: s for s in seasons_data}
    
    # 3. For each season, check what we have vs what's available
    hist = sqlite3.connect(HISTORY_DB)
    
    total_new = 0
    for s in seasons_data:
        sid = s["seasonId"]
        available_mds = s["matchDay"]  # list of ints
        
        # What we already have in DB
        existing = set(r[0] for r in hist.execute(
            "SELECT DISTINCT day FROM matches WHERE season = ?", (sid,)).fetchall())
        
        needed_mds = [md for md in available_mds if md not in existing]
        
        if needed_mds:
            print(f"  {s['seasonName']}: missing MDs {needed_mds}")
            
            for md in needed_mds:
                matches = scrape_results(sid, md)
                if matches:
                    # Insert into DB
                    max_id = hist.execute("SELECT COALESCE(MAX(id), 0) FROM matches").fetchone()[0]
                    batch = []
                    for m in matches:
                        fth, fta = m["fth"], m["fta"]
                        outcome = "HOME" if fth > fta else ("AWAY" if fta > fth else "DRAW")
                        max_id += 1
                        batch.append((max_id, m["season_id"], m["match_day"], m["home"], m["away"],
                            None, None, None, None, None, None, None,
                            outcome, fth, fta, fth+fta, 1 if fth>0 and fta>0 else 0, 1 if fth+fta>2.5 else 0,
                            f"{m['hth']}:{m['hta']}", m["first_goal"], "0", datetime.now().isoformat(), "auto_monitor"))
                    
                    hist.executemany("""INSERT INTO matches (id, season, day, home, away,
                        oh, od, oa, o_o25, o_u25, o_gg, o_ng,
                        outcome, h, a, total, gg, o25,
                        half_time, first_goal, season_start_time, har_timestamp, source_file
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", batch)
                    hist.commit()
                    total_new += len(matches)
                    print(f"    MD{md}: {len(matches)} matches saved")
                    
                    # Bridge log
                    bridge_log("NEW_RESULTS", {
                        "season": s["seasonName"],
                        "match_day": md,
                        "matches": len(matches)
                    })
                else:
                    print(f"    MD{md}: no results yet")
    
    hist.close()
    
    # 4. Summary
    db_total = 0
    try:
        hist2 = sqlite3.connect(HISTORY_DB)
        db_total = hist2.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        hist2.close()
    except: pass
    
    print(f"\n[{datetime.now().isoformat()}] Monitor complete:")
    print(f"  New matches: {total_new}")
    print(f"  DB total: {db_total}")
    
    bridge_log("MONITOR_COMPLETE", {
        "new_matches": total_new,
        "db_total": db_total,
        "current_season": current.get("seasonName"),
        "current_md": current_md,
        "status": current_status
    })
    
    return total_new

if __name__ == "__main__":
    sys.exit(main())
