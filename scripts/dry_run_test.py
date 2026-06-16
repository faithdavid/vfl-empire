import sys
from pathlib import Path
EMPIRE = Path("/home/ubuntu/faith-workspace/vfl-empire")
sys.path.insert(0, str(EMPIRE / "scripts"))
from msport_api import get_event_list
from vfl_live_predictor import normalize_team
import json
import subprocess

match_days = get_event_list()
if not match_days:
    print("No live games found.")
    sys.exit()

md_live = match_days[0]
target_md = md_live["matchDay"]

legs = []
for ev in md_live["events"][:8]:
    ht = normalize_team(ev["homeTeam"])
    at = normalize_team(ev["awayTeam"])
    legs.append({"home": ht, "away": at, "market": "1"})

payload = {
    "target_md": target_md,
    "stake": 150,
    "legs": legs
}

print(f"Executing DRY RUN parlay on MD {target_md}...")
cmd = ["python3", str(EMPIRE / "scripts" / "browser_bet_placer.py"), "parlay", json.dumps(payload)]
res = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:", res.stdout)
print("STDERR:", res.stderr)
