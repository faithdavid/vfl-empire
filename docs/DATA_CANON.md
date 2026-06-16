# VFL Empire — Data canon

**Operational database:** PostgreSQL `vfl_empire` (`faith-workspace/vfl-empire`, `services/common/db_manager.py`).

## Silver (source of truth)

| Table | Grain | Dedupe |
|-------|--------|--------|
| `vfl_seasons` | 1 row / MSport season | `season_id` (text, e.g. `vf:season:3100286`) |
| `vfl_matchdays` | 1 row / season / MD | `(season_id FK, matchday_number)` |
| `vfl_results_v2` | 1 row / finished fixture | `(matchday_id, home_team, away_team)` — **canonical pass:** `scripts/dedupe_results_canonical.py` (30×8, MSport source priority) |
| `vfl_prematch_odds` | 1 row / market selection | `(event_id, market_name, specifiers, selection_name)` — latest `captured_at` wins |

## Writers (live)

- **Results:** `services/ingester/server.py` → `sync_chronological_data`
- **Deep prematch:** `scripts/full_odds_and_details_collector.py`, `scripts/data_pipeline_daemon.py`, ingester `_ingest_event_list` → `upsert_prematch_records`

## Bronze (archive — no new writers)

- SQLite: `vfl-complete-data/databases/history.db`, `sovereign.db`, `vfl_odds.db`
- PG legacy: `matches`, `fixture_markets`, `vfl_odds_v2` (read-only after backfill completes)

## Gold (derived)

- Views: `v_fixture_results`, `v_season_completeness` (`scripts/sql/create_analytics_views.sql`)
- Signals: `vfl-complete-data/signals/predictions_latest.json`
- `vfl_predictions` (live picks)

## Migrations

- Prematch unify: `scripts/backfill_prematch_odds.py`
- History results: `scripts/migrate_history_matches_to_pg.py` (from `faith-workspace/.../history.db` only)
- GitHub bronze: `scripts/ingest_github_bronze_to_pg.py`, `scripts/ingest_har_virtual_results.py` — see `docs/GITHUB_BRONZE_INGEST.md`
- Results dedupe (MSport truth): `scripts/dedupe_results_canonical.py` — `vf:match:` > `history:` > `github_har_result:`; one tier per MD; max 8 fixtures/MD
- Season map export: `docs/SEASON_ID_MAP.csv` via `scripts/build_season_id_map.py`

## Analyst rule

Train labels from `vfl_results_v2` only; features from `vfl_prematch_odds` with `captured_at` ≤ kickoff. Flag seasons with &lt;21 markets as `no_deep_odds`.

**Narrative history:** see `docs/JOURNEY_LOG.md` (battles, dedupe, odd/even surge, deep goals, backtest).

**Partial prematch is kept:** every captured selection from MSport (full 21-family seasons, partial MDs, or shallow-only eras) is stored in `vfl_prematch_odds` — do not drop incomplete seasons; use `distinct_market_families` / `fixtures_with_prematch` from `v_season_completeness` to filter analysis.