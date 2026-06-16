#!/bin/bash
# vfl_onimix_cron.sh — Onimix VFL Engine Cron Wrapper
# Runs the Onimix feeder and prints a short summary to stdout.
# Intended to be invoked by cron; stdout goes to Discord (#vfl-predictions).
# Stderr is logged to /tmp/vfl_onimix_feeder.log for debugging.
set -e

cd /home/ubuntu/faith-workspace/vfl-empire/scripts || {
    echo "[ERROR] Cannot cd to scripts directory" >&2
    exit 1
}

python3 vfl_onimix_feeder.py 2>> /tmp/vfl_onimix_feeder.log

echo "--- Onimix Feeder Complete ---"
