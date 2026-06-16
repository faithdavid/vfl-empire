#!/usr/bin/env python3
"""Backup ALL archived public threads from Discord forum vfl-season-ingester."""

import os, json, time, requests
from datetime import datetime, timezone

ENV_PATH = os.path.expanduser("~/.hermes/.env")
CHANNEL_ID = "1507068774552043623"  # vfl-season-ingester
GUILD_ID = "1506726428161605642"
OUTPUT_PATH = "/home/ubuntu/faith-workspace/vfl-empire/backups/discord/vfl-season-ingester-backup.json"
DELAY = 0.5

def read_token():
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise ValueError("DISCORD_BOT_TOKEN not found")

TOKEN = read_token()
HEADERS = {"Authorization": f"Bot {TOKEN}"}
API = "https://discord.com/api/v10"

def api_get(url, params=None):
    while True:
        time.sleep(DELAY)
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            retry_after = r.json().get("retry_after", 1.0)
            print(f"  429 — retrying after {retry_after}s")
            time.sleep(retry_after)
        else:
            print(f"  ERROR {r.status_code}: {r.text[:200]}")
            r.raise_for_status()

def fetch_archived_threads():
    """Fetch ALL archived public threads using cursor-based pagination."""
    all_threads = []
    url = f"{API}/channels/{CHANNEL_ID}/threads/archived/public"
    params = {"limit": 100}

    while url:
        print(f"  Fetching archived threads page... ({len(all_threads)} so far)")
        data = api_get(url, params)
        threads = data.get("threads", [])
        all_threads.extend(threads)

        if data.get("has_more") and threads:
            last = threads[-1]["thread_metadata"]["archive_timestamp"]
            params = {"limit": 100, "before": last}
            url = f"{API}/channels/{CHANNEL_ID}/threads/archived/public"
        else:
            url = None

    return all_threads

def fetch_messages(thread_id):
    """Fetch ALL messages in a thread using before-based pagination."""
    all_msgs = []
    url = f"{API}/channels/{thread_id}/messages"
    params = {"limit": 100}

    while url:
        batch = api_get(url, params)
        if not batch:
            break
        all_msgs.extend(batch)
        if len(batch) == 100:
            params = {"limit": 100, "before": batch[-1]["id"]}
            url = f"{API}/channels/{thread_id}/messages"
        else:
            url = None

    return all_msgs

def main():
    print("=== Discord Forum Backup: vfl-season-ingester ===")
    print(f"Channel ID: {CHANNEL_ID}")
    print()

    # Step 1: Fetch all archived threads
    print("Step 1: Fetching all archived public threads...")
    threads = fetch_archived_threads()
    print(f"  Found {len(threads)} archived threads.\n")

    # Build output
    backup = {
        "channel_id": CHANNEL_ID,
        "channel_name": "vfl-season-ingester",
        "backup_timestamp": datetime.now(timezone.utc).isoformat(),
        "thread_count": len(threads),
        "threads": [],
    }

    # Step 2: Fetch messages for each thread
    print("Step 2: Fetching messages for each thread...")
    for idx, t in enumerate(threads, 1):
        tid = t["id"]
        tname = t.get("name", "Unknown")
        created = t.get("thread_metadata", {}).get("create_timestamp", t.get("timestamp", ""))

        print(f"  [{idx}/{len(threads)}] '{tname}' ({tid})...", end=" ", flush=True)
        raw = fetch_messages(tid)

        # Reverse to chronological order (oldest first)
        msgs = []
        for m in reversed(raw):
            msgs.append({
                "message_id": m["id"],
                "author_id": m["author"]["id"],
                "author_name": m["author"]["username"],
                "timestamp": m.get("timestamp", ""),
                "content": m.get("content", ""),
            })

        backup["threads"].append({
            "thread_id": tid,
            "thread_name": tname,
            "created_at": created,
            "message_count": len(msgs),
            "messages": msgs,
        })
        print(f"{len(msgs)} messages")

    # Step 3: Write output
    print(f"\nStep 3: Writing backup to {OUTPUT_PATH}...")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2, ensure_ascii=False)

    total_msgs = sum(t["message_count"] for t in backup["threads"])
    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"\n=== Backup Complete ===")
    print(f"  Threads:  {backup['thread_count']}")
    print(f"  Messages: {total_msgs}")
    print(f"  File size: {size_mb:.2f} MB")
    print(f"  Output:   {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
