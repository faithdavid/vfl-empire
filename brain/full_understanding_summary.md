# Full Understanding Summary - VFL Empire & AutoBet Placer (as of user request)

## 1. Project Overview
- Large-scale automated betting intelligence system for MSport Virtual Football (VFLM).
- Multi-service architecture (Ingester, Predictor, Betting, Settlement) with Redis event bus and Postgres persistence.
- Heavy use of historical data analysis, mirroring, clustering, and some LLM/agentic components.
- Output delivered primarily via Hermes CLI to specific Discord forums/channels (predictions, settlements, war room).

## 2. Data & Validation
- Postgres DB (vfl_empire) contains rich results, bets, predictions.
- **Aston Villa Insight Validated**: ~4860 historical matches involving AV, avg 2.43 goals/game, 77.2% Under 3.5, only 22.8% Over 3.5. Recent form similar. Over 1.5 hit rate ~71% but risky in low-variance environment. User's losses on Over 1.5 AV picks are statistically expected.

## 3. AutoBet Placer Role
- `browser_bet_placer.py`: The execution layer. Uses persistent browser session (CDP) to place parlays on the live MSport site.
- Called by `auto_bet_orchestrator.py` (and variants).
- Current weaknesses: Betslip clearing is best-effort, no strong pre-placement slip inspection (risk of accidental duplicate/additional bets if state is dirty), limited team bias awareness at placement time.

## 4. Duplicate Betting Root Causes (Likely)
- Orchestrator is designed to place one high-conviction parlay per run.
- Duplicates most likely from:
  - Multiple concurrent/manual/cron invocations of the orchestrator.
  - Legacy scripts (e.g., place_two_bets.py).
  - Race conditions or incomplete betslip clearing in the placer.

## 5. Aston Villa Specific Problem
- Strong historical Under bias not yet reflected in selection rules.
- O15_SURE_FIXTURES and qualifier logic can still surface Over 1.5 on AV games.

## 6. Actions Taken (Needful)
- Initialized structured `brain/` in the project.
- Hardened `browser_bet_placer.py` with more robust betslip clearing + verification.
- Added `STRONG_UNDER_TEAMS` list + heavy penalty in orchestrator conviction scoring for Over markets involving Aston Villa.
- Removed Aston Villa from O15_SURE_FIXTURES.
- Created project overview, task, plan, and this summary in the brain.

## Recommended Immediate Next Work for "Making AutoBet Placer Start Working"
- Add explicit pre-placement slip inspection + abort/retry in the placer.
- Add idempotency key or "already placed today for this MD" guard at orchestrator level.
- Expand team bias rules (more data-driven from DB).
- Wire the new brain artifacts into daily workflows.
- Test the hardened placer in controlled conditions before live capital.

This gives a solid, shared, evidence-based foundation. The placer can now be iterated on safely with these guardrails in place.