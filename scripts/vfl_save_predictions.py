#!/usr/bin/env python3
"""
VFL Prediction Saver — appends predictions to:
  1. vfl_ledger.json (canonical ledger for settlement)
  2. predictions.jsonl (append-only JSON Lines log for local reference)

Usage:
  python3 vfl_save_predictions.py '{"season_id":"...", ...}'
  python3 vfl_save_predictions.py --file /path/to/prediction.json
  echo '{"season_id":"...", ...}' | python3 vfl_save_predictions.py
"""
import json, sys, os
from datetime import datetime, timezone

LEDGER_PATH = os.path.expanduser("~/.hermes/cron/state/vfl_ledger.json")
JSONL_PATH = os.path.expanduser("~/Documents/Projects/vfl-data/predictions/predictions.jsonl")

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return None

def save_ledger_entry(entry):
    """Append one prediction entry to the ledger."""
    ledger = load_json(LEDGER_PATH) or {"predictions": []}
    ledger["predictions"].append(entry)
    with open(LEDGER_PATH, "w") as f:
        json.dump(ledger, f, indent=2)

def append_jsonl(entry):
    """Append one JSON line to the predictions log."""
    # Add a timestamp for the log
    log_entry = dict(entry)
    log_entry["_logged_at"] = datetime.now(timezone.utc).isoformat()
    with open(JSONL_PATH, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

def main():
    # Read prediction from stdin, --file, or argv
    raw = None
    
    # Check for --file argument
    if "--file" in sys.argv:
        idx = sys.argv.index("--file")
        if idx + 1 < len(sys.argv):
            filepath = sys.argv[idx + 1]
            with open(filepath) as f:
                raw = f.read()
    elif not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        raw = sys.argv[1]

    if not raw:
        print("[SILENT] — No prediction data to save")
        return

    try:
        entry = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON: {e}")
        return

    # Validate required fields
    required = ["season_id", "match_day", "home", "away", "prediction", "confidence"]
    missing = [f for f in required if f not in entry]
    if missing:
        print(f"[ERROR] Missing fields: {missing}")
        return

    # Save to ledger
    save_ledger_entry(entry)

    # Append to JSON Lines log
    append_jsonl(entry)

    print(f"[SAVED] {entry['home']} vs {entry['away']} → {entry['prediction']} ({entry['confidence']}%)")

if __name__ == "__main__":
    main()
