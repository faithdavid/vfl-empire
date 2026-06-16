# VFL Empire & Hermes — System Design Audit & Improvement Plan

*Based on: https://github.com/donnemartin/system-design-primer*

---

## Part 1: VFL Empire — Current Architecture vs Best Practices

### 1.1 The CAP Theorem Problem

**Current:** The Empire is AP (Available + Partition-tolerant) — but betting NEEDS CP (Consistency + Partition-tolerant). We cannot place the same bet twice, and we must know our exact bankroll at all times.

| Component | Current | Should Be | Gap |
|-----------|---------|-----------|-----|
| Bet ledgers | JSON file (no transaction) | RDBMS with ACID transactions | ❌ Critical |
| Bankroll state | JSON file (read-modify-write race) | Atomic counter + WAL | ❌ Critical |
| Prediction cache | JSON file (stale reads) | Redis/TTL with cache-aside | ❌ High |
| Signal files (pipeline) | Filesystem IPC (no ordering) | Message queue with at-least-once delivery | ❌ High |

**Fix:** Introduce a proper database (PostgreSQL) for transactional state. Keep SQLite for read-heavy analytics.

### 1.2 Database Architecture

**Current Anti-Pattern:** 3+ unconnected SQLite files, no replication, no connection pooling, 16 cron jobs all opening fresh connections.

**System Design Primer says:**
- *Master-slave replication* for reads scaling
- *Connection pooling* to reduce overhead
- *Denormalization* for read-heavy query paths

**Recommended Architecture:**

```
┌─────────────────────────────────────────────────────┐
│                  PostgreSQL (Primary)                │
│  ┌─────────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ bet_ledger  │  │ bankroll │  │ predictions    │  │
│  │ (ACID)      │  │ (atomic) │  │ (versioned)    │  │
│  └─────────────┘  └──────────┘  └────────────────┘  │
├─────────────────────────────────────────────────────┤
│              SQLite Replicas (Read-only)             │
│  ┌─────────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ vfl_results │  │ vfl_odds │  │ history (ro)   │  │
│  │ (WAL mode)  │  │ (WAL)    │  │ (WAL)          │  │
│  └─────────────┘  └──────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 1.3 Caching Architecture

**Current:** Zero caching. Every prediction cycle re-computes everything from SQLite.

**System Design Primer says:**
- *Cache-aside*: Application checks cache first, loads from DB on miss
- *Write-through*: Every write goes to cache AND DB
- *TTL-based invalidation* for time-sensitive data (odds)

**Recommended Cache Layers:**

| Layer | Technology | What's Cached | TTL | Pattern |
|-------|-----------|---------------|-----|---------|
| L1 (In-memory) | Python dict | Current matchday events, oracle tiers | 60s | Cache-aside |
| L2 (Shared) | Redis | H2H stats, team profiles, form data | 300s | Cache-aside |
| L3 (CDN) | Surge.sh | Pulse HTML, static assets | 1800s | Push CDN |
| L4 (Browser) | localStorage | Dashboard UI state | Session | Client cache |

### 1.4 Asynchronous Processing

**Current:** Cron-based polling (every 1-30 min). No event-driven triggers.

**System Design Primer says:**
- *Message queues* decouple producers from consumers
- *Task queues* with worker pools for parallel processing
- *Back pressure* when downstream systems are slow

**Recommended Async Pipeline:**

```
MSport API → [Poll Adapter] → Message Queue (Redis Streams / NATS)
                                ├── Season Ingester (worker pool)
                                ├── Feature Store (worker pool)  
                                ├── Predictor (worker pool, 4 instances)
                                ├── Betting Engine (single consumer, ordered)
                                └── Settlement Service (single consumer, ordered)
```

**Why this matters:** 
- VFLM cycles every ~4 minutes. Cron at 1-minute intervals wastes 75% of cycles.
- Event-driven: when MSport publishes new odds, our system reacts instantly.
- Workers scale independently: if prediction is slow, add more predictor workers without touching other services.
- Ordered consumption for betting: bets must be processed in sequence.

### 1.5 Microservices & Service Discovery

**Current:** 4 microservices already exist but run on one machine, no health checks, no discovery.

**System Design Primer says:**
- *Health check endpoints* (`/health`) for every service
- *Service registry* for dynamic discovery
- *Circuit breaker* for downstream failures

**Required additions to existing services:**

```python
# Every service needs:
@app.get('/health')
def health():
    return {
        'status': 'ok',
        'db_connected': db.is_connected(),
        'last_poll': state.last_poll_time,
        'uptime': state.uptime_seconds
    }

@app.get('/metrics')  
def metrics():
    return {
        'requests_total': metrics.requests,
        'avg_latency_ms': metrics.avg_latency,
        'error_rate': metrics.error_rate
    }
```

### 1.6 Availability & Fail-over

**Current:** Single Oracle VM. If it goes down, the Empire stops. No backup.

**System Design Primer says:**
- *Active-passive failover*: standby instance takes over
- *Replication*: data must survive single-instance failure
- *Availability targets*: define SLO (99% = 3.5 days/year downtime → we need 99.9%+ for betting)

**Recommended:**
```
┌──────────────┐     ┌──────────────┐
│  Oracle VM   │────▶│  Backup VM   │
│  (Active)    │     │  (Passive)   │
│              │     │              │
│  PostgreSQL  │────▶│  PostgreSQL  │
│  (Primary)   │     │  (Replica)   │
└──────────────┘     └──────────────┘

WAL streaming to replica. 
Manual or automatic failover (< 60s RTO).
Database snapshots every hour to object storage.
```

### 1.7 Performance vs Scalability

**Current Performance Problem:** The monolithic predictor (`live_scrape_and_predict.py`) takes ~30s to analyze 8 fixtures. A single user (us) doesn't notice, but if we wanted to run 10 parallel seasons, it would fail.

**Current Scalability Problem:** SQLite is fast for 25K rows but starts to struggle at 500K+ concurrent reads from multiple cron jobs.

**Fix:** 
- Profile the predictor: which function is slowest? → Optimize that function (Performance fix)
- Add Redis cache for frequently-accessed data (Scalability fix)
- Parallelize per-fixture analysis with ProcessPoolExecutor (Scalability fix)

---

## Part 2: Hermes Agent — Architecture Improvements

### 2.1 Current State

Hermes runs as a single process with:
- MCP servers as external processes
- SQLite for session storage
- Cron scheduler for job orchestration
- Discord/Telegram/Terminal transport

### 2.2 Key Gaps

| Pattern | Current | Recommended |
|---------|---------|-------------|
| Cache | None | Tool output caching (frequently-used results) |
| Database | Single SQLite | Separate session DB + job state DB + index |
| Async | Cron-based | Event-driven task scheduling |
| Observability | Logs only | Metrics endpoint + structured logging |
| Service Discovery | Static config | Dynamic MCP server registration |

### 2.3 Hermes Recommended Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Hermes Core                         │
├─────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐    │
│  │ LLM     │  │ Tool     │  │ Session          │    │
│  │ Router  │  │ Executor │  │ Manager          │    │
│  └────┬────┘  └────┬─────┘  └────────┬─────────┘    │
│       │            │                 │                │
├───────┴────────────┴─────────────────┴──────────────┤
│                 MCP Bus Layer                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ Filesys  │ │ Browser  │ │ AGY      │ │ Other  │ │
│  │ MCP      │ │ MCP      │ │ MCP      │ │ MCPs   │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ │
├─────────────────────────────────────────────────────┤
│                 Data Layer                           │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │ Session DB   │  │ Job Queue    │  │ Cache     │ │
│  │ (SQLite WAL) │  │ (Redis/NATS) │  │ (Redis)   │ │
│  └──────────────┘  └──────────────┘  └───────────┘ │
├─────────────────────────────────────────────────────┤
│              Transport Layer                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ Telegram │ │ Discord  │ │ Terminal │ │ Web UI │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## Part 3: Implementation Roadmap

### Phase 1 (This Week) — No-Brainer Improvements

| # | Change | Effort | Impact | Pattern |
|---|--------|--------|--------|---------|
| 1 | Switch vfl_results.db to WAL mode | 5 min | ✅ Concurrent reads | Database |
| 2 | Add health endpoints to 4 services | 2h | ✅ Observability | Microservices |
| 3 | Add retry with exponential backoff to MSport client | 1h | ✅ Resilience | Back pressure |
| 4 | Implement cache-aside for H2H queries | 3h | ✅ 10x faster predictions | Caching |
| 5 | Add connection pooling to DB access | 1h | ✅ No more DB contention | Database |

### Phase 2 (Next Week) — Structural Improvements

| # | Change | Effort | Impact | Pattern |
|---|--------|--------|--------|---------|
| 6 | Replace signal files with Redis Streams | 8h | 🎯 No more race conditions | Async/MQ |
| 7 | Add PostgreSQL for betting state | 16h | 🎯 ACID betting transactions | Database |
| 8 | Parallelize per-fixture prediction | 4h | 🎯 4x faster prediction | Performance |
| 9 | Implement circuit breaker on MSport API | 3h | ✅ No cascading failures | Resilience |
| 10 | Add Prometheus metrics to all services | 8h | ✅ Real observability | Monitoring |

### Phase 3 (This Month) — Enterprise Scale

| # | Change | Effort | Impact | Pattern |
|---|--------|--------|--------|---------|
| 11 | Deploy standby VM with WAL replication | 16h | 🏆 No single point of failure | Availability |
| 12 | Implement service registry + DNS-based discovery | 8h | ✅ Dynamic scaling | Service Discovery |
| 13 | Rate limiting with token bucket per API consumer | 4h | ✅ Fair resource usage | Back pressure |
| 14 | Dashboard with real-time metrics (Grafana) | 12h | ✅ Full observability | Monitoring |
| 15 | Auto-scaling worker pool based on queue depth | 8h | ✅ Elastic capacity | Scaling |

---

## Part 4: Data Science Architecture — Finite State Space Integration

The Finite State Space Discovery (34 unique scorelines, converged pairs) enables a new architectural component:

```
Pre-match odds → Pair-Specific Distribution Lookup → 
  ├── 34 × P(scoreline | pair) → 
  ├── Weighted probability for each market
  └── True fair odds = 1 / P(market | pair)

Compare MSport odds vs True fair odds
→ Bet where edge > 0
```

This is a **denormalized lookup table** (system design pattern: precompute once, serve fast). The pair statistics don't change rapidly — they converged at ~150 matches. We compute once, cache forever, update weekly.

