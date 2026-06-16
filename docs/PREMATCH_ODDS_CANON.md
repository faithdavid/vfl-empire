# Canonical pre-match odds (2026-06-14)

**Table:** `vfl_prematch_odds` — one row per `(event_id, market_name, specifiers, selection_name)`.

**Writers (live):**
- `scripts/full_odds_and_details_collector.py` → `event_detail` / `event_list` (data pipeline daemon ~30s)
- `services/ingester/server.py` → `ingester_event_list` on each `/ingest/season` poll

**Legacy (read-only / deprecate later):** `fixture_markets`, `vfl_odds_v2` — ingester still mirrors v2 for cluster scripts.

**Backfill:**
```bash
python3 scripts/backfill_prematch_odds.py --batch 5000
```

**Schema:** `scripts/sql/create_vfl_prematch_odds.sql`