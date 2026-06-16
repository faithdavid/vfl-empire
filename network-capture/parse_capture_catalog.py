#!/usr/bin/env python3
"""Build MSport VFL API catalog + JSON schemas from an interactive capture directory."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

VFL_API_PREFIX = "/api/ng/facts-center/query/frontend/virtual/"
DEFAULT_MARKET_PREFIX = "/api/ng/facts-center/query/frontend/default-market-info/"


def load_ndjson(path: Path):
    if not path.exists():
        return
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if line:
            yield json.loads(line)


def normalize_endpoint(url: str) -> str | None:
    if VFL_API_PREFIX in url:
        parsed = urlparse(url)
        path = parsed.path.split("/api/ng/facts-center/query/frontend/virtual/", 1)[-1]
        path = re.sub(r"eventId=vf:match:\d+", "eventId={eventId}", path)
        path = re.sub(r"seasonId=vf:season:\d+", "seasonId={seasonId}", path)
        path = re.sub(r"matchDay=\d+", "matchDay={matchDay}", path)
        return path.split("?")[0] if "?" not in path else path
    if DEFAULT_MARKET_PREFIX in url:
        return "default-market-info/v2"
    return None


def try_parse_json(preview: str) -> dict | list | None:
    if not preview:
        return None
    try:
        return json.loads(preview)
    except json.JSONDecodeError:
        return None


def _type_name(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _schema_from_obj(obj: Any, depth: int = 0, max_depth: int = 4) -> Any:
    if depth >= max_depth:
        return _type_name(obj)
    if isinstance(obj, dict):
        return {k: _schema_from_obj(v, depth + 1, max_depth) for k, v in obj.items()}
    if isinstance(obj, list):
        if not obj:
            return ["empty"]
        return [_schema_from_obj(obj[0], depth + 1, max_depth)]
    return _type_name(obj)


def extract_endpoint_schema(body: dict | list) -> dict:
    if isinstance(body, dict) and "data" in body:
        data = body["data"]
    else:
        data = body
    return _schema_from_obj(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_dir", type=Path)
    args = parser.parse_args()
    capture_dir = args.capture_dir

    counts: Counter[str] = Counter()
    methods: dict[str, set[str]] = defaultdict(set)
    samples: dict[str, dict] = {}
    schemas: dict[str, dict] = {}

    for fname in ("events_playwright.ndjson", "events_cdp.ndjson"):
        for p in (capture_dir / fname, capture_dir.parent.parent / fname):
            for ev in load_ndjson(p):
                url = ev.get("url", "")
                ep = normalize_endpoint(url)
                if not ep:
                    continue
                key = f"{ev.get('method', 'GET')} {ep}"
                counts[key] += 1
                methods[ep].add(ev.get("method", "GET"))
                preview = ev.get("body_preview", "")
                if key not in samples and preview:
                    parsed = try_parse_json(preview)
                    samples[key] = {
                        "url": url,
                        "status": ev.get("status"),
                        "body_chars": len(preview),
                        "body_truncated": ev.get("body_truncated", False),
                        "parseable": parsed is not None,
                    }
                    if parsed is not None and key not in schemas:
                        schemas[key] = extract_endpoint_schema(parsed)

    catalog = {
        "capture_dir": str(capture_dir),
        "vfl_endpoints": [
            {"endpoint": k, "hits": v, "sample": samples.get(k), "schema": schemas.get(k)}
            for k, v in counts.most_common()
        ],
        "recommended_pipeline": [
            "GET current/match/day/info",
            "GET event/list?sportId=vf:sport:1",
            "GET default-market-info/v2?sportId=vf:sport:1&withOthers=1",
            "GET event/detail?eventId={eventId}",
            "GET result?seasonId={seasonId}&matchDay={matchDay}",
            "GET result/season/selection",
            "GET table",
        ],
        "event_id_format": "vf:match:{numeric_id}",
        "event_id_sources": {
            "event_list": "homeTeam/awayTeam/eventId + embedded markets (7)",
            "event_detail": "full markets (31+) + metadata",
            "result_api": "NO eventId — scores only",
            "default_market_info": "market type catalog (ids, titles, groups)",
        },
        "collection_strategy": {
            "default": "event/detail for every fixture every cycle — upsert all markets + fixture_details",
            "fallback": "event/list embedded markets only if detail API fails",
            "catalog": "default-market-info/v2 once per session or hourly",
        },
    }

    out = capture_dir / "api_catalog.json"
    out.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    parseable = sum(1 for e in catalog["vfl_endpoints"] if e.get("sample", {}).get("parseable"))
    print(f"Wrote {out} ({len(catalog['vfl_endpoints'])} endpoints, {parseable} parseable schemas)")


if __name__ == "__main__":
    main()