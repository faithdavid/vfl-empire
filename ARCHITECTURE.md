# VFL Empire — Microservice Architecture

## Core Principle
Replace monolithic cron scripts with independently deployable, single-responsibility services communicating over REST + Redis pub/sub.

## Service Map

```
┌─────────────────────────────────────────────────────────────┐
│                      Redis Pub/Sub                           │
│  (event bus: fixture_update, prediction_ready, bet_placed)  │
└─────────────────────────────────────────────────────────────┘
         ▲            ▲            ▲            ▲
         │            │            │            │
┌────────┴──┐ ┌───────┴────┐ ┌────┴────┐ ┌────┴────────┐
│ Data      │ │ Prediction │ │ Betting │ │ Settlement  │
│ Ingester  │ │ Engine     │ │ Agent   │ │ Service     │
│ (:8001)   │ │ (:8002)    │ │ (:8003) │ │ (:8004)     │
└───────────┘ └────────────┘ └─────────┘ └─────────────┘
      │              │              │             │
      ▼              ▼              ▼             ▼
┌────────────────────────────────────────────────────────────┐
│                   Shared Data Layer                          │
│  history.db  vfl_odds.db  vfl_results.db  empire_events.db  │
└────────────────────────────────────────────────────────────┘
```

## Service Definitions

### 1. Data Ingester (port 8001)
- **Responsibility:** Poll MSport APIs, store raw data
- **Endpoints:** `POST /ingest/season`, `GET /ingest/status`
- **Cron:** Internal scheduler (every 30m)
- **Data written:** `history.db`, `vfl_odds.db`, `vfl_results.db`

### 2. Prediction Engine (port 8002)
- **Responsibility:** Oracle scoring + Local Analyst, produce predictions
- **Endpoints:** `POST /predict`, `GET /predictions/latest`
- **Consumes:** DBs (read-only)
- **Produces:** Signals JSON → Redis pub/sub

### 3. Betting Agent (port 8003)
- **Responsibility:** Filter predictions, Kelly stake calc, output signals
- **Endpoints:** `POST /evaluate`, `GET /signals/latest`
- **Consumes:** Predictions from Prediction Engine
- **Produces:** Betting signals → Discord

### 4. Settlement Service (port 8004)
- **Responsibility:** Settle bets, update bankroll, track P&L
- **Endpoints:** `POST /settle`, `GET /ledger`, `GET /bankroll`
- **Consumes:** Bet ledger, MSport results
- **Produces:** Settlement reports → Discord

## Communication
- **Synchronous:** REST (FastAPI) for request-response
- **Asynchronous:** Redis pub/sub for event-driven flows
- **Shared state:** SQLite DBs (read-only for consumers, write-owned by producer)

## Deployment
Each service runs as:
- Python FastAPI + uvicorn
- Systemd user service for lifecycle management
- Shared Python venv (`~/faith-workspace/vfl-empire/venv/`)
- Environment config via `.env` files
