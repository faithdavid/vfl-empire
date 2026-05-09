#!/usr/bin/env python3
"""
Compact Oracle heartbeat — runs collector, outputs a summary.
The full context JSON is saved to state file for the agent to read.
"""
import subprocess, json, os, sys

collector = os.path.expanduser("~/Documents/Projects/vfl-data/scripts/vfl_oracle_collector.py")
result = subprocess.run(["python3", collector], capture_output=True, text=True, timeout=30)

if result.returncode != 0:
    print("[SILENT]")
    sys.exit(0)

try:
    data = json.loads(result.stdout)
except:
    print("[SILENT]")
    sys.exit(0)

season = data.get("season", {})
completed = data.get("completed_mds", [])
upcoming = data.get("upcoming", [])
table = data.get("table", [])

# Check if we already predicted this MD (season-aware)
state_file = os.path.expanduser("~/.hermes/cron/state/vfl_predictor_state.json")
already_predicted = []
current_season_id = season.get("id", "")
if os.path.exists(state_file):
    try:
        with open(state_file) as f:
            st = json.load(f)
        # Only respect predicted_mds if it's the same season
        if st.get("last_season") == current_season_id:
            already_predicted = st.get("predicted_mds", [])
    except:
        pass

# Find the first unpredicted MD with fixtures (skip current/live MD)
current_md = season.get("current_md", 0)
next_md = None
next_matches = []
for u in upcoming:
    md_num = u["match_day"]
    if md_num in already_predicted:
        continue
    if md_num <= current_md:
        continue  # Skip current/live MDs
    if u["matches"]:
        next_md = md_num
        next_matches = u["matches"]
        break

if next_md is None:
    print("[SILENT] — No new MD to predict")
    sys.exit(0)

# Print compact header for agent context
print(f"🤖 SEASON: {season.get('name')} — MD {next_md} PREDICTIONS NEEDED")
print(f"Current MD: {season.get('current_md')} | Status: {season.get('status')}")
print()

if table:
    print("📊 CURRENT TABLE:")
    for t in table[:8]:
        print(f"  {t['pos']}. {t['team']:20} {t['pts']}pts {t['gp']}gp GD:{t['gd']:+d} Form:{t['form']}")
    print()

print(f"⚽ MD {next_md} FIXTURES:")
for m in next_matches:
    flags = ""
    print(f"  {m['home']:20} vs {m['away']:<20}")
    print(f"    Odds: H:{m['odds']['H']} D:{m['odds']['D']} A:{m['odds']['A']}  [Implied: H:{m['implied_h']}% D:{m['implied_d']}% A:{m['implied_a']}%]")
    print(f"    Tier: {m['tier_matchup']}  Vig: {m['vig']}%")
print()
print("Context file: ~/.hermes/cron/state/vfl_oracle_context.json")
print("Read it for full analysis: constraints, bias distortion, historical fixture data.")
print("Make your predictions. Save to ledger. Output your reasoning.")
