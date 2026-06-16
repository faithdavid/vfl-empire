# VFL Empire — AutoBet Placer & Betting System Walkthrough

## Overview

The AutoBet Placer is the execution layer of the VFL Empire betting system. It is responsible for actually placing bets on the MSport Virtuals platform through browser automation.

**Core Components:**
- **Low-level Placer**: `browser_bet_placer.py` (Playwright + CDP automation)
- **High-level Orchestrator**: `auto_bet_orchestrator.py` (decision engine that calls the placer)
- Supporting scripts: `auto_bet_streak_orchestrator.py`, `place_two_bets.py`, etc.

The placer is deliberately kept as a relatively focused browser automation tool that higher-level intelligence can drive.

## Architecture

### browser_bet_placer.py
- Connects to a persistent Chrome instance via Chrome DevTools Protocol (CDP) on `localhost:9222`.
- Uses Playwright for reliable DOM interaction on the MSport virtuals page.
- Main capabilities:
  - Get current balance
  - Discover active Match Days
  - Place single bets and multi-leg parlays (1X2, Double Chance, Over/Under with variable lines)
  - Handle popups, bet slip management, stake input, and confirmation flows
  - Robust error detection (insufficient balance, etc.)

**CLI Interface** (designed for orchestration):
```bash
python browser_bet_placer.py balance
python browser_bet_placer.py matchdays
python browser_bet_placer.py parlay '<json-payload>'
```

The parlay command accepts a JSON structure with `legs`, `stake`, and optional `target_md`.

### Integration with Orchestrator
The `auto_bet_orchestrator.py` builds high-conviction parlays (currently 2-3 legs) based on prediction signals, then calls the browser placer to execute them.

Current money management logic includes:
- Base stake starting at ₦10
- Compounding / reinvestment rules (work in progress)
- Reserve percentages
- Milestone tracking

## Current Status (as of late May 2026)

- The browser placer is functional for the main bet types used in the empire (especially Over/Under and Double Chance parlays).
- Recent work has focused on improving reliability around popups, stake input, and success detection.
- A major ongoing thread is the **compounding stake + parlay reinvestment rule** (always stake floor of current balance after wins, starting from a small base).
- The system is moving toward more autonomous operation with the orchestrator driving placement decisions.

## Key Challenges / Areas of Attention

- Fragility of browser automation against site changes (selectors, popup behavior).
- Precise balance tracking and stake calculation for compounding strategies.
- Handling edge cases in bet slip state (stale selections, multiple tabs, etc.).
- Speed vs reliability tradeoffs when placing multiple parlays per matchday.

## Related Services

- Prediction services feed signals into the orchestrator.
- Settlement / ledger components track results after placement.
- The placer is the critical bridge between "what we want to bet" and "what actually gets placed on MSport".

---

*This document should be updated as the AutoBet Placer evolves.*