#!/usr/bin/env python3
"""
🧝‍♀️ VERITY — VFL Settlement Agent
Named after Veritas, Roman goddess of truth.
She verifies predictions against reality, marking them WON or LOST.
"""
import urllib.request, json, os, sys
from datetime import datetime
from collections import defaultdict

# ─── VERITY'S IDENTITY ───
NAME = "Verity"
TITLE = "Settlement Agent of the Trillion Empire"
SIGIL = "🧝‍♀️"
MOTTO = "Truth is the only settlement."

# ─── CONFIG ───
LEDGER_PATH = os.path.expanduser("~/.hermes/cron/state/vfl_ledger.json")
ACCURACY_PATH = os.path.expanduser("~/Documents/Projects/vfl-data/models/accuracy_tracker.json")
TABLE_DIR = os.path.expanduser("~/Documents/Projects/vfl-data/tables")
UA = "Mozilla/5.0"
os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
os.makedirs(TABLE_DIR, exist_ok=True)

def outcome_from_ft(ft):
    try:
        h, a = map(int, ft.split(':'))
        if h > a: return "HOME"
        elif a > h: return "AWAY"
        else: return "DRAW"
    except:
        return None

def get_current_season():
    url = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/current/match/day/info"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    d = data.get("data", {})
    return {
        'season_id': d.get('seasonId', ''),
        'season_name': d.get('seasonName', ''),
        'match_day': d.get('matchDay'),
        'status': d.get('status')
    }

def check_results_for_md(season_id, md):
    url = f"https://www.msport.com/api/ng/facts-center/query/frontend/virtual/result?seasonId={season_id}&matchDay={md}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
    return data.get("data", {}).get("results", [])

def get_current_season_smart():
    """Get current season, falling back to cached if API fails."""
    try:
        return get_current_season()
    except:
        return {"season_id": "", "match_day": None, "status": "ERROR"}

def check_results_with_fallback(s_id, md, current_sid):
    """Check results for a season+MD, with fallback to current season if stale ID.
    Returns (results_list, effective_season_id_used)."""
    # Primary: check the recorded season_id
    results = check_results_for_md(s_id, md)
    effective_sid = s_id
    
    # If no results found AND the season_id is stale (not current), 
    # fall back to current season's results for same MD
    if not results and s_id != current_sid and current_sid:
        fallback_results = check_results_for_md(current_sid, md)
        if fallback_results:
            results = fallback_results
            effective_sid = current_sid
    
    return results, effective_sid

def main():
    ledger = {"predictions": [], "settled": []}
    if os.path.exists(LEDGER_PATH):
        try:
            with open(LEDGER_PATH) as f:
                ledger = json.load(f)
        except:
            pass
    
    accuracy = {"seasons": {}, "overall": {"predicted": 0, "correct": 0, "accuracy": 0}}
    if os.path.exists(ACCURACY_PATH):
        try:
            with open(ACCURACY_PATH) as f:
                accuracy = json.load(f)
        except:
            pass
    
    season = get_current_season_smart()
    sid = season['season_id']
    current_md = season.get('match_day')
    
    if not sid or current_md is None:
        print("[SILENT]")
        return
    
    # Group pending predictions by season_id
    pending = [p for p in ledger.get("predictions", []) if not p.get("settled")]
    if not pending:
        print("[SILENT]")
        with open(LEDGER_PATH, 'w') as f:
            json.dump(ledger, f, indent=2)
        with open(ACCURACY_PATH, 'w') as f:
            json.dump(accuracy, f, indent=2)
        return
    
    # Group by season for efficient API calls
    by_season = defaultdict(list)
    for p in pending:
        by_season[p.get('season_id', sid)].append(p)
    
    settled_this_run = []
    
    for s_id, s_pending in by_season.items():
        # Get all available results for this season
        season_current = s_id == sid  # Is this the current live season?
        checked_mds = set()
        for pred in s_pending:
            md = pred.get('match_day')
            if md is None or md in checked_mds:
                continue
            
            # Only skip current/live MDs if this is the current season
            if season_current and md >= current_md:
                continue
            
            # Check results with automatic fallback for stale season IDs
            results, effective_sid = check_results_with_fallback(s_id, md, sid)
            
            # If results found via fallback, update prediction's season_id
            if not results:
                continue
            if effective_sid != s_id:
                # Found matches in current season — update the prediction's season_id
                for p in s_pending:
                    p['season_id'] = effective_sid
                    p['season_name'] = season.get('season_name', p.get('season_name', ''))
            
            checked_mds.add(md)
            
            for r in results:
                for pred in s_pending:
                    if pred.get('settled'):
                        continue
                    if r.get('homeTeam') == pred['home'] and r.get('awayTeam') == pred['away']:
                        ft = r.get('fullTime')
                        actual_outcome = outcome_from_ft(ft)
                        if actual_outcome is None:
                            continue
                        
                        correct = pred['prediction'] == actual_outcome
                        pred['settled'] = True
                        pred['actual_outcome'] = actual_outcome
                        pred['full_time'] = ft
                        pred['correct'] = correct
                        pred['settled_at'] = datetime.now().isoformat()
                        pred['settled_by'] = NAME
                        
                        sn = pred.get('season_name', s_id)
                        ss = accuracy.setdefault("seasons", {}).setdefault(sn, {"predicted": 0, "correct": 0, "accuracy": 0})
                        ss["predicted"] += 1
                        if correct:
                            ss["correct"] += 1
                        ss["accuracy"] = round(ss["correct"] / ss["predicted"] * 100, 1) if ss["predicted"] else 0
                        
                        accuracy["overall"]["predicted"] += 1
                        if correct:
                            accuracy["overall"]["correct"] += 1
                        accuracy["overall"]["accuracy"] = round(accuracy["overall"]["correct"] / accuracy["overall"]["predicted"] * 100, 1) if accuracy["overall"]["predicted"] else 0
                        
                        settled_this_run.append(pred)
                        break
    
    if not settled_this_run:
        with open(LEDGER_PATH, 'w') as f:
            json.dump(ledger, f, indent=2)
        with open(ACCURACY_PATH, 'w') as f:
            json.dump(accuracy, f, indent=2)
        print("[SILENT]")
        return
    
    ledger["settled"].extend(settled_this_run)
    with open(LEDGER_PATH, 'w') as f:
        json.dump(ledger, f, indent=2)
    with open(ACCURACY_PATH, 'w') as f:
        json.dump(accuracy, f, indent=2)
    
    # ─── VERITY'S REPORT ───
    wins = sum(1 for s in settled_this_run if s.get('correct'))
    losses = sum(1 for s in settled_this_run if not s.get('correct'))
    total = wins + losses
    
    output = []
    output.append(f"{SIGIL} **{NAME} — Settlement Report**")
    output.append(f"*{MOTTO}*")
    output.append("")
    
    # Group by MD for display
    by_md = defaultdict(list)
    for s in settled_this_run:
        by_md[s.get('match_day', 0)].append(s)
    
    for md in sorted(by_md.keys()):
        md_settled = by_md[md]
        md_wins = sum(1 for s in md_settled if s.get('correct'))
        md_acc = f"{md_wins}/{len(md_settled)} ({md_wins/len(md_settled)*100:.0f}%)"
        output.append(f"📊 **MD {md}:** {md_acc}")
        for s in md_settled:
            icon = "✅" if s.get('correct') else "❌"
            output.append(f"{icon} {s['home']} {s.get('full_time','?-?')} {s['away']} (pred: {s['prediction']}, actual: {s.get('actual_outcome','?')})")
        output.append("")
    
    overall = accuracy.get("overall", {})
    output.append(f"🏆 **Running Accuracy:** {overall.get('accuracy', 0)}% ({overall.get('correct', 0)}/{overall.get('predicted', 0)})")
    
    print("\n".join(output))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[SILENT]")
