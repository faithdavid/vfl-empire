#!/usr/bin/env python3
"""Replace capped Discord forum channels: create new ones, delete old ones."""

import json, os, time, sys
from urllib.request import Request, urlopen, HTTPError
from urllib.parse import urlencode

ENV_PATH = os.path.expanduser("~/.hermes/.env")
GUILD_ID = "1506726428161605642"

def get_token():
    with open(ENV_PATH) as f:
        for line in f:
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("DISCORD_BOT_TOKEN not found")

TOKEN = get_token()
HEADERS = {
    "Authorization": f"Bot {TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "DiscordBot (https://hermes.agent, 1.0)",
}

def api_call(method, url, body=None, retries=3):
    """Make a Discord API call with retry logic."""
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method, headers=HEADERS)
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            resp_body = e.read().decode()
            if e.code == 429 and attempt < retries - 1:
                retry_after = json.loads(resp_body).get("retry_after", 1)
                print(f"  429 rate limited, waiting {retry_after}s...")
                time.sleep(retry_after + 0.5)
                continue
            print(f"  ERROR {e.code}: {resp_body[:200]}")
            return {"error": e.code, "detail": resp_body[:500]}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            print(f"  EXCEPTION: {e}")
            return {"error": str(e)}

def create_forum(name, topic):
    """Create a new forum channel."""
    url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/channels"
    body = {
        "name": name,
        "type": 15,  # GUILD_FORUM
        "topic": topic,
    }
    print(f"\n--- Creating forum: {name} ---")
    result = api_call("POST", url, body)
    if "error" not in result:
        print(f"  ✅ Created: {name} (ID: {result['id']})")
    else:
        print(f"  ❌ Failed to create {name}: {result}")
    return result

def delete_channel(channel_id, name):
    """Delete a channel."""
    url = f"https://discord.com/api/v10/channels/{channel_id}"
    print(f"\n--- Deleting old channel: {name} ({channel_id}) ---")
    result = api_call("DELETE", url)
    if "error" not in result:
        print(f"  ✅ Deleted: {name} ({channel_id})")
    else:
        print(f"  ❌ Failed to delete {name}: {result}")
    return result

def main():
    print("=" * 60)
    print("PHASE 1: CREATE NEW FORUM CHANNELS")
    print("=" * 60)

    replacements = [
        {
            "old_id": "1507068779450863626",
            "old_name": "vfl-predictions",
            "new_name": "vfl-predictions-2",
            "topic": "VFL predictions pipeline — v2 (replacement for capped forum)"
        },
        {
            "old_id": "1507068774552043623",
            "old_name": "vfl-season-ingester",
            "new_name": "vfl-season-ingester-2",
            "topic": "VFL season data ingestion — v2 (replacement for capped forum)"
        },
        {
            "old_id": "1507068780650565815",
            "old_name": "vfl-live-predictor",
            "new_name": "vfl-live-predictor-2",
            "topic": "Live VFL predictions — v2 (replacement for capped forum)"
        },
    ]

    mapping = []  # (old_id, old_name, new_id, new_name, success)

    for r in replacements:
        result = create_forum(r["new_name"], r["topic"])
        if "error" not in result:
            mapping.append((r["old_id"], r["old_name"], result["id"], r["new_name"], True))
        else:
            mapping.append((r["old_id"], r["old_name"], None, r["new_name"], False))

    print("\n" + "=" * 60)
    print("CHANNEL MAPPING")
    print("=" * 60)
    for old_id, old_name, new_id, new_name, success in mapping:
        status = "✅" if success else "❌"
        new_info = f"{new_name} ({new_id})" if new_id else "FAILED"
        print(f"  {status} {old_name} ({old_id}) -> {new_info}")

    print("\n" + "=" * 60)
    print("PHASE 2: DELETE OLD CAPPED FORUMS (only if replacement succeeded)")
    print("=" * 60)

    for old_id, old_name, new_id, new_name, success in mapping:
        if success:
            delete_channel(old_id, old_name)
        else:
            print(f"  ⏭️  Skipping deletion of {old_name} ({old_id}) — replacement failed")

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    all_ok = all(s for _, _, _, _, s in mapping)
    if all_ok:
        print("  ✅ All 3 forums replaced successfully!")
    else:
        failed = [n for _, _, _, n, s in mapping if not s]
        print(f"  ⚠️  Some channels had issues: {failed}")

if __name__ == "__main__":
    main()
