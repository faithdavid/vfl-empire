#!/usr/bin/env bash

# vfl_trap_cron.sh
# Runs the Trap Interceptor to identify Master Locks and post to Discord Forum.

cd /home/ubuntu/faith-workspace/vfl-empire/scripts
python3 vfl_trap_interceptor.py >> /home/ubuntu/faith-workspace/vfl-empire/logs/trap_interceptor.log 2>&1
python3 vfl_tier_routing_daemon.py >> /home/ubuntu/faith-workspace/vfl-empire/logs/tier_routing.log 2>&1
