# VFL Data Pipeline Refresh & Alignment Confirmation (2026-06-13)

## Summary
Confirmed that the live data ingestion pipeline is actively feeding fresh data from prematch odds/markets through to results settlement, up to the current time. Executed full alignment to connect everything end-to-end in the analysis layer (DB view + CSV + manifest). This brings the convenient joined dataset (used by the notebook, pattern miners, odds DNA work, etc.) up to date with live operations.

## Live Pipeline Status
- **Active daemons/processes**:
  - `services/ingester/server.py` (ingesting seasons/fixtures)
  - Main data daemon (`data_pipeline.log`): collecting `full event/detail + upserting markets...` (prematch odds), event_id_sync, processing matchdays.
  - `services/predictor/server.py`
  - `services/settlement/server.py` + `msport_settlement_mirror.py`
  - `vfl_rapid_daemon.py --dry-run`
- **Recent activity** (from logs ~07:33–07:44 on 2026-06-13):
  - VFLM 5385 MD12 → MD13 → MD14 → MD15 actively being processed.
  - Status updates: MATCH / POST_MATCH.
  - Markets/odds collection and event detail upserts happening in real-time cycles.
  - Ingester receiving POST /ingest/season and status checks.
- Raw tables (`vfl_matchdays`, `vfl_results_v2`, `fixture_markets`, etc.) are being populated continuously by the operational pipeline (ingester → markets/prematch + results comber/settlement).

## Alignment Execution
Ran:
```bash
python3 scripts/align_dataset.py --refresh --export --validate
```
- **Before**: ~61,342 fixtures, 154 seasons (manifest from 2026-06-11, up to VFLM 5360). Aligned CSV last exported then.
- **After**: **76,549 fixtures**, **178 seasons**. Latest season in aligned layer: **VFLM 5384** (MDs up to 29 in the snapshot).
- New files:
  - `data/aligned/dataset_manifest.json` (updated 07:43)
  - `data/aligned/vfl_fixture_unified.csv` (14.1 MB, exported 07:44)
- PG `vfl_fixture_aligned` (and related) rebuilt from live `vfl_results_v2` + matchdays + odds/markets joins.
- Validation output confirmed expanded coverage (core odds 42,336; snapshots 75,991).

**Note**: Live daemon continued advancing to VFLM 5385 MD15 even during/after the run (logs show ongoing sync and market collection for 5385). The aligned snapshot captures up to 5384 fully; re-run the align command later for incremental newer data.

## End-to-End Connection Verified (Prematch Odds ↔ Results)
The alignment joins prematch data (from live `event/detail` markets collection in the daemon) with results (from settlement/`vfl_results_v2`).

**Latest seasons in aligned (with both prematch odds and results):**
- VFLM 5384 MD29 and earlier MDs: 8 fixtures each, all with results and has_odds = 8.

**Sample recent fixtures proving the join (prematch odds fields + actual outcomes):**
- VFLM 5384 MD29 | Bournemouth vs Everton | gg=2.45, o25=2.75 | goals 1-2 (total 3)
- VFLM 5384 MD29 | Fulham vs Brighton | gg=2.25, o25=2.70 | goals 0-1 (total 1)
- VFLM 5384 MD29 | Leeds vs Manchester Blue | gg=2.10, o25=2.15 | goals 0-0 (total 0)
- VFLM 5384 MD29 | Liverpool vs Tottenham | gg=1.80, o25=1.75 | goals 1-0 (total 1)
- VFLM 5384 MD29 | Manchester Red vs Crystal Palace | gg=2.05, o25=1.65 | goals 2-1 (total 3)

These rows come directly from the refreshed `vfl_fixture_aligned` (and matching CSV). Prematch odds were collected before the match; results after settlement. Full end-to-end from live daemon → DB → aligned analysis layer.

## Files & Artifacts Updated in vfl-empire
- `data/aligned/` : Fresh CSV + manifest + (implied) complete_seasons.txt
- `research_logs/vfl_data_pipeline_refresh_and_alignment_2026-06-13.md` (this file)
- `vfl_master_progress_log.md` (appended Phase 6 section)
- `surge-findings/libraries-eda-guide.html` (updated with this progress section)
- `surge-findings/index.html` remains the patterns dump (not modified here)

## Next for Analysis / Hermes
- Reload `notebooks/vfl_analysis.ipynb` or the fresh `data/aligned/vfl_fixture_unified.csv` — now includes the latest joined data through VFLM 5384.
- The live feed (VFLM 5385+) is still flowing; periodic `align_dataset.py --refresh --export` will keep the analysis layer current.
- This solidifies the foundation for further pattern mining, odds DNA work, ML on the unified matrix, etc., on fresher data.
- All raw prematch (odds/markets) to results are confirmed connected in the operational DB; the alignment makes it queryable/usable for intelligence work.

## Sources of Confirmation
- Active logs: `logs/data_pipeline.log`, `logs/ingester.log`, `logs/predictor.log` etc. (very recent entries for 5385 MDs and market upserts).
- Running processes: ingester, predictor, settlement, rapid daemon, data pipeline.
- DB queries (post-align): vfl_fixture_aligned now reflects expanded seasons/MDs with joined odds+results.
- Alignment script output and file timestamps.

This completes the confirmation and refresh cycle. The system is now end-to-end current for continued work. 

(Logged 2026-06-13 via Grok session in vfl-empire workspace.)