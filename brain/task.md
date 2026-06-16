# AutoBet Placer — Current Tasks

## Active / In Progress

- [x] Harden browser_bet_placer.py against dirty betslip / duplicate placement risk
  - Added robust _clear_betslip_robust() helper with verification
  - Better popup dismissal before placement attempts

- [x] Inject empirical team bias for strong Unders (Aston Villa)
  - Added STRONG_UNDER_TEAMS set
  - Heavy conviction penalty (x0.15) on any Over market involving these teams in the orchestrator
  - Removed Aston Villa from O15_SURE_FIXTURES

- [ ] Implement / improve compounding stake parlay reinvestment rule (end-to-end)
  - Define exact rule with user
  - Implement in orchestrator + ensure placer receives correct stake
  - Audit trail for stake decisions

- [x] Add dedicated Account Monitor (account_monitor.py) using same Playwright CDP session
  - Real-time observation of balance, betslip state, and bad patterns (especially Aston Villa + Over)
  - Auto-creates pause_betting.flag on detection of problems
  - Tested in --once mode (already flagged potential AV + Over visibility)

- [x] Launched + live inspection (2026-05-29 ~02:47-02:50 UTC):
  - Account Monitor launched → immediately triggered on "Aston Villa + Over" visible → created pause flag.
  - Orchestrator respected the flag and did nothing.
  - **Direct Playwright CDP inspection performed**:
    - Connected successfully to the live MSport virtuals page.
    - Current balance: NGN 98.86 (matches placer).
    - Betslip currently empty.
    - "Aston Villa" + "Over" / "Over 1.5" text confirmed visible on the page (in fixture list/market selectors).
    - Placer CLI still fully functional (balance + matchdays commands succeeded cleanly, returned current MDs 28/29).
  - AutoBet Placer is technically working (read + navigation paths are healthy). The monitor is correctly protecting against the known bad pattern.

## Backlog / Future

- [ ] Explicit "already placed for this MD" guard at orchestrator level (stronger dedup)
- [ ] Dry-run / simulation mode for placer
- [ ] More data-driven team bias rules pulled from Postgres (vfl_results_v2 + vfl_bets)

## Recently Completed

- [x] Full project deep dive + DB validation of Aston Villa Under bias (77%+ Under 3.5 confirmed)
- [x] Structured brain/ initialized with overview, tasks, plan, and full understanding summary
- [x] Concrete code changes for duplicate prevention and AV bias (see git diff or search STRONG_UNDER_TEAMS)
- [x] New insight incorporated: Fulham is a strong Under team (recent 50 games avg 2.00 goals, 42% Under 1.5). 
  The ₦10 Over 1.5 parlay on Fulham vs Bournemouth lost as expected. 
  Added "Fulham" to STRONG_UNDER_TEAMS with penalty on Over markets.

**Detailed matchup goal analysis (for prediction engine improvement)**:
- Everton vs Leeds: 1.61 avg goals, 93.3% Under 3.5, 77% Under 2.5, 20.6% NG (one of the strongest under fixtures in the league).
- Fulham vs Leeds: 1.88 avg, 88% U3.5, 71% U2.5, 15% NG.
- Fulham vs Bournemouth: 2.02 avg (328 games), 86% U3.5, 66.5% U2.5, 13.1% NG. Recent form still very low.
- Aston Villa vs Everton: 1.94 avg, 86.8% U3.5.
- Bournemouth vs Leeds: 1.95 avg, 87.5% U3.5.

**Engine improvements implemented (user request #2 + accurate under calculation)**:
- Added `ULTRA_UNDER_PAIRS` set + `get_pair_under_stats()` helper that queries real historical under rates (U1.5/U2.5/U3.5/NG) from the DB for any given matchup.
- O1.5 anchors are now completely blocked on ultra under pairs.
- In `conviction()` scoring (strengthened):
  - Over markets on ultra under pairs get an extremely aggressive penalty (x0.05).
  - When the engine considers Under 2.5 / Under 3.5 / NG on these pairs (with 30+ historical games), it now **recalculates a more accurate EV** using the real historical rate and boosts confidence toward the actual rate (capped at 96).
- This is the core of "calculates the under accurately" — the engine no longer uses generic confidence numbers for these critical matchups; it uses the real data.

The long-running Account Monitor (6+ hours) completed cleanly with stable balance and no bad patterns detected in the final snapshots. Good sign.

---

**Latest cycle (short, intentional)**:
- Orchestrator ran for ~4 seconds and correctly went into "WAITING" mode:
  > "⏳ Waiting for active bet (MD2) to settle..."
- This is the ratchet logic working as designed — it placed the previous ₦10 parlay and is now waiting for settlement before considering new bets.
- No new placement attempted in this cycle.

**Active unsettled bets for MD2** (from DB):
- Several parlays recorded for MD2, including ones with ₦10 stake (matching the successful placement).
- The system is currently in a safe waiting state.

No pause flag is currently active.

The autobet has now done one full monitored placement cycle and is correctly pausing itself until settlement. This is good, controlled behavior.