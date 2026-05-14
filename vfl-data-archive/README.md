# VFL Data Archive

Complete data backup for the Trillion Empire VFL prediction pipeline.
Generated: 2026-05-14 23:55 UTC

## What's Here

### canonical/db/
Clean exports from `history.db` (SQLite) — **61K matches across 285 seasons**.

| File | Records | Description |
|------|---------|-------------|
| `matches_all.jsonl` | 60,992 | Every match ever scraped, with odds and results |
| `odds_history.json` | 55,160 | Scored matches only — full odds + goals |
| `seasons.json` | 285 | Per-season summaries (overs, unders, avg goals) |
| `matchup_history.json` | All H2H | Every pairing with Over% rate and avg goals |
| `recent_form.json` | 24 teams | Per-team Over% in last 5 games |
| `teams.json` | 24 | Team list |

### live-extraction/chunks_v2/
**LIVE API extraction data** — the running harvester saves a full 32-market snapshot
of every upcoming matchday. Each chunk holds ~24 matchdays. This is the CURRENT
live data pipeline, capturing odds as they appear on MSport.

- **55 chunks** totaling 52.5MB
- Markets include: 1X2, Over/Under (1.5/2.5/3.5), Double Chance, GG/NG, DNB, Correct Score, Handicap
- Updated every 2 minutes by the `vfl-empire-harvester-v2` cron

### raw/
Current pipeline state files, analysis outputs, and league tables.

| Directory | Contents |
|-----------|----------|
| `raw/picks/` | All pick histories (VFL + LLM), bet ledger |
| `raw/state/` | Tier matrix, auto-predictor state, cron ledgers |
| `raw/analysis/` | H2H patterns, cassandra edges, torin signals, rank-gap model |
| `raw/tables/` | League tables per matchday (current season) |

### manifest.json
Machine-readable catalog with exact file counts and sizes per directory.

## How to Restore

1. Clone this repo
2. The canonical JSON files are self-contained — no database needed
3. `matches_all.jsonl` can be imported back to SQLite if desired
4. Chunks can be read directly or fed into the pipeline

## Size Summary

Total: **101.9MB**
