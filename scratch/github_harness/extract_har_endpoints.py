#!/usr/bin/env python3
"""Write deduped MSport API response JSON from all HAR files under a root."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent / "moneymspport-money" / "HarFiles"
OUT = Path(__file__).resolve().parent / "extracted_har"
OUT.mkdir(exist_ok=True)

API_PREFIX = "/api/ng/facts-center/query/frontend/virtual/"


def endpoint_key(url: str) -> str:
    p = urlparse(url)
    path = p.path
    if API_PREFIX in path:
        return path.split(API_PREFIX, 1)[1].strip("/") or path
    return path


def main():
    by_endpoint: dict[str, list] = {}
    seen_hashes: set[str] = set()
    stats = {"hars": 0, "responses": 0, "stored": 0, "events": 0, "markets_rows": 0}

    for har_path in sorted(ROOT.glob("*.har")):
        stats["hars"] += 1
        try:
            har = json.loads(har_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        for ent in har.get("log", {}).get("entries", []):
            url = ent.get("request", {}).get("url", "")
            if "msport.com" not in url or API_PREFIX not in url:
                continue
            text = (ent.get("response", {}).get("content", {}) or {}).get("text") or ""
            if not text.strip().startswith("{"):
                continue
            stats["responses"] += 1
            h = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            try:
                body = json.loads(text)
            except json.JSONDecodeError:
                continue
            ep = endpoint_key(url)
            by_endpoint.setdefault(ep, []).append({"har": har_path.name, "url": url, "body": body})
            stats["stored"] += 1
            blob = json.dumps(body)
            stats["events"] += len(re.findall(r'"eventId"', blob))
            stats["markets_rows"] += blob.count('"markets"')

    manifest = {
        "stats": stats,
        "endpoints": {k: len(v) for k, v in sorted(by_endpoint.items(), key=lambda x: -len(x[1]))},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for ep, items in by_endpoint.items():
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", ep)[:120]
        (OUT / f"{safe}.json").write_text(json.dumps(items, indent=2)[:50_000_000])

    print(json.dumps(manifest, indent=2))
    print(f"Wrote extracted_har/ under {OUT.parent}")


if __name__ == "__main__":
    main()