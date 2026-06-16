#!/bin/bash
# VFL Microservice Orchestrator — unified control for all 4 services
set -e

PYTHON="/home/ubuntu/.hermes/hermes-agent/venv/bin/python"
BASE="/home/ubuntu/faith-workspace/vfl-empire"
export PYTHONPATH="$BASE/services"

mkdir -p "$BASE/logs"

ACTION="${1:-status}"
SERVICE="${2:-all}"

case "$ACTION" in
  start)
    echo "Starting VFL microservices..."
    systemctl --user daemon-reload
    for svc in vfl-ingester vfl-predictor vfl-betting vfl-settlement vfl-orchestrator vfl-streak-betting; do
      if [ "$SERVICE" = "all" ] || [ "$SERVICE" = "$svc" ]; then
        echo "  Starting $svc..."
        systemctl --user start "$svc" 2>/dev/null || true
        systemctl --user enable "$svc" 2>/dev/null || true
      fi
    done
    echo "Done."
    ;;
  stop)
    for svc in vfl-orchestrator vfl-ingester vfl-predictor vfl-betting vfl-settlement vfl-streak-betting; do
      if [ "$SERVICE" = "all" ] || [ "$SERVICE" = "$svc" ]; then
        echo "  Stopping $svc..."
        systemctl --user stop "$svc" 2>/dev/null || true
      fi
    done
    echo "Done."
    ;;
  restart)
    "$0" stop "$SERVICE"
    sleep 1
    "$0" start "$SERVICE"
    ;;
  status)
    echo "=== VFL Microservice Status ==="
    systemctl --user status vfl-ingester vfl-predictor vfl-betting vfl-settlement vfl-orchestrator vfl-streak-betting 2>&1 | grep -E "(●|Active:|Loaded:)" || echo "(no services running)"
    echo ""
    echo "=== Health Checks ==="
    for port in 8001 8002 8003 8004; do
      name="ingester predictor betting settlement"
      sname=$(echo $name | cut -d' ' -f$((port-8000)))
      if curl -sf "http://localhost:$port/health" > /dev/null 2>&1; then
        echo "  :$port  ✅ $sname OK"
      else
        echo "  :$port  ❌ $sname DOWN"
      fi
    done
    ;;
  trigger)
    # Trigger one-off actions
    case "${2:-season}" in
      season)  curl -s -X POST http://localhost:8001/ingest/season ;;
      predict) curl -s -X POST http://localhost:8002/predict ;;
      evaluate) curl -s -X POST http://localhost:8003/evaluate ;;
      settle)  curl -s -X POST http://localhost:8004/settle ;;
      *) echo "Actions: season, predict, evaluate, settle" ;;
    esac
    ;;
  logs)
    tail -f "$BASE/logs/${SERVICE:-ingester}.log" 2>/dev/null || echo "No log file for $SERVICE"
    ;;
  test)
    echo "=== Testing All Services ==="
    for port in 8001 8002 8003 8004; do
      name="ingester predictor betting settlement"
      sname=$(echo $name | cut -d' ' -f$((port-8000)))
      result=$(curl -sf "http://localhost:$port/health" 2>/dev/null)
      if [ $? -eq 0 ]; then
        echo "  :$port  ✅ $sname — $result"
      else
        echo "  :$port  ❌ $sname DOWN"
      fi
    done
    echo ""
    echo "=== Trigger prediction cycle ==="
    curl -s -X POST http://localhost:8002/predict
    sleep 2
    echo ""
    echo "=== Get latest predictions ==="
    curl -s http://localhost:8002/predictions/latest | python3 -m json.tool 2>/dev/null | head -30
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|trigger|logs|test} [service|action]"
    echo "  Services: all, vfl-ingester, vfl-predictor, vfl-betting, vfl-settlement"
    echo "  Actions: season, predict, evaluate, settle"
    ;;
esac
