#!/bin/bash
# Wrapper for vfl_live_predictor.py — cron-friendly
# Runs silently on repeat matchdays, outputs prediction report on new ones
cd /home/ubuntu/faith-workspace/vfl-empire/scripts
exec python3 vfl_live_predictor.py 2>/tmp/vfl_live_predictor_cron.log
