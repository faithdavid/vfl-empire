# AutoBet Placer — Implementation Plan (Compounding & Reliability Focus)

## Objective

Improve the AutoBet Placer (primarily `browser_bet_placer.py` and its callers in the orchestrator) to support a robust, compounding stake strategy while increasing placement reliability.

## Current State

- The placer can successfully place 2-3 leg parlays using 1X2, Double Chance, and Over/Under markets.
- It uses Playwright connected over CDP to a user-controlled Chrome session.
- Basic money management exists in the orchestrator, but the full "always reinvest floor of balance" compounding loop is not yet cleanly implemented end-to-end.

## Proposed Approach

### Phase 1: Clarify & Stabilize the Compounding Rule
1. Define the exact mathematical rule (user to confirm):
   - Stake = floor(current active bankroll) ?
   - Or floor(available balance after reserve)?
   - Handling of losses (reset to base or continue)?
2. Implement the rule in the orchestrator + ensure the placer receives the correct stake.
3. Add clear logging of "Intended stake vs Actual stake used".

### Phase 2: Reliability Hardening of the Placer
- Systematic review of failure modes from recent runs.
- Improve popup dismissal logic (more selectors + force clicks + retry).
- Better bet slip state management (clearing, tab selection, multiple attempts).
- More defensive balance reading before and after placement.

### Phase 3: Better Observability & Contracts
- Structured return values from the placer (including post-bet balance).
- Optional dry-run mode.
- Integration tests or simulation mode against recorded page states (if feasible).

## Risks

- Site DOM changes breaking selectors.
- Timing/race conditions during high-traffic matchdays.
- Balance drift between what the system thinks it has vs reality.

## Verification

- Successful placement of multiple parlays with the new compounding rule on a live or test matchday.
- Clear audit trail in logs showing stake decisions.
- Reduced rate of "placement failed" errors that are actually recoverable UI issues.

## Open Questions for User

- Exact compounding formula you want right now?
- Any specific failure cases you've seen recently with the current placer?
- Should the placer itself become "smarter" about stake sizing, or should all intelligence stay in the orchestrator?

---

Update this plan as decisions are made.