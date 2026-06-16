#!/usr/bin/env bash
# Silent unless ETL is READY — then prints one line for cron delivery.
set -euo pipefail
cd /home/ubuntu/faith-workspace/vfl-empire
OUT=$(python3 scripts/etl_readiness_check.py 2>&1) || true
if echo "$OUT" | grep -q "^READY:"; then
  echo "👑 VFL data ETL complete — vfl_prematch_odds unified; MSport live ingest OK."
  echo "$OUT"
fi
exit 0