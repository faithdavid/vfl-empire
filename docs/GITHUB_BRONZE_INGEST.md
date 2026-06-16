
## GitHub bronze ingest (DS/ML prep)

**Principle:** Bronze (GitHub/HAR/SQLite) → **silver only** (`vfl_results_v2`, `vfl_prematch_odds`). Gold = views + signals.

### Industry-style checks (exploration / modeling)

| Dimension | Rule |
|-----------|------|
| **Grain** | Results: 1 row / `(matchday_id, home_team, away_team)`. Prematch: 1 row / `(event_id, market_name, specifiers, selection_name)`. |
| **Validity** | Results require parseable `fullTime` `H:A`. Odds require numeric `odds > 0` where used. |
| **Uniqueness** | `ON CONFLICT DO NOTHING` (results) or upsert latest `captured_at` (prematch). |
| **Lineage** | `source` / `event_id` prefix: `github_har_result:`, `github_har_event_list`, `github_prematch_master_csv`, `history:`. |
| **Consistency** | Seasons: `vf:season:` + `VFLM ####` via `vfl_seasons`. Time fields: Unix ms on API payloads only. |
| **Completeness** | Use `v_season_completeness`: 30 MD, ≥240 results, `distinct_market_families` for deep odds. |

### Scripts

```bash
python3 scripts/ingest_github_bronze_to_pg.py          # dataset history + CSV + HAR event lists
python3 scripts/ingest_har_virtual_results.py          # HAR virtual/result → results (VFLM 3137–3239 band)
python3 scripts/data_reconciliation_report.py          # before/after counts
python3 scripts/etl_readiness_check.py                 # gate for downstream jobs
```

### Modeling

- **Labels:** `vfl_results_v2` only (`home_goals`, `away_goals`, derived outcomes).
- **Features:** `vfl_prematch_odds` with `captured_at` ≤ kickoff; flag `no_deep_odds` when &lt;21 market families.
- **Do not** train on `github_csv:` synthetic event_ids without joining to `vf:match:` where possible.