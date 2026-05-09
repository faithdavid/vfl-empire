#!/usr/bin/env python3
"""
VFL MASTER CYCLE — runs every 5 minutes.
1. Check for new results → scrape → merge
2. Run predictions on upcoming odds
3. Settle pending predictions
4. LOG EVERYTHING to bridge
5. Notify user of anything interesting
"""
import json, urllib.request, sqlite3, os, sys, traceback
from datetime import datetime

# ─── CONFIG ───
HISTORY_DB = os.path.expanduser("~/Documents/Projects/vfl-data/databases/history.db")
SOVEREIGN_DB = os.path.expanduser("~/Documents/Projects/vfl-data/databases/sovereign.db")
BRIDGE_PATH = os.path.expanduser("~/.openclaw/workspace-town-steward/angel-inbox.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
REF = "https://www.msport.com/ng/web/virtual"
SEASON_LIST_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/result/season/selection"
RESULTS_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/result?seasonId={}&matchDay={}"
CURRENT_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/current/match/day/info"
EVENT_LIST_URL = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/event/list?sportId=vf:sport:1"

# Calibration constants
HWR, DWR, AWR = 0.456, 0.239, 0.306
GGR, O25R = 0.490, 0.488
FG_H, FG_H_WIN, FG_A_WIN = 0.523, 0.759, 0.655
HT_H_WIN, HT_D_DRAW, HT_A_WIN = 0.823, 0.376, 0.740

def api_get(url, headers=None, timeout=12):
    hdrs = {"User-Agent": UA, "Referer": REF}
    if headers: hdrs.update(headers)
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=timeout).read())

def bridge_log(events):
    """Write one or more events to bridge activity log."""
    try:
        with open(BRIDGE_PATH) as f:
            bridge = json.load(f)
    except:
        bridge = {}
    bridge["activity_log"] = bridge.get("activity_log", [])
    if not isinstance(events, list):
        events = [events]
    for e in events:
        bridge["activity_log"].append({"timestamp": datetime.now().isoformat(), **e})
    bridge["last_cycle"] = datetime.now().isoformat()
    with open(BRIDGE_PATH, 'w') as f:
        json.dump(bridge, f, indent=2)

# ═══════════════════════════════════════════════════════════════
# PHASE 1: MONITOR — scrape new results
# ═══════════════════════════════════════════════════════════════
def phase_monitor():
    logs = []
    total_new = 0
    try:
        current = api_get(CURRENT_URL)
        season_data = api_get(SEASON_LIST_URL)
        current_season = current.get("data", {}).get("seasonName", "?")
        current_md = current.get("data", {}).get("matchDay", "?")
        current_status = current.get("data", {}).get("status", "?")
        
        hist = sqlite3.connect(HISTORY_DB)
        for s in season_data.get("data", []):
            sid = s["seasonId"]
            available_mds = s["matchDay"]
            existing = set(r[0] for r in hist.execute(
                "SELECT DISTINCT day FROM matches WHERE season = ?", (sid,)).fetchall())
            
            for md in available_mds:
                if md in existing:
                    continue
                try:
                    url = RESULTS_URL.format(sid, md)
                    data = api_get(url)
                    results = data.get("data", {}).get("results")
                    if not results:
                        continue
                    
                    max_id = hist.execute("SELECT COALESCE(MAX(id), 0) FROM matches").fetchone()[0]
                    batch = []
                    for rm in results:
                        ft_h, ft_a = map(int, rm.get("fullTime","0:0").split(":"))
                        ht_h, ht_a = map(int, rm.get("halfTime","0:0").split(":"))
                        outcome = "HOME" if ft_h > ft_a else ("AWAY" if ft_a > ft_h else "DRAW")
                        max_id += 1
                        batch.append((max_id, sid, md, rm.get("homeTeam"), rm.get("awayTeam"),
                            None, None, None, None, None, None, None,
                            outcome, ft_h, ft_a, ft_h+ft_a, 1 if ft_h>0 and ft_a>0 else 0, 1 if ft_h+ft_a>2.5 else 0,
                            f"{ht_h}:{ht_a}", rm.get("firstGoal"), "0", datetime.now().isoformat(), "auto_monitor"))
                    
                    hist.executemany("""INSERT INTO matches (id, season, day, home, away,
                        oh, od, oa, o_o25, o_u25, o_gg, o_ng,
                        outcome, h, a, total, gg, o25,
                        half_time, first_goal, season_start_time, har_timestamp, source_file
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", batch)
                    hist.commit()
                    total_new += len(batch)
                    logs.append({"event": f"NEW_RESULTS_{s['seasonName']}", "md": md, "count": len(batch)})
                except Exception as e:
                    pass
        
        hist.close()
        
        if total_new:
            logs.append({"event": "MONITOR_COMPLETE", "new_matches": total_new, "season": current_season, "md": current_md, "status": current_status})
        
    except Exception as e:
        logs.append({"event": "MONITOR_ERROR", "error": str(e)[:100]})
    
    return total_new, logs

# ═══════════════════════════════════════════════════════════════
# PHASE 2: PREDICT — find value bets
# ═══════════════════════════════════════════════════════════════
def calc_sf(implied_prob, historical_rate):
    """Safety Factor = historical / fair_implied"""
    if implied_prob <= 0:
        return 0
    return historical_rate / implied_prob

def phase_predict():
    logs = []
    predictions_made = 0
    
    try:
        data = api_get(EVENT_LIST_URL, {"operId": "2"})
        conn = sqlite3.connect(SOVEREIGN_DB)
        
        for md_entry in data.get("data", {}).get("matchDays", []):
            md = md_entry.get("matchDay")
            for e in md_entry.get("events", []):
                home = e.get("homeTeam")
                away = e.get("awayTeam")
                ev_id = e.get("eventId")
                markets = {m["id"]: m for m in e.get("markets", [])}
                
                # 1x2
                m1 = markets.get(1, {})
                outs = {o["description"]: float(o["odds"]) for o in m1.get("outcomes", [])}
                oh, od, oa = outs.get("Home", 0), outs.get("Draw", 0), outs.get("Away", 0)
                if not oh: continue
                
                imp = [1/oh, 1/od, 1/oa]
                total = sum(imp)
                fair = [i/total for i in imp]
                
                sfs = [
                    ("HOME", oh, calc_sf(fair[0], HWR)),
                    ("DRAW", od, calc_sf(fair[1], DWR)),
                    ("AWAY", oa, calc_sf(fair[2], AWR)),
                ]
                
                for outcome, odds_val, sf in sfs:
                    if sf > 1.15:
                        match_id = f"{ev_id}_{outcome}"
                        conn.execute("""INSERT OR IGNORE INTO master_ledger 
                            (match_id, season_id, match_day, home_team, away_team,
                             odds_h, odds_d, odds_a, prediction, certainty, label, created_at, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                            match_id, "vf:season:3086378", md, home, away,
                            oh, od, oa, outcome, round(sf, 3),
                            f"fellinius_sf{sf:.2f}", datetime.now().isoformat(), "PENDING"))
                        if conn.total_changes > 0:
                            predictions_made += 1
        
        conn.commit()
        conn.close()
        
        if predictions_made:
            logs.append({"event": "PREDICTIONS_MADE", "count": predictions_made})
        
    except Exception as e:
        logs.append({"event": "PREDICT_ERROR", "error": str(e)[:100]})
    
    return predictions_made, logs

# ═══════════════════════════════════════════════════════════════
# PHASE 3: SETTLE — check results for pending predictions
# ═══════════════════════════════════════════════════════════════
def phase_settle():
    logs = []
    wins = 0
    losses = 0
    
    try:
        conn = sqlite3.connect(SOVEREIGN_DB)
        
        # Find current season from history or use the latest season
        try:
            hist = sqlite3.connect(HISTORY_DB)
            current_season = hist.execute(
                "SELECT season FROM matches ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
            hist.close()
        except:
            current_season = "vf:season:3086378"
        
        # Only settle predictions for current season — old ones are unreachable
        pending = conn.execute("""
            SELECT match_id, season_id, match_day, home_team, away_team, 
                   odds_h, odds_d, odds_a, prediction
            FROM master_ledger WHERE status = 'PENDING' AND season_id = ?
        """, (current_season,)).fetchall()
        
        for row in pending:
            mid, sid, md, home, away, oh, od, oa, pred = row
            
            # Get results for this MD and season
            url = RESULTS_URL.format(sid, md)
            try:
                data = api_get(url)
                for r in data.get("data", {}).get("results", []):
                    if r.get("homeTeam") == home and r.get("awayTeam") == away:
                        ft_h, ft_a = map(int, r.get("fullTime","0:0").split(":"))
                        actual = "HOME" if ft_h > ft_a else ("AWAY" if ft_a > ft_h else "DRAW")
                        
                        # Map prediction to payout
                        if actual == pred:
                            p_l = oh if pred == "HOME" else (od if pred == "DRAW" else oa)
                            status = "WON"
                            wins += 1
                        else:
                            p_l = -1.0
                            status = "LOST"
                            losses += 1
                        
                        conn.execute("""UPDATE master_ledger SET 
                            full_time=?, actual_h=?, actual_a=?, outcome=?, p_l=?, 
                            settled_at=?, status=?
                            WHERE match_id=?""", (
                            f"{ft_h}:{ft_a}", ft_h, ft_a, actual, p_l,
                            datetime.now().isoformat(), status, mid))
                        break
            except:
                pass
        
        conn.commit()
        conn.close()
        
        if wins or losses:
            logs.append({"event": "SETTLEMENTS", "wins": wins, "losses": losses, "total": wins+losses})
        
    except Exception as e:
        logs.append({"event": "SETTLE_ERROR", "error": str(e)[:100]})
    
    return wins, losses, logs

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    cycle_start = datetime.now().isoformat()
    all_logs = []
    total_info = {"new_results": 0, "predictions": 0, "wins": 0, "losses": 0}
    
    print(f"🔄 VFL Master Cycle [{cycle_start}]")
    
    # Phase 1
    nr, logs1 = phase_monitor()
    total_info["new_results"] = nr
    all_logs.extend(logs1)
    if nr: print(f"  📥 {nr} new results scraped")
    
    # Phase 2
    np, logs2 = phase_predict()
    total_info["predictions"] = np
    all_logs.extend(logs2)
    if np: print(f"  🔮 {np} new predictions placed")
    
    # Phase 3
    w, l, logs3 = phase_settle()
    total_info["wins"] = w
    total_info["losses"] = l
    all_logs.extend(logs3)
    if w or l: print(f"  ✅ {w} WON / ❌ {l} LOST")
    
    # Log everything to bridge
    bridge_log(all_logs)
    
    # Summary
    print(f"✅ Cycle complete — bridge updated with {len(all_logs)} event(s)")
    
    # Print summary for cron delivery to Telegram
    if total_info["new_results"] or total_info["predictions"] or total_info["wins"] or total_info["losses"]:
        print(f"\n📊 CYCLE SUMMARY")
        if total_info["new_results"]:
            print(f"  📥 {total_info['new_results']} new matches scraped")
        if total_info["predictions"]:
            print(f"  🔮 {total_info['predictions']} new predictions placed")
        if total_info["wins"]:
            print(f"  ✅ WON: {total_info['wins']}")
        if total_info["losses"]:
            print(f"  ❌ LOST: {total_info['losses']}")
    
    return total_info

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        bridge_log([{"event": "FATAL_ERROR", "error": str(e)[:200], "trace": traceback.format_exc()[:200]}])
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
