# VFL Empire - Full Project Overview (May 2026)

## High-Level Architecture

**Empire Structure:**
- **Sovereign**: Lord FaithDavid
- **CEO/Orchestrator**: Angela (via Hermes profiles)
- **Core System**: VFL Prediction & Betting Empire for MSport Virtual Football League (VFLM)

**Main Repos / Workspaces:**
- `/home/ubuntu/empire-infra/` - Current production infrastructure, skills, projects, Hermes profiles
- `/home/ubuntu/faith-workspace/vfl-empire/` - Core scripts, services (microservices), placer, orchestrator, historical analysis
- Hermes skills for VFL under `.hermes/skills/vfl*` and empire-infra equivalents

**Microservices Architecture** (from ARCHITECTURE.md):
- Ingester (8001): Data scraping/ingestion from MSport
- Prediction Engine (8002): Signal generation (Poisson, clusters, LLM, etc.)
- Betting Agent (8003): Selection, staking, decisioning (includes AutoBet logic)
- Settlement Service (8004): Results tracking, P&L, bankroll updates

Communication: FastAPI REST + Redis pub/sub + shared Postgres (vfl_empire)

**Discord Delivery** (Hermes-based):
- Primary: `hermes send --to discord:CHANNEL_ID`
- Key channels/forums:
  - vfl-empire
  - vfl-predictions (matchday threads)
  - vfl-settlements
- Notifier: `hermes_notifier.py` + cron wrappers that capture stdout and route via Hermes
- Fallback: Direct Discord webhooks

## AutoBet Placer Subsystem

**Core Files:**
- `scripts/browser_bet_placer.py`: Playwright CDP automation for actual bet placement on MSport site. Handles login/session via existing browser, market selection, parlay building, stake input, popup handling.
- `scripts/auto_bet_orchestrator.py`: High-level engine. Builds parlays from predictions, applies money management (ratchet/compounding), calls the placer via subprocess.
- Supporting: auto_bet_streak_orchestrator.py, pair_betting_rules.py, place_two_bets.py (legacy/test)

**Known Issues (User Reported):**
- Duplicate bets being placed (two bets instead of one).
- Poor performance on Aston Villa matches when selecting Over 1.5 (strong historical Under bias).

**Data Layer:**
- Postgres: vfl_empire (tables: vfl_results_v2, vfl_bets, vfl_predictions, bankroll, matches, vfl_matchdays, vfl_settlements, etc.)
- Strong validation: Aston Villa games avg ~2.43 goals, ~77% Under 3.5.

## Current State of AutoBet Placer

The placer is functional for core markets (1X2, Double Chance, Over/Under with line selection) but needs hardening for production reliability, especially around:
- Betslip state management (clearing, inspection before placement)
- Idempotency / duplicate prevention at placement time
- Error recovery and logging for settlement correlation
- Integration with team-specific biases (e.g., treat Aston Villa as heavy Unders)

## Next Actions for "Making the AutoBet Placer Work"

1. Harden placer against accidental multi-placement.
2. Inject strong Aston Villa Under bias into selection (upstream of placer or in rules).
3. Improve logging/traceability from decision → placement → settlement.
4. Use structured brain artifacts for ongoing work tracking.

---
Generated as part of systematic deep dive requested by user.