#!/bin/bash
cd /home/ubuntu/faith-workspace/vfl-empire/scripts || exit 1
exec python3 vfl_rapid_daemon.py --once --dry-run 2>> /tmp/vfl_rapid_daemon_cron.log
