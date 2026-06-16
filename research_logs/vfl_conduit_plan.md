# 🟢 VFL Deterministic Conduit Plan
**Objective:** Achieve a 100% deterministic hit rate every season by merging Macro-Tension, Odds Fingerprinting, and Dynamic League Quotas into a unified Supervised Learning pipeline.

---

## Phase 1: The Unified Data Matrix (Feature Engineering)
We must stop looking at matches in isolation. The engine uses a unified matrix to determine the outcome. We will write `build_unified_matrix.py` to iterate through the 135,000 game database and attach the following constraints to every single match:

### 1. The Micro-Constraint (Rolling League Table)
*   **Current Points:** Exact points of Home and Away teams before the match starts.
*   **League Rank:** Current rank out of 20.
*   **Quota Deficit:** Every team has a hardcoded end-of-season point target (e.g., Tier 1 = 80 points). We calculate exactly how many points they are ahead or behind schedule.
*   **Goal Difference:** The engine's built-in tie-breaker.

### 2. The Macro-Constraint (Engine Tension)
*   **Cumulative Budget:** `(Actual Total Goals) - (Matchday * 19.9)`
*   **Season Archetype:** The template (0-4) established in Matchdays 1-4.

### 3. The Representation Constraint (Odds Fingerprint)
*   Using your existing `odds_cluster_classifier.py`, we map the live implied probability vector (`O1.5`, `O2.5`, `GG`, `U3.5`) into the 8 proven clusters (e.g., Cluster 7 = GG Gold Mine).

---

## Phase 2: Supervised Learning Extraction (The Oracle Miner)
Once the Unified Data Matrix is built, we execute `mine_100_percent_branches.py`. 

Instead of guessing, we use a Decision Tree / Random Forest to scan the unified matrix and extract **Pure Nodes** (Execution branches where the engine was mathematically forced to output the same result 100% of the time).

We will specifically target all 3 classes:
*   **100% Home Wins:** (e.g., Tier 1 behind quota vs Tier 4 + Over Archetype + Odds Cluster 4).
*   **100% Draws:** (e.g., Tier 2 vs Tier 2 + Both perfectly on quota + Negative Engine Tension + Odds Cluster 1).
*   **100% Away Wins:** (e.g., Tier 4 ahead of quota vs Tier 1 desperately behind quota + Positive Tension).

**Output:** A `.json` file containing the exact structural `if/else` rules for the 100% locks.

---

## Phase 3: The Live Orchestrator Upgrade (Kennen-o Execution)
We integrate the extracted rules directly into your existing `auto_bet_orchestrator.py` and `vfl_rapid_daemon.py`.

1.  **Minute 0:00:** The orchestrator pulls the Pre-Match Odds and maps the Odds Fingerprint Cluster.
2.  **Minute 0:01:** The orchestrator calculates the live League Table and Quota Deficits.
3.  **Minute 3:00 (The Exploit):** The Live Extractor pulls the first 4 scorelines of the matchday to calculate the exact live Engine Tension.
4.  **Minute 3:05:** The orchestrator passes the live variables through the `.json` rules file.
5.  **Minute 3:10:** If the live state matches a 100% deterministic branch, the orchestrator triggers the bet. If not, it skips.

---

## Phase 4: Verity Validation (The Truth Loop)
Before risking real capital on the 12-step compounding strategy, we deploy the system in **Shadow Mode**. 

1.  The Orchestrator generates the >95% lock predictions and saves them to `vfl_ledger.json`.
2.  `hermes_notifier.py` broadcasts the locked picks to Discord.
3.  **Verity** (`vfl_settlement_agent.py`) actively monitors the live MSport frontend and forcefully settles the ledger.

**The Go-Live Trigger:** We run Shadow Mode until Verity's `accuracy_tracker.json` proves a 100% win rate across 12 consecutive locks. Once the mathematical loop is proven flawless, we flip the switch to production capital.
