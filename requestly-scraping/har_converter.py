#!/usr/bin/env python3
"""
har_converter.py — Converts RQSession network events to HAR 1.2 format.

Usage:
    python3 har_converter.py <session_json_path> [output_har_path]

If output_har_path is omitted, the output is written to the same path
with .har extension instead of .json.
"""

import json
import sys
import os
from datetime import datetime, timezone


def parse_rq_session(json_path):
    """Load an RQSession JSON file and return the parsed dict."""
    with open(json_path, "r") as f:
        return json.load(f)


def network_events_to_har(rq_session, source_file=""):
    """
    Convert RQSession network events into a HAR 1.2 structure.
    Returns a dict conforming to the HAR 1.2 spec.
    """
    events = rq_session.get("events", {})
    network_events = events.get("network", [])
    attributes = rq_session.get("attributes", {})

    # Determine the page URL and timings
    page_url = attributes.get("url", source_file or "about:blank")
    start_time = attributes.get("startTime", 0)
    duration = attributes.get("duration", 0)

    # Convert epoch ms to ISO 8601
    if isinstance(start_time, (int, float)) and start_time > 0:
        started_date_time = datetime.fromtimestamp(
            start_time / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(start_time % 1000):03d}Z"
    else:
        started_date_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"

    # Build HAR entries from network events
    entries = []
    for ev in network_events:
        method = ev.get("method", "GET")
        url = ev.get("url", "")
        status = ev.get("status", 0)
        status_text = ev.get("statusText", "")
        content_type = ev.get("contentType", "")
        response_time = ev.get("responseTime", 0)
        timestamp = ev.get("timestamp", 0)
        request_data = ev.get("requestData", {})
        response_data = ev.get("response", "")

        # Request headers
        request_headers = []
        if isinstance(request_data, dict):
            headers = request_data.get("headers", {})
            if isinstance(headers, dict):
                for k, v in headers.items():
                    request_headers.append({"name": str(k), "value": str(v)})

        # Response headers
        response_headers = []
        if isinstance(response_data, dict):
            resp_headers = response_data.get("headers", {})
            if isinstance(resp_headers, dict):
                for k, v in resp_headers.items():
                    response_headers.append({"name": str(k), "value": str(v)})

        # Response body text
        response_body_text = ""
        if isinstance(response_data, str):
            response_body_text = response_data
        elif isinstance(response_data, dict):
            # Could be structured, try body
            response_body_text = json.dumps(response_data.get("body", response_data))

        # Build request object
        request_obj = {
            "method": method,
            "url": url,
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": request_headers,
            "queryString": [],
            "postData": {},
            "headersSize": -1,
            "bodySize": -1,
        }

        # If request data has post body
        post_body = None
        if isinstance(request_data, dict):
            post_body = request_data.get("body")
        if post_body is None and isinstance(request_data, str):
            post_body = request_data
        if post_body:
            request_obj["postData"] = {
                "mimeType": "application/octet-stream",
                    "text": str(post_body or "")[:10000],
            }

        # Build response object
        response_obj = {
            "status": status,
            "statusText": status_text or "",
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": response_headers,
            "content": {
                "size": len(response_body_text),
                "mimeType": content_type or "application/octet-stream",
                "text": response_body_text[:50000] if response_body_text else "",
            },
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": len(response_body_text),
        }

        # Calculate timing
        if timestamp and response_time:
            wait_time = response_time
        else:
            wait_time = 0

        timings_obj = {
            "blocked": -1,
            "dns": -1,
            "connect": -1,
            "send": 0,
            "wait": wait_time,
            "receive": 0,
            "ssl": -1,
        }

        entry = {
            "startedDateTime": started_date_time,
            "time": wait_time,
            "request": request_obj,
            "response": response_obj,
            "cache": {},
            "timings": timings_obj,
        }
        entries.append(entry)

    # Build the full HAR structure
    har = {
        "log": {
            "version": "1.2",
            "creator": {
                "name": "Requestly SDK HAR Converter",
                "version": "1.0.0",
            },
            "browser": {
                "name": attributes.get("environment", {}).get("browser", {}).get("name", "Chrome"),
                "version": attributes.get("environment", {}).get("browser", {}).get("version", ""),
            },
            "pages": [
                {
                    "startedDateTime": started_date_time,
                    "id": "page_1",
                    "title": page_url,
                    "pageTimings": {
                        "onContentLoad": -1,
                        "onLoad": duration,
                    },
                }
            ],
            "entries": entries,
        }
    }

    return har


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    input_path = sys.argv[1]

    if not os.path.exists(input_path):
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    # Determine output path
    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        base, _ = os.path.splitext(input_path)
        output_path = base + ".har"

    # Parse and convert
    try:
        session = parse_rq_session(input_path)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {input_path}: {e}")
        sys.exit(1)

    har = network_events_to_har(session, source_file=input_path)

    # Count network events
    network_count = len(har["log"]["entries"])

    # Write output
    with open(output_path, "w") as f:
        json.dump(har, f, indent=2)

    print(f"[OK] Converted {network_count} network events to HAR 1.2")
    print(f"[OK] Output: {output_path}")

    if network_count > 0:
        first = har["log"]["entries"][0]
        print(f"  First entry: {first['request']['method']} {first['request']['url'][:80]}")
        print(f"  Status: {first['response']['status']}")


if __name__ == "__main__":
    main()
