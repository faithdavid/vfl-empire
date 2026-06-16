#!/usr/bin/env python3
"""
Ingest faithdavid GitHub harness bronze into Postgres silver (vfl_empire).

Sources (under scratch/github_harness by default):
  - vfl-complete-dataset/databases/history.db  -> vfl_results_v2 + shallow vfl_prematch_odds
  - moneymspport-money/ExtractedData/prematch_odds_master.csv -> shallow prematch
  - extracted_har/*.json (event/list, match/day/event/list) -> shallow prematch from embedded markets

Does not replace live MSport writers; uses ON CONFLICT dedupe per DATA_CANON.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EMPIRE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EMPIRE / "services"))

from common.db_manager import get_db
from common.msport_client import records_from_event
from common.prematch_odds import upsert_prematch_records

HARNESS = EMPIRE / "scratch" / "github_harness"
log = logging.getLogger("ingest_github_bronze")

VFLM_RE = re.compile(r"VFLM\s*(\d+)", re.I)


def ms_to_iso(ms) -> str | None:
    try:
        v = int(ms)
        if v > 1e12:
            return datetime.fromtimestamp(v / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None
    return None


def migrate_history_db(db_path: Path, *, skip_prematch: bool, dry_run: bool) -> None:
    script = EMPIRE / "scripts" / "migrate_history_matches_to_pg.py"
    cmd = [sys.executable, str(script), "--db", str(db_path)]
    if skip_prematch:
        cmd.append("--skip-prematch")
    if dry_run:
        cmd.append("--dry-run")
    log.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(EMPIRE))


def prematch_from_master_csv(csv_path: Path, *, dry_run: bool) -> dict:
    stats = {"rows": 0, "selections": 0, "upserted": 0}
    if not csv_path.exists():
        log.warning("Missing %s", csv_path)
        return stats

    records: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            stats["rows"] += 1
            season = (row.get("season") or "").strip()
            season_id = (row.get("season_id") or "").strip()
            if not season_id.startswith("vf:season:"):
                continue
            try:
                md = int(row.get("match_day") or 0)
            except ValueError:
                md = None
            home = (row.get("home") or "").strip()
            away = (row.get("away") or "").strip()
            captured = row.get("captured_at") or None
            # synthetic event until vf:match known
            event_id = f"github_csv:{season_id}:{md}:{home}:{away}"
            base = {
                "event_id": event_id,
                "season_id": season_id,
                "matchday_number": md,
                "home_team": home,
                "away_team": away,
                "source": "github_prematch_master_csv",
            }

            def add(market, spec, sel, key):
                val = row.get(key)
                if val is None or val == "":
                    return
                try:
                    odds = float(val)
                except ValueError:
                    return
                records.append({**base, "market_name": market, "specifiers": spec, "selection_name": sel, "odds": odds})
                stats["selections"] += 1

            add("1x2", "", "Home", "odds_h")
            add("1x2", "", "Draw", "odds_d")
            add("1x2", "", "Away", "odds_a")
            # implied_vig only — no O/U in this csv unless extended

    if dry_run:
        log.info("CSV dry-run: %s fixture rows -> %s selections", stats["rows"], stats["selections"])
        return stats

    for i in range(0, len(records), 500):
        stats["upserted"] += upsert_prematch_records(records[i : i + 500])
    log.info("CSV upsert touched ~%s rows (%s selections)", stats["upserted"], stats["selections"])
    return stats


def ingest_har_json(har_dir: Path, *, dry_run: bool) -> dict:
    stats = {"files": 0, "events": 0, "selections": 0, "upserted": 0}
    targets = [
        "event_list.json",
        "match_day_event_list.json",
    ]
    records: list[dict] = []
    for name in targets:
        path = har_dir / name
        if not path.exists():
            continue
        stats["files"] += 1
        try:
            items = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            log.error("HAR JSON parse failed %s: %s", path, e)
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            body = item.get("body") or {}
            data = body.get("data") if isinstance(body, dict) else {}
            if not isinstance(data, dict):
                data = body if isinstance(body, dict) else {}
            match_days = data.get("matchDays") or []
            if not match_days and "events" in data:
                match_days = [{"events": data["events"], "matchDay": data.get("matchDay"), "seasonId": data.get("seasonId")}]
            for md in match_days:
                if not isinstance(md, dict):
                    continue
                md_num = md.get("matchDay") or md.get("roundNumber")
                season_id = md.get("seasonId")
                captured = ms_to_iso(md.get("matchDayStartTime") or md.get("seasonStartTime"))
                for ev in md.get("events") or []:
                    if not ev.get("eventId"):
                        continue
                    stats["events"] += 1
                    recs = records_from_event(
                        ev,
                        season_id=season_id,
                        matchday_number=md_num,
                        source="github_har_event_list",
                    )
                    stats["selections"] += len(recs)
                    records.extend(recs)

    if dry_run:
        log.info("HAR dry-run: %s files, %s events, %s selections", stats["files"], stats["events"], stats["selections"])
        return stats

    for i in range(0, len(records), 500):
        stats["upserted"] += upsert_prematch_records(records[i : i + 500], captured_at=None)
    log.info("HAR upsert touched ~%s rows", stats["upserted"])
    return stats


def count_silver() -> dict:
    with get_db() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM vfl_results_v2")
        r = cur.fetchone()
        results = r["c"] if isinstance(r, dict) else r[0]
        cur.execute("SELECT COUNT(*) AS c FROM vfl_prematch_odds")
        r = cur.fetchone()
        prematch = r["c"] if isinstance(r, dict) else r[0]
        cur.execute(
            "SELECT COUNT(*) AS c FROM vfl_prematch_odds WHERE source LIKE 'github%'"
        )
        r = cur.fetchone()
        github_pm = r["c"] if isinstance(r, dict) else r[0]
        cur.execute(
            "SELECT COUNT(*) AS c FROM vfl_results_v2 WHERE event_id LIKE 'history:%'"
        )
        r = cur.fetchone()
        history_ev = r["c"] if isinstance(r, dict) else r[0]
    return {
        "vfl_results_v2": results,
        "vfl_prematch_odds": prematch,
        "github_prematch_rows": github_pm,
        "history_event_id_results": history_ev,
    }


def main():
    ap = argparse.ArgumentParser(description="Ingest GitHub harness into vfl_empire silver")
    ap.add_argument("--harness-dir", type=Path, default=HARNESS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-history", action="store_true")
    ap.add_argument("--skip-csv", action="store_true")
    ap.add_argument("--skip-har", action="store_true")
    ap.add_argument("--skip-har-results", action="store_true")
    ap.add_argument("--skip-prematch-on-history", action="store_true", help="Only results from dataset history.db")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    before = count_silver()
    log.info("BEFORE silver: %s", before)

    root = args.harness_dir
    if not args.skip_history:
        db = root / "vfl-complete-dataset/databases/history.db"
        if db.exists():
            migrate_history_db(
                db,
                skip_prematch=args.skip_prematch_on_history,
                dry_run=args.dry_run,
            )
        else:
            log.warning("No dataset history.db at %s", db)

    if not args.skip_csv:
        prematch_from_master_csv(
            root / "moneymspport-money/ExtractedData/prematch_odds_master.csv",
            dry_run=args.dry_run,
        )

    if not args.skip_har:
        ingest_har_json(root / "extracted_har", dry_run=args.dry_run)

    if not args.skip_har_results:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ingest_har_virtual_results",
            EMPIRE / "scripts" / "ingest_har_virtual_results.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        har_result = root / "extracted_har" / "result.json"
        mod.ingest_result_json(har_result, dry_run=args.dry_run)

    after = count_silver()
    log.info("AFTER silver: %s", after)
    log.info(
        "DELTA results=%s prematch=%s github_prematch=%s",
        after["vfl_results_v2"] - before["vfl_results_v2"],
        after["vfl_prematch_odds"] - before["vfl_prematch_odds"],
        after["github_prematch_rows"] - before["github_prematch_rows"],
    )


if __name__ == "__main__":
    main()