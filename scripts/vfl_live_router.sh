#!/bin/bash
cd /home/ubuntu/faith-workspace/vfl-empire/scripts

# Run V2 Predictor
PRED_OUT=$(python3 vfl_live_predictor_v2.py)
if [ -n "$PRED_OUT" ]; then
    echo "$PRED_OUT" | /home/ubuntu/.local/bin/hermes send --to discord:1507922324072960031:1512636049585602682
fi

# Run the Conditional Standing Pattern Predictor
python3 vfl_live_standing_predictor.py

# Run Live Power Parlay DAEMON
