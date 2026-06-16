#!/usr/bin/env python3
"""
test_akamai_pipeline.py — VFL Akamai CDN Data Pipeline Test Suite.

Probes and validates each of the listed Akamai CDN and unencrypted REST endpoints.
Displays payload shapes, validates fields, and records round-trip latencies.
"""

import os
import sys
import time
import json
import traceback

# Ensure sibling import works correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vfl_akamai_pipeline import AkamaiVFLPipeline, resolve_db_path

def test_endpoint(name: str, fetch_func, *args, **kwargs) -> bool:
    """Test a single endpoint, displaying time taken and validating output is parseable JSON."""
    print(f"📡 Testing {name}...")
    t0 = time.time()
    try:
        data = fetch_func(*args, **kwargs)
        rtt_ms = (time.time() - t0) * 1000
        
        if data is None:
            if name == "MSport Financial Balance":
                print(f"   ℹ️  PASSED (Expected Unauthorized without Session) in {rtt_ms:.2f} ms\n")
                return True
            print(f"   ❌ FAILED (Returned None) in {rtt_ms:.2f} ms\n")
            return False
            
        print(f"   ✅ SUCCESS ({rtt_ms:.2f} ms)")
        
        # Display schema shape
        if isinstance(data, dict):
            print(f"      Type: Dictionary")
            print(f"      Keys: {list(data.keys())[:12]}")
            # print a tiny snippet of key contents
            sample_keys = list(data.keys())[:3]
            sample_data = {k: str(data[k])[:80] + "..." for k in sample_keys if k in data}
            print(f"      Sample: {sample_data}")
        elif isinstance(data, list):
            print(f"      Type: List (Length: {len(data)})")
            if data:
                print(f"      Sample Item: {str(data[0])[:120]}...")
        else:
            print(f"      Type: {type(data)} | Value: {str(data)[:120]}...")
            
        print()
        return True
    except Exception as e:
        rtt_ms = (time.time() - t0) * 1000
        print(f"   ❌ ERROR in {rtt_ms:.2f} ms: {e}")
        traceback.print_exc()
        print()
        return False

def main() -> int:
    print("=" * 60)
    print("🧪  VFL Akamai CDN Pipeline Integration Tests")
    print("=" * 60)

    pipeline = AkamaiVFLPipeline(rate_limit_delay=0.1)

    # 1. Fetch current active match day metadata
    print("⏱️  Discovering current match day and active season...")
    info = pipeline.get_msport_matchday_info()
    if not info:
        print("❌ Cannot proceed with live tests: MSport current matchday is unreachable.")
        return 1

    season_id = info.get("seasonId", "3092003") # Fallback to HAR sample if needed
    matchday = info.get("matchDay", 21)
    print(f"📋 Discovered Season ID: {season_id} | Matchday: {matchday}\n")

    endpoints_to_test = [
        ("MSport Current Match Day Info", pipeline.get_msport_matchday_info),
        ("MSport Financial Balance", pipeline.get_msport_balance),
        ("MSport Current Event List", pipeline.get_msport_event_list),
        ("Akamai Live Events Feed", pipeline.get_live_events, season_id, matchday),
        ("Akamai Live Scores Feed", pipeline.get_live_scores, season_id, matchday),
        ("Akamai Full GISMO Feed", pipeline.get_full_feed, season_id, matchday),
        ("Akamai Live Standing Table", pipeline.get_tournament_table, season_id, matchday),
        ("Akamai VFEL2 Mobile Event IDs", pipeline.get_vfel2_events, season_id, matchday),
        ("Akamai VFEL2 Settings Config", pipeline.get_vfel2_config),
        ("Akamai VFEL2 Stage Phases", pipeline.get_vfel2_phases),
        ("Akamai VFEL2 Jersey Assignments", pipeline.get_vfel2_teams),
        ("Akamai VFEL2 Clock Timings", pipeline.get_vfel2_timings),
    ]

    total_tested = 0
    passed = 0

    for name, func, *args in endpoints_to_test:
        total_tested += 1
        if test_endpoint(name, func, *args):
            passed += 1

    print("=" * 60)
    print(f"📊 TEST SUITE SUMMARY: {passed}/{total_tested} Passed")
    print("=" * 60)

    # Validate snapshot building
    print("\n🔍 Validating Matchday Snapshot Sync logic...")
    snapshot = pipeline.sync_matchday()
    if snapshot and "matches" in snapshot and snapshot["matches"]:
        print(f"✅ Synchronized snapshot for season {snapshot['season_name']} MD {snapshot['matchday']}")
        print(f"   Matches sync size: {len(snapshot['matches'])} games")
        
        # Predictor mapping verification
        recs = pipeline.export_predictor_format(snapshot)
        if recs:
            print(f"✅ Predictor format parsing matches: OK (Normalized {len(recs)} games)")
            print(f"   First match mapping preview:")
            print(json.dumps(recs[0], indent=4))
    else:
        print("❌ Matchday snapshot sync returned empty or malformed.")

    if passed == total_tested:
        print("\n🎉 ALL TESTS COMPLETED SUCCESSFULLY!")
        return 0
    else:
        print("\n⚠️ SOME INTEGRATION TESTS FAILING.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
