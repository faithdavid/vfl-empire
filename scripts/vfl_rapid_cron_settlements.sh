#!/bin/bash
cd /home/ubuntu/faith-workspace/vfl-empire/scripts || exit 1
exec python3 vfl_rapid_daemon.py --once --dry-run --report-settlements 2>> /tmp/vfl_settlements_cron.log
