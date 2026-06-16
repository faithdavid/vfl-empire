#!/usr/bin/env python3
"""
📡 VFL DISCORD NOTIFIER — Discord Webhook Integration Utility 📡
=================================================================
Sends structured Discord embeds for predictions, regime classifications,
and system alerts. Designed as a modular importable utility.

Usage:
  python3 vfl_discord_notifier.py --test "Your alert message"
  python3 vfl_discord_notifier.py --test "Alert Title|Alert Description|0xFF0000"
  python3 vfl_discord_notifier.py --fields
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Environment ────────────────────────────────────────────────────────────

ENV_PATH = Path("/home/ubuntu/.hermes/profiles/vfl-bot/.env")
DEFAULT_WEBHOOK = "https://discord.com/api/webhooks/placeholder"  # fallback


def _load_env_file(env_path: Path = ENV_PATH) -> dict:
    """Load key=value pairs from a .env file (no external dep)."""
    env = {}
    if not env_path.is_file():
        print(f"[WARN] .env file not found at {env_path}", file=sys.stderr)
        return env
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip optional quotes
            if len(value) > 1 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            env[key] = value
    return env


def get_webhook_url() -> str:
    """Return the Discord webhook URL from env, or default placeholder."""
    env = _load_env_file()
    url = env.get("DISCORD_WEBHOOK_URL", "")
    if not url:
        print(
            "[WARN] DISCORD_WEBHOOK_URL not found in .env. "
            "Using placeholder. Set it in your .env to enable Discord alerts.",
            file=sys.stderr,
        )
        return DEFAULT_WEBHOOK
    return url


# ── Embed Builder ──────────────────────────────────────────────────────────


def build_embed(
    title: str,
    description: str,
    color: int = 0x00FF00,
    fields: list = None,
) -> dict:
    """
    Build a Discord embed dict ready for webhook POST.

    Parameters
    ----------
    title : str
        Bold embed title (displayed at top).
    description : str
        Main body text of the embed.
    color : int
        Decimal hex colour for the left accent bar (default green 0x00FF00).
    fields : list[dict] or None
        Optional list of field dicts:
        [{"name": "...", "value": "...", "inline": True}]
        Ideal for metrics (Draw rates, Avg goals, P&L, etc.).

    Returns
    -------
    dict
        The embed payload to nest inside a webhook body.
    """
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fields:
        embed["fields"] = fields
    return embed


# ── Webhook Poster ─────────────────────────────────────────────────────────


def send_discord_alert(
    title: str,
    description: str,
    color: int = 0x00FF00,
    fields: list = None,
    webhook_url: str = None,
) -> bool:
    """
    Send a structured Discord embed alert via webhook.

    Parameters
    ----------
    title : str
        Embed title.
    description : str
        Embed description / body.
    color : int
        Hexadecimal colour code (default 0x00FF00 = green).
    fields : list[dict] or None
        Optional field rows e.g.
        [{"name": "Draw Rate", "value": "34.2%", "inline": True},
         {"name": "Avg Goals", "value": "2.81", "inline": True}]
    webhook_url : str or None
        Override webhook URL. If None, loads from .env.

    Returns
    -------
    bool
        True if successfully posted, False otherwise.
    """
    if webhook_url is None:
        webhook_url = get_webhook_url()

    if "placeholder" in webhook_url:
        print("[SKIP] Webhook URL is a placeholder — not sending.", file=sys.stderr)
        return False

    embed = build_embed(title, description, color, fields)
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "VFL-Notifier/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 204):
                return True
            else:
                print(
                    f"[ERROR] Discord webhook returned HTTP {resp.status}: "
                    f"{resp.read().decode(errors='replace')}",
                    file=sys.stderr,
                )
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(
            f"[ERROR] HTTP {e.code} from Discord webhook: {body}",
            file=sys.stderr,
        )
        return False
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"[ERROR] Network error posting to Discord: {e}", file=sys.stderr)
        return False


# ── CLI Test Routine ───────────────────────────────────────────────────────


def _parse_fields_arg(raw: str) -> list:
    """Parse --fields argument: 'name|value|inline,name2|value2|inline2'."""
    fields = []
    for item in raw.split(","):
        parts = [p.strip() for p in item.split("|")]
        if len(parts) >= 2:
            fields.append({
                "name": parts[0],
                "value": parts[1],
                "inline": len(parts) < 3 or parts[2].lower() in ("true", "1", "yes"),
            })
    return fields


def _run_test(args: list):
    """Parse CLI args and send a test alert."""
    test_msg = "Test alert from VFL Discord Notifier"
    color = 0x00FF00
    title = "🧪 VFL Notifier Test"
    fields = None

    for arg in args:
        if arg.startswith("--fields="):
            fields = _parse_fields_arg(arg.split("=", 1)[1])
        elif arg.startswith("--test="):
            test_msg = arg.split("=", 1)[1]
        elif arg == "--test" or arg == "-t":
            # The next argument (if any) will be the message — handled below
            pass

    # Support pipe-delimited format: "Title|Description|HexColor"
    if "|" in test_msg:
        parts = [p.strip() for p in test_msg.split("|")]
        if len(parts) >= 1:
            title = parts[0]
        if len(parts) >= 2:
            test_msg = parts[1]
        if len(parts) >= 3:
            try:
                color = int(parts[2], 16) if parts[2].startswith("0x") else int(parts[2])
            except ValueError:
                pass

    # If --test alone (no value), pull next positional
    if test_msg == "Test alert from VFL Discord Notifier" and len(args) >= 2:
        test_msg = args[1]

    print(f"🔔 Sending test alert...")
    print(f"   Title  : {title}")
    print(f"   Message: {test_msg}")
    print(f"   Color  : 0x{color:06X}")
    if fields:
        print(f"   Fields : {json.dumps(fields, indent=2)}")

    success = send_discord_alert(
        title=title,
        description=test_msg,
        color=color,
        fields=fields,
    )

    if success:
        print("✅ Alert sent successfully!")
    else:
        print("⚠️  Alert not sent (placeholder or network issue — this is expected if no real webhook URL is configured).")
        sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    args = sys.argv[1:]

    # Check for --test, -t, or --test=value syntax
    is_test = any(a in ("--test", "-t") for a in args)
    is_test |= any(a.startswith("--test=") for a in args)
    is_test |= any(a.startswith("--fields") for a in args)

    if is_test:
        _run_test(args)
    else:
        print(f"Unknown arguments: {' '.join(args)}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
