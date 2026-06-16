#!/bin/bash
# Wrapper for vfl_live_predictor.py — cron-friendly (Hermes → Discord)
set -euo pipefail
EMPIRE="/home/ubuntu/faith-workspace/vfl-empire"
cd "$EMPIRE/scripts"
PY="${EMPIRE}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then PY=python3; fi

DISCORD_TARGET="discord:1507922324072960031:1512659823081164891"

# Run the python script and capture stdout
PREDICTION_OUTPUT=$("$PY" vfl_live_predictor.py 2>>/tmp/vfl_live_predictor_cron.log)

# Only send to Discord if there's actual data and it's not a silent skip
if [[ -n "$PREDICTION_OUTPUT" && ! "$PREDICTION_OUTPUT" == *"No new data to process"* && ! "$PREDICTION_OUTPUT" == *"No event data returned"* ]]; then
    /home/ubuntu/.local/bin/hermes send --to "$DISCORD_TARGET" "$PREDICTION_OUTPUT"
fi
