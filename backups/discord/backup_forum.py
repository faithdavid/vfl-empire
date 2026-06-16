#!/usr/bin/env python3
"""
Backup ALL archived thread data from Discord forum vfl-live-predictor.
Channel ID: 1507068780650565815
Guild ID: 1506726428161605642
"""

import os
import re
import json
import time
import requests
from datetime import datetime, timezone

# --- Configuration ---
ENV_PATH = os.path.expanduser("~/.hermes/.env")
CHANNEL_ID = "1507068780650565815"
CHANNEL_NAME = "vfl-live-predictor"
OUTPUT_PATH = "/home/ubuntu/faith-workspace/vfl-empire/backups/discord/vfl-live-predictor-backup.json"
DELAY = 0.5  # seconds between requests

# --- Read token from .env ---
def read_token_from_env(env_path):
    """Read DISCORD_BOT_TOKEN from .env file."""
    if not os.path.exists(env_path):
        print(f"ERROR: .env file not found at {env_path}")
        return None
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                # Handle quoted and unquoted values
                value = line.split("=", 1)[1]
                value = value.strip("\"'")
                if value:
                    return value
    print("ERROR: DISCORD_BOT_TOKEN not found in .env")
    return None

# --- Discord API helpers ---
BASE = "https://discord.com/api/v10"
HEADERS = None

def api_get(url, params=None):
    """Make a GET request to Discord API with rate limit handling."""
    global HEADERS
    if HEADERS is None:
        token = read_token_from_env(ENV_PATH)
        if not token:
            raise RuntimeError("Could not read Discord bot token")
        HEADERS = {"Authorization": f"Bot {token}"}
    
    while True:
        resp = requests.get(url, headers=HEADERS, params=params)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 1))
            print(f"  Rate limited! Retrying after {retry_after}s...")
            time.sleep(retry_after + 0.5)
            continue
        resp.raise_for_status()
        return resp.json()

def fetch_archived_threads(channel_id):
    """Fetch ALL archived public threads from a forum channel (paginated)."""
    threads = []
    url = f"{BASE}/channels/{channel_id}/threads/archived/public"
    params = {"limit": 100}
    
    while True:
        print(f"  Fetching archived threads page... (got {len(threads)} so far)")
        data = api_get(url, params=params)
        
        batch = data.get("threads", [])
        threads.extend(batch)
        print(f"  Got {len(batch)} threads on this page")
        
        if data.get("has_more") and data.get("thread_metadata_snapshot"):
            last_thread = batch[-1]
            # Use the archive timestamp for cursor-based pagination
            last_meta = data["thread_metadata_snapshot"][-1] if data.get("thread_metadata_snapshot") else None
            if last_meta:
                params["before"] = last_meta.get("archive_timestamp")
            else:
                params["before"] = last_thread.get("id")
        else:
            break
        
        time.sleep(DELAY)
    
    return threads

def fetch_thread_messages(thread_id):
    """Fetch ALL messages from a thread (paginated with before parameter)."""
    messages = []
    url = f"{BASE}/channels/{thread_id}/messages"
    params = {"limit": 100}
    
    while True:
        print(f"    Fetching messages page... (got {len(messages)} so far)")
        data = api_get(url, params=params)
        
        if not data:
            break
        
        messages.extend(data)
        
        if len(data) < 100:
            break
        
        # Use the oldest message ID as cursor
        params["before"] = data[-1]["id"]
        
        time.sleep(DELAY)
    
    return messages

def format_messages(messages):
    """Convert raw Discord messages to our backup format."""
    result = []
    for msg in messages:
        result.append({
            "message_id": msg["id"],
            "author_id": msg["author"]["id"],
            "author_name": msg["author"]["global_name"] or msg["author"]["username"],
            "timestamp": msg["timestamp"],
            "content": msg.get("content", "")
        })
    return result

def format_thread(thread, messages_formatted):
    """Convert a raw thread to our backup format."""
    return {
        "thread_id": thread["id"],
        "thread_name": thread.get("name", ""),
        "created_at": thread.get("timestamp", thread.get("thread_metadata", {}).get("create_timestamp", "")),
        "message_count": len(messages_formatted),
        "messages": messages_formatted
    }

# --- Main ---
def main():
    print(f"Starting Discord forum backup for channel: {CHANNEL_NAME} ({CHANNEL_ID})")
    print(f"Token from .env: {'Found' if read_token_from_env(ENV_PATH) else 'NOT FOUND'}")
    print()
    
    # Step 1: Fetch all archived threads
    print("Step 1: Fetching archived threads...")
    raw_threads = fetch_archived_threads(CHANNEL_ID)
    print(f"Total archived threads found: {len(raw_threads)}")
    print()
    
    # Step 2: For each thread, fetch all messages
    print("Step 2: Fetching messages for each thread...")
    backup_threads = []
    for i, thread in enumerate(raw_threads, 1):
        thread_id = thread["id"]
        thread_name = thread.get("name", "(no name)")
        print(f"  [{i}/{len(raw_threads)}] Thread: {thread_name} (ID: {thread_id})")
        
        raw_messages = fetch_thread_messages(thread_id)
        formatted_msgs = format_messages(raw_messages)
        backup_threads.append(format_thread(thread, formatted_msgs))
        
        print(f"    Messages: {len(formatted_msgs)}")
        time.sleep(DELAY)
    
    # Step 3: Build final backup
    print()
    print("Step 3: Writing backup file...")
    backup_data = {
        "channel_id": CHANNEL_ID,
        "channel_name": CHANNEL_NAME,
        "backup_timestamp": datetime.now(timezone.utc).isoformat(),
        "thread_count": len(backup_threads),
        "threads": backup_threads
    }
    
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False)
    
    # Stats
    total_messages = sum(t["message_count"] for t in backup_threads)
    print(f"\nDone! Backup saved to: {OUTPUT_PATH}")
    print(f"  Threads: {len(backup_threads)}")
    print(f"  Total messages: {total_messages}")
    print(f"  File size: {os.path.getsize(OUTPUT_PATH)} bytes")

if __name__ == "__main__":
    main()
