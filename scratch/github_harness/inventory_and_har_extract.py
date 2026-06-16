#!/usr/bin/env python3
"""Inventory faithdavid GitHub clones + extract MSport endpoints from HAR files."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent

MSPORT_HINTS = (
    "msport.com",
    "/virtual/",
    "vf:season",
    "vf:match",
    "event/list",
    "event/detail",
    "matchDay",
)


def sizeof_fmt(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.1f}{unit}" if unit != "B" else f"{num}{unit}"
        num /= 1024
    return f"{num:.1f}TB"


def inventory_tree(base: Path) -> dict:
    out = {"path": str(base), "files": 0, "bytes": 0, "by_ext": Counter()}
    if not base.exists():
        return out
    for p in base.rglob("*"):
        if p.is_file():
            out["files"] += 1
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            out["bytes"] += sz
            out["by_ext"][p.suffix.lower() or "(noext)"] += sz
    return out


def sqlite_stats(db_path: Path) -> list[dict]:
    rows = []
    if not db_path.exists() or db_path.stat().st_size < 100:
        return rows
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                n = cur.fetchone()[0]
                rows.append({"db": str(db_path.relative_to(ROOT)), "table": t, "rows": n})
            except sqlite3.Error:
                pass
        con.close()
    except sqlite3.Error as e:
        rows.append({"db": str(db_path.relative_to(ROOT)), "table": f"ERROR:{e}", "rows": -1})
    return rows


def count_text_lines(p: Path, max_sample: int = 0) -> int:
    try:
        with open(p, "rb") as f:
            data = f.read()
        if max_sample and len(data) > max_sample:
            # estimate for huge files
            sample = data[:max_sample]
            lines = sample.count(b"\n")
            return int(lines * (len(data) / len(sample)))
        return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    except OSError:
        return 0


def har_extract(har_path: Path) -> dict:
    stat = {
        "file": str(har_path.relative_to(ROOT)),
        "size": har_path.stat().st_size,
        "entries": 0,
        "msport_entries": 0,
        "endpoints": Counter(),
        "json_bodies": 0,
        "vflm_seasons": set(),
        "vf_match_ids": 0,
        "events_in_bodies": 0,
        "parse_error": None,
    }
    try:
        with open(har_path, encoding="utf-8", errors="replace") as f:
            har = json.load(f)
    except Exception as e:
        stat["parse_error"] = str(e)
        return stat

    entries = har.get("log", {}).get("entries", [])
    stat["entries"] = len(entries)
    for ent in entries:
        req = ent.get("request", {})
        url = req.get("url", "")
        parsed = urlparse(url)
        path = parsed.path or url
        host = parsed.netloc
        is_msport = any(h in url.lower() for h in ("msport.com", "virtual"))
        if is_msport:
            stat["msport_entries"] += 1
            # normalize endpoint key
            key = f"{host}{path.split('?')[0]}"
            stat["endpoints"][key] += 1

        content = ent.get("response", {}).get("content", {})
        text = content.get("text") or ""
        if not text:
            continue
        mime = (content.get("mimeType") or "").lower()
        if "json" not in mime and not text.strip().startswith(("{", "[")):
            continue
        stat["json_bodies"] += 1
        if not is_msport and "vf:" not in text and "VFLM" not in text:
            continue
        # try parse JSON (HAR may be base64 in some exports - skip if not json)
        body = text
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            continue
        blob = json.dumps(obj)
        for m in re.findall(r"VFLM\s*(\d+)", blob):
            stat["vflm_seasons"].add(int(m))
        stat["vf_match_ids"] += len(re.findall(r"vf:match:\d+", blob))
        # count events arrays
        if isinstance(obj, dict):
            data = obj.get("data") or obj
            if isinstance(data, dict):
                for md in data.get("matchDays") or []:
                    if isinstance(md, dict):
                        evs = md.get("events") or []
                        stat["events_in_bodies"] += len(evs)
                for key in ("events", "eventList"):
                    if key in data and isinstance(data[key], list):
                        stat["events_in_bodies"] += len(data[key])

    stat["vflm_seasons"] = sorted(stat["vflm_seasons"])
    stat["endpoints"] = dict(stat["endpoints"].most_common(15))
    return stat


def main():
    repos = ["moneymspport-money", "vfl-complete-dataset", "vfl-complete-data"]
    print("=== REPO INVENTORY (faithdavid clones) ===\n")
    all_sqlite = []
    har_files = []
    csv_stats = []
    jsonl_stats = []

    for repo in repos:
        base = ROOT / repo
        inv = inventory_tree(base)
        print(f"## {repo}")
        print(f"  files={inv['files']} total={sizeof_fmt(inv['bytes'])}")
        top_ext = inv["by_ext"].most_common(8)
        print(f"  top_ext: {', '.join(f'{e}={sizeof_fmt(s)}' for e,s in top_ext)}")
        print()

        for db in sorted(base.rglob("*.db")):
            all_sqlite.extend(sqlite_stats(db))
        for har in sorted(base.rglob("*.har")):
            har_files.append(har)
        for csv in sorted(base.rglob("*.csv")):
            n = count_text_lines(csv)
            csv_stats.append((str(csv.relative_to(ROOT)), n, csv.stat().st_size))
        for jl in sorted(base.rglob("*.jsonl")):
            n = count_text_lines(jl)
            jsonl_stats.append((str(jl.relative_to(ROOT)), n, jl.stat().st_size))

    print("=== SQLITE ===")
    for row in sorted(all_sqlite, key=lambda x: (-x["rows"], x["db"])):
        if row["rows"] >= 0:
            print(f"  {row['db']} :: {row['table']} => {row['rows']:,} rows")
        else:
            print(f"  {row['db']} :: {row['table']}")

    print("\n=== CSV (line counts) ===")
    for path, n, sz in sorted(csv_stats, key=lambda x: -x[1])[:25]:
        print(f"  {n:>8,} lines  {sizeof_fmt(sz):>8}  {path}")

    print("\n=== JSONL ===")
    for path, n, sz in jsonl_stats:
        print(f"  {n:>8,} lines  {sizeof_fmt(sz):>8}  {path}")

    print(f"\n=== HAR FILES ({len(har_files)}) ===")
    har_agg = {
        "files": 0,
        "bytes": 0,
        "entries": 0,
        "msport_entries": 0,
        "json_bodies": 0,
        "events_in_bodies": 0,
        "vf_match_ids": 0,
        "vflm_seasons": set(),
        "endpoints": Counter(),
    }
    for har in har_files:
        h = har_extract(har)
        har_agg["files"] += 1
        har_agg["bytes"] += h["size"]
        har_agg["entries"] += h["entries"]
        har_agg["msport_entries"] += h["msport_entries"]
        har_agg["json_bodies"] += h["json_bodies"]
        har_agg["events_in_bodies"] += h["events_in_bodies"]
        har_agg["vf_match_ids"] += h["vf_match_ids"]
        har_agg["vflm_seasons"].update(h.get("vflm_seasons") or [])
        for ep, c in (h.get("endpoints") or {}).items():
            har_agg["endpoints"][ep] += c
        err = h.get("parse_error")
        print(
            f"  {h['file']}: {sizeof_fmt(h['size'])} entries={h['entries']} "
            f"msport={h['msport_entries']} json={h['json_bodies']} events={h['events_in_bodies']} "
            f"VFLM#={len(h.get('vflm_seasons') or [])} err={err or '-'}"
        )

    print("\n=== HAR AGGREGATE ===")
    print(f"  files={har_agg['files']} bytes={sizeof_fmt(har_agg['bytes'])}")
    print(f"  har_entries={har_agg['entries']:,} msport_entries={har_agg['msport_entries']:,}")
    print(f"  json_response_bodies={har_agg['json_bodies']:,}")
    print(f"  events_parsed_from_bodies={har_agg['events_in_bodies']:,}")
    print(f"  vf:match id occurrences={har_agg['vf_match_ids']:,}")
    seasons = sorted(har_agg["vflm_seasons"])
    if seasons:
        print(f"  distinct VFLM numbers in HAR JSON: {len(seasons)} (min={seasons[0]} max={seasons[-1]})")
    print("  top endpoints:")
    for ep, c in har_agg["endpoints"].most_common(12):
        print(f"    {c:>5}x  {ep}")

    # prematch master quick stats
    master = ROOT / "moneymspport-money/ExtractedData/prematch_odds_master.csv"
    if master.exists():
        n = count_text_lines(master)
        print(f"\n=== prematch_odds_master.csv ===")
        print(f"  lines={n:,} (incl header) size={sizeof_fmt(master.stat().st_size)}")

    # msport_all_raw.json
    for name in ("vfl-complete-dataset/msport_all_raw.json",):
        p = ROOT / name
        if p.exists():
            print(f"\n=== {name} ===")
            print(f"  size={sizeof_fmt(p.stat().st_size)}")
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    # stream peek
                    head = f.read(500_000)
                print(f"  chars_read_sample={len(head):,}")
                vflm_nums = set(re.findall(r"VFLM\s*(\d+)", head))
                print(f"  VFLM hits in sample: {len(vflm_nums)}")
            except OSError as e:
                print(f"  read_err={e}")


if __name__ == "__main__":
    main()