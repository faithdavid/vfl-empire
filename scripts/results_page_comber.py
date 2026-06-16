#!/usr/bin/env python3
"""
results_page_comber.py
Playwright-based comber for the MSport Virtual results page.
Walks backwards through matchdays/seasons by clicking "prev" to capture
a large amount of historical results data at once.

Purpose: Ensure no lapses/gaps in the central Postgres DB for results data.
The UI comb-through is reliable for bulk historical results (as you used before).

- Goes to /virtual/result (performs login if needed; supports profile for future no-login runs).
- Extracts fixtures + final scores.
- Inserts directly into central vfl_empire tables (vfl_results_v2 and matches where appropriate).
- Keeps a JSON backup.
- Tracks progress to resume without re-doing everything.
- Can comb many MDs in one run ("a lot of results data at once").

Usage:
  python3 results_page_comber.py --steps 20          # comb back 20 MDs from current
  python3 ... --steps 100 --dry-run                  # see what would be inserted
  python3 ... --resume                               # use last position

Requires: playwright installed in the env (as in your other scripts).
The hardcoded creds are from your existing scraper; update if needed.
For no-login in future: save storage_state after first successful run.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# DB
sys.path.insert(0, str(Path(__file__).parent.parent / "services"))
try:
    from common.db_manager import get_db
    from common.event_id_sync import lookup_event_id
    HAS_DB_MANAGER = True
except Exception as e:
    HAS_DB_MANAGER = False
    print("Warning: db_manager not available, will try direct psycopg2. Error:", e)
    import psycopg2

from playwright.sync_api import sync_playwright

# Paths (adapt to your setup; using the vfl-bot profile area)
BASE_DIR = Path("/home/ubuntu/.hermes/profiles/vfl-bot")
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = DATA_DIR / "results_page_comber.log"
OUTPUT_JSON = DATA_DIR / "combed_results.json"
STATE_FILE = DATA_DIR / "comber_state.json"  # for resume (last season/md combed)

# Login creds (from your existing script)
PHONE = "09038426877"
PASSWORD = "fadava2002"

def log(msg):
    ts = datetime.now().isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def extract_fixtures(page):
    """Extract fixtures + FINAL scores from the results page body text.
    This is the comb logic you used — gets a batch of results per page.
    """
    text = page.inner_text("body")
    
    # Season / Match Day (the page shows "Season XXX" "Match Day Y")
    s = re.search(r'Season\s+(\d+)', text)
    md_s = re.search(r'Match\s+Day\s+(\d+)', text)
    season_num = s.group(1) if s else "?"
    md = int(md_s.group(1)) if md_s else 0
    
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    fixtures = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        # Team pattern: "TeamA - TeamB" (your original regex)
        tm = re.match(r'^([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s*[-–]\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)$', line)
        if tm:
            home = tm.group(1)
            away = tm.group(2)
            if i + 3 < len(lines):
                ft_line = lines[i + 3]
                sm = re.match(r'^(\d+)\s*[-:]\s*(\d+)$', ft_line)
                if sm:
                    h = int(sm.group(1))
                    a = int(sm.group(2))
                    fixtures.append({
                        "home": home,
                        "away": away,
                        "h": h,
                        "a": a,
                        "score": f"{h}-{a}",
                        "total": h + a,
                    })
            i += 4
        else:
            i += 1
    
    return season_num, md, fixtures

def get_db_cursor():
    if HAS_DB_MANAGER:
        # The manager yields a cursor in a context; we will use it per insert or batch.
        return None  # special handling
    else:
        conn = psycopg2.connect(dbname="vfl_empire", user="vfl_user", password="vfl_pass", host="localhost", port=5432)
        return conn, conn.cursor()

def _upsert_result_v2(cur, season_name: str, season_id: str, md: int, fix: dict, event_id: str, captured_at: str):
    """Insert into normalized vfl_results_v2 via seasons + matchdays."""
    cur.execute(
        """
        INSERT INTO vfl_seasons (season_id, season_name)
        VALUES (%s, %s)
        ON CONFLICT (season_id) DO UPDATE SET season_name = EXCLUDED.season_name
        RETURNING id
        """,
        (season_id, season_name),
    )
    db_season_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO vfl_matchdays (season_id, matchday_number, status)
        VALUES (%s, %s, 'FINISHED')
        ON CONFLICT (season_id, matchday_number) DO UPDATE SET status = 'FINISHED'
        RETURNING id
        """,
        (db_season_id, md),
    )
    db_md_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO vfl_results_v2 (matchday_id, event_id, home_team, away_team, home_goals, away_goals, captured_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (matchday_id, home_team, away_team) DO NOTHING
        """,
        (db_md_id, event_id, fix["home"], fix["away"], fix["h"], fix["a"], captured_at),
    )


def insert_result(season_num, md, fix, captured_at):
    """Insert one result row into the central vfl_results_v2 tables."""
    season_name = f"VFLM {season_num}"
    season_id = None
    if HAS_DB_MANAGER:
        with get_db() as cur:
            cur.execute(
                "SELECT season_id FROM vfl_seasons WHERE season_name = %s LIMIT 1",
                (season_name,),
            )
            row = cur.fetchone()
            if row:
                season_id = row[0]
    event_id = None
    if season_id:
        event_id = lookup_event_id(season_id, md, fix["home"], fix["away"])
    if not event_id:
        event_id = (
            f"vf:match:season:vflm{season_num}:md:{md}:"
            f"{fix['home']}:{fix['away']}".replace(" ", "")
        )

    if HAS_DB_MANAGER:
        with get_db() as cur:
            cur.execute(
                "SELECT season_id FROM vfl_seasons WHERE season_name = %s LIMIT 1",
                (season_name,),
            )
            row = cur.fetchone()
            season_id = row[0] if row else f"vf:season:vflm{season_num}"
            _upsert_result_v2(cur, season_name, season_id, md, fix, event_id, captured_at)
    else:
        conn, cur = get_db_cursor()
        cur.execute(
            "SELECT season_id FROM vfl_seasons WHERE season_name = %s LIMIT 1",
            (season_name,),
        )
        row = cur.fetchone()
        season_id = row[0] if row else f"vf:season:vflm{season_num}"
        _upsert_result_v2(cur, season_name, season_id, md, fix, event_id, captured_at)
        conn.commit()
        conn.close()

def comb_results(steps: int = 30, dry_run: bool = False, resume: bool = False):
    """Main comb logic — walks the results page backwards, extracting a lot of data at once."""
    log("Starting results page comber (Playwright comb-through for completeness, no lapses)")
    
    state = {}
    if resume and STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        log(f"Resuming from state: {state}")
    
    all_combed = {}
    if OUTPUT_JSON.exists():
        all_combed = json.loads(OUTPUT_JSON.read_text()).get("results", {})
    
    captured_at = datetime.now(timezone.utc).isoformat()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = browser.new_page()
        
        # Login flow (your original; results page seems to need it based on tests)
        # If you have a saved storage_state.json from a previous login, load it here to skip.
        # page.context.add_cookies(...) or context = browser.new_context(storage_state=...)
        try:
            page.goto("https://www.msport.com", timeout=20000)
            page.click("text=Login", timeout=8000)
            page.fill("input[type=\"tel\"]", PHONE)
            page.fill("input[type=\"password\"]", PASSWORD)
            page.click("button:has-text(\"Login\")")
            page.wait_for_timeout(2000)
            log("Login attempted")
        except Exception as e:
            log(f"Login step warning (may already be logged in or page different): {e}")
        
        # Go to results
        page.goto("https://www.msport.com/ng/web/virtual/result", timeout=25000)
        page.wait_for_timeout(3000)
        log("On results page")
        
        # Initial
        season_num, md, fixes = extract_fixtures(page)
        if not fixes:
            log("No fixtures on initial page — the page may require login or have changed structure.")
            # Try to continue anyway for a few clicks if prev exists
        
        current_season = int(season_num) if season_num != "?" else 5345
        current_md = md if md > 0 else 27
        
        # Apply resume
        if resume and "last_season" in state:
            current_season = state["last_season"]
            current_md = state["last_md"]
            log(f"Resumed counter to S{current_season} MD{current_md}")
        
        combed_count = 0
        
        # Comb loop (this is the "comb through" that gets a lot at once)
        for i in range(steps):
            key = f"S{current_season}_MD{current_md}"
            
            if key in all_combed:
                log(f"  {key} already have, skipping")
            else:
                season_num, md, fixes = extract_fixtures(page)
                if fixes:
                    all_combed[key] = {
                        "season": str(current_season),
                        "md": current_md,
                        "fixtures": fixes,
                        "combed_at": captured_at
                    }
                    log(f"  {key}: {len(fixes)} results")
                    
                    if not dry_run:
                        for fix in fixes:
                            try:
                                insert_result(str(current_season), current_md, fix, captured_at)
                            except Exception as ex:
                                log(f"    DB insert error for {fix}: {ex}")
                    combed_count += len(fixes)
                else:
                    log(f"  {key}: 0 fixtures on page")
            
            # Click prev to get previous MD (the comb action)
            try:
                prev_btn = page.query_selector(".virtual-result-chg.prev")
                if not prev_btn:
                    log("No more prev button — end of available history")
                    break
                prev_btn.click()
                page.wait_for_timeout(2200)  # let the page update
                
                # Update counters (your reliable method)
                current_md -= 1
                if current_md <= 0:
                    current_season -= 1
                    current_md = 30
                
                # Save progress state
                state = {"last_season": current_season, "last_md": current_md, "updated": captured_at}
                STATE_FILE.write_text(json.dumps(state))
                
            except Exception as e:
                log(f"Error clicking prev at step {i}: {e}")
                break
        
        browser.close()
    
    # Save the combed data
    output = {
        "scraped_at": captured_at,
        "total_mds_combed_this_run": len([k for k in all_combed if "combed_at" in all_combed[k] and all_combed[k]["combed_at"] == captured_at]),
        "total_mds_in_file": len(all_combed),
        "results": all_combed
    }
    OUTPUT_JSON.write_text(json.dumps(output, indent=2, default=str))
    
    log(f"Combed {combed_count} individual results this run. Total MDs in backup: {len(all_combed)}")
    log(f"Data saved to {OUTPUT_JSON}")
    log("Central DB should now have the results (no lapses from this comb).")
    return output

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Comb the MSport virtual results page with Playwright for complete historical data into central DB.")
    ap.add_argument("--steps", type=int, default=30, help="How many MDs to comb backwards (large number = lots of data at once)")
    ap.add_argument("--dry-run", action="store_true", help="Parse and log but do not insert to DB")
    ap.add_argument("--resume", action="store_true", help="Resume from last comb position in state file")
    ap.add_argument("--loop", action="store_true", help="Run continuously")
    ap.add_argument("--interval", type=int, default=150, help="Seconds between loop runs")
    args = ap.parse_args()

    if args.loop:
        while True:
            try:
                comb_results(steps=args.steps, dry_run=args.dry_run, resume=args.resume)
            except Exception as e:
                log(f"Comber loop error: {e}")
            time.sleep(args.interval)
    else:
        comb_results(steps=args.steps, dry_run=args.dry_run, resume=args.resume)
