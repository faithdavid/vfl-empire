#!/usr/bin/env python3
"""
Account Monitor for VFL AutoBet Placer

Purpose: Continuously observe the MSport account via the same Playwright CDP session
used by the AutoBet Placer. Detects problems in real time so we can stop immediately
and lose no (or minimal) money.

Monitors:
- Current balance (unexpected drops)
- Current bet slip contents (unexpected bets being added)
- Recent bet confirmations / success modals
- Specifically flags any activity involving "Aston Villa" + Over markets (known bad pattern)

On detection of bad state:
- Creates pause_betting.flag immediately
- Logs detailed alert
- Can be extended to send notifications via Hermes

Usage:
  python account_monitor.py --loop          # Continuous monitoring
  python account_monitor.py --once          # Single snapshot check
  python account_monitor.py --check-aston   # Focused check for Aston Villa activity
"""

import time
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [MONITOR] %(levelname)s - %(message)s'
)
log = logging.getLogger("AccountMonitor")

CDP_URL = "http://localhost:9222"
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
PAUSE_FLAG = BASE_DIR / "signals" / "pause_betting.flag"
MONITOR_LOG = BASE_DIR / "signals" / "account_monitor.log"

def connect_to_browser():
    """Connect to the existing Chrome session via CDP (same as the placer)."""
    p = sync_playwright().start()
    try:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]
        page = context.pages[0]
        log.info("Successfully connected to browser via CDP")
        return p, browser, page
    except Exception as e:
        log.error(f"Failed to connect to browser CDP: {e}")
        p.stop()
        raise

def get_balance_safe(page) -> str:
    """Read current balance with error handling."""
    try:
        bal_text = page.locator('[class*="balance"], .header-balance, .wallet-balance').first.inner_text(timeout=8000)
        return bal_text.strip()
    except Exception as e:
        log.warning(f"Could not read balance: {e}")
        return "UNKNOWN"

def inspect_betslip(page) -> dict:
    """Inspect current bet slip state."""
    try:
        slip_items = page.locator('.bet-slip-item, [class*="bet-slip"] .item, .m-bet-item').all()
        count = len(slip_items)
        
        contents = []
        for item in slip_items[:5]:  # Limit to avoid huge logs
            try:
                text = item.inner_text(timeout=1000)
                contents.append(text[:100])
            except:
                pass
        
        return {
            "item_count": count,
            "contents_preview": contents,
            "is_empty": count == 0
        }
    except Exception as e:
        return {"error": str(e), "item_count": -1}

def detect_recent_success_modal(page) -> bool:
    """Check if a bet success modal appeared recently."""
    try:
        success = page.locator('text="Bet Successful!"').first
        return success.is_visible(timeout=2000)
    except:
        return False

def check_for_bad_patterns(page, bad_teams=None) -> list:
    """
    Scan the bet slip and recent activity for known bad patterns.
    Focused on Aston Villa + Over markets (user has high loss rate on these).
    Only triggers on actual selected bets, not just market visibility on the page.
    """
    if bad_teams is None:
        bad_teams = {"Aston Villa"}

    problems = []
    try:
        # Only check the actual bet slip contents (more precise)
        slip = inspect_betslip(page)
        if slip.get("item_count", 0) > 0:
            for preview in slip.get("contents_preview", []):
                preview_lower = preview.lower()
                for team in bad_teams:
                    if team.lower() in preview_lower and "over" in preview_lower:
                        problems.append(f"Betslip contains bad pattern: {team} + Over")
        
        # Also check if a bad bet was just successfully placed
        if detect_recent_success_modal(page):
            # Quick body check only when a bet just succeeded
            body_text = page.locator('body').inner_text(timeout=3000).lower()
            for team in bad_teams:
                if team.lower() in body_text and "over" in body_text:
                    problems.append(f"Recent bet success + {team} + Over pattern detected on page")
    except Exception as e:
        problems.append(f"Pattern check error: {e}")
    
    return problems

def create_pause_flag(reason: str):
    """Immediately stop all betting by creating the pause flag."""
    try:
        PAUSE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        PAUSE_FLAG.write_text(f"Paused by AccountMonitor at {datetime.now(timezone.utc).isoformat()}\nReason: {reason}\n")
        log.critical(f"PAUSE FLAG CREATED: {reason}")
        return True
    except Exception as e:
        log.error(f"Failed to create pause flag: {e}")
        return False

def monitor_loop(duration_seconds: int = 3600, check_interval: int = 15):
    """Main monitoring loop."""
    log.info("=== Starting Account Monitor (Safety Mode) ===")
    log.info(f"Will monitor for up to {duration_seconds}s, checking every {check_interval}s")
    
    p, browser, page = connect_to_browser()
    
    start_balance = get_balance_safe(page)
    log.info(f"Starting balance: {start_balance}")
    
    start_time = time.time()
    last_balance = start_balance
    
    try:
        while time.time() - start_time < duration_seconds:
            current_balance = get_balance_safe(page)
            slip_state = inspect_betslip(page)
            bad_patterns = check_for_bad_patterns(page)
            
            # Log snapshot
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "balance": current_balance,
                "betslip_items": slip_state.get("item_count", -1),
                "bad_patterns_detected": len(bad_patterns)
            }
            log.info(f"Monitor snapshot: {json.dumps(snapshot)}")
            
            # === SAFETY RULES ===
            problems_found = []
            
            # 1. Unexpected balance drop
            try:
                prev = float(''.join(filter(str.isdigit, last_balance)) or 0)
                curr = float(''.join(filter(str.isdigit, current_balance)) or 0)
                if curr < prev - 5:  # More than 5 Naira drop without explanation
                    problems_found.append(f"Unexpected balance drop: {last_balance} → {current_balance}")
            except:
                pass
            
            # 2. Betslip has unexpected items (possible duplicate or rogue bet)
            if slip_state.get("item_count", 0) > 0:
                problems_found.append(f"Betslip not empty ({slip_state['item_count']} items)")
            
            # 3. Bad patterns (especially Aston Villa + Over)
            problems_found.extend(bad_patterns)
            
            if problems_found:
                reason = " | ".join(problems_found)
                log.critical(f"PROBLEM DETECTED: {reason}")
                create_pause_flag(reason)
                
                # Write detailed log
                with open(MONITOR_LOG, "a") as f:
                    f.write(f"\n{datetime.now(timezone.utc).isoformat()} - ALERT\n")
                    f.write(f"Reason: {reason}\n")
                    f.write(f"Snapshot: {json.dumps(snapshot, indent=2)}\n")
                
                log.info("Monitoring paused due to detected problem. Pause flag created.")
                break
            
            last_balance = current_balance
            
            # Check for recent success modal (bet just placed)
            if detect_recent_success_modal(page):
                log.warning("Recent bet success modal detected. Recording state for review.")
                # In future we could correlate with expected placements from orchestrator
            
            time.sleep(check_interval)
    
    except KeyboardInterrupt:
        log.info("Monitoring stopped by user (KeyboardInterrupt)")
    except Exception as e:
        log.error(f"Monitoring loop crashed: {e}")
        create_pause_flag(f"Monitor crash: {str(e)}")
    finally:
        try:
            browser.close()
            p.stop()
        except:
            pass
        log.info("Account Monitor session ended.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VFL Account Monitor")
    parser.add_argument("--loop", action="store_true", help="Run continuous monitoring")
    parser.add_argument("--once", action="store_true", help="Single check and exit")
    parser.add_argument("--duration", type=int, default=3600, help="Max seconds to run in loop mode")
    parser.add_argument("--interval", type=int, default=15, help="Seconds between checks")
    
    args = parser.parse_args()
    
    if args.once:
        p, browser, page = connect_to_browser()
        print("Balance:", get_balance_safe(page))
        print("Betslip:", inspect_betslip(page))
        print("Bad patterns:", check_for_bad_patterns(page))
        browser.close()
        p.stop()
    elif args.loop:
        monitor_loop(duration_seconds=args.duration, check_interval=args.interval)
    else:
        print("Use --loop or --once")
        parser.print_help()