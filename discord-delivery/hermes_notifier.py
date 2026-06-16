import json
import os
import urllib.request
import logging

logger = logging.getLogger("[HERMES-NOTIFIER]")

# Tokens from .env
SLACK_TOKEN = "xoxb-10487508680051-11085741825046-b75a6XgRhMS0UnXNms2WjIxv"
SLACK_CHANNEL = "C0AEWQ2628H"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1310344464522969189/p0-7vI7vI7vI7vI7vI7vI7vI7vI7vI7vI7vI7vI7vI7vI7vI" # Need real one, but I'll use Slack as primary for Hermes

def send_slack(text: str):
    """Sends a message to the Slack channel."""
    url = "https://slack.com/api/chat.postMessage"
    payload = {
        "channel": SLACK_CHANNEL,
        "text": text
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SLACK_TOKEN}"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"Slack failed: {e}")
        return None

def send_discord(text: str):
    """Sends a message to the Discord channel using hermes send CLI."""
    import subprocess
    logger.info("Sending forecast to Discord channel via hermes send...")
    try:
        # Run: hermes send --to discord:1507922324072960031:1512636049585602682
        res = subprocess.run(
            ["/home/ubuntu/.local/bin/hermes", "send", "--to", "discord:1507922324072960031:1512636049585602682", text],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info("Sent successfully via hermes send.")
        return 200
    except Exception as e:
        logger.error(f"Failed sending via hermes send: {e}")
        # Fallback to the webhook if hermes send fails
        if not DISCORD_WEBHOOK or "api/webhooks" not in DISCORD_WEBHOOK:
            return None
        payload = {"content": text}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status
        except Exception as e2:
            logger.error(f"Discord webhook fallback failed: {e2}")
            return None

def notify(msg: str):
    """Notify all configured channels."""
    logger.info(f"Notifying: {msg}")
    send_slack(msg)
    send_discord(msg)
