# Odd/Even — theory, tiers, and execution plan

## Proven mathematical frames (map to VFL)

| Framework | What it predicts | VFL hook |
|-----------|------------------|----------|
| **Poisson / Skellam** | Distribution of **total goals**; P(Odd) = Σ P(H=i)P(A=j) over i+j odd | Team **λ** from history; tier clash shifts λ_h, λ_a |
| **Bradley–Terry / Elo** | Win prob from strength gap | Tier **T1–T4** = weight class; gap → more blowouts → different total-goal mix |
| **Dixon–Coles** | Low-score correlation (0–0, 1–1) | VFL **34 scorelines** — parity couples 0,2,4… vs 1,3,5… |
| **Binomial / hypergeometric** | Rare for football; parity is **not** i.i.d. coin | Use only after **conditioning** on λ_total |
| **Book implied + Shin / devig** | Fair P(Odd) vs posted Odd/Even | Compare model P(Odd) to `1/odd_odds` after vig removal |
| **Entropy / cluster fingerprints** | Joint market compression (GG, O2.5, CS) | `odds_cluster_classifier` archetypes → conditional odd-rate |

**Canon:** walk-forward, calibration before ROI claims (`vfl-math-ml-crosswalk`).

## Weight class & tier clash (Empire stack)

1. **Static innate classes** — `TEAM_TIERS` in `vfl_oracle_collector.py` (6×T1, 4×T2, 4×T3, 2×T4).  
2. **Dynamic X-2 tiers** — `truth-bot/vfl_automated_truth_bot.py`: standings at **MD−2** → T1–T4 (4 teams each).  
3. **Historical weight classes** — `vfl-truth-engine/scripts/team_weight_classes.py` (Heavyweight … Featherweight).  
4. **Odds DNA clusters** — `recalibrate_odds_clusters.py` / classifier: **script** implied by MSport joint odds.

**Clash hypothesis:** same weight class (gap=0) vs **cross-class** (gap 1–3) changes **total-goals parity** if blowouts skew even totals (2,4,6) vs odd (1,3,5).

Run: `scripts/analyze_odd_even_theory_tiers.py` → heatmap, gap bar, Poisson calibration.

## Recommended pipeline (best way forward)

```
Canonical results (v_results_odd_even_ready)
    → tier labels (static + optional X-2 replay per season/MD)
    → team λ_h, λ_a (rolling or season-to-date, walk-forward)
    → Poisson P(Odd) + tier-gap residual features
    → join prematch Odd/Even + O/U 2.5 + cluster ID on event_id
    → devig book → edge = model_p − fair_p
    → bet if edge > τ (backtest τ on holdout seasons only)
```

**Phase A (now):** empirical clash matrix + Poisson calibration (script above).  
**Phase B:** replay **X-2 tiers** on historical seasons (points table through MD−2).  
**Phase C:** add **cluster-conditioned** odd-rate table from `classify_match`.  
**Phase D:** simple **logistic** or **shallow tree** on `[poisson_p_odd, tier_gap, cluster, implied_odd_norm]` — not raw parity.

## What not to do

- Bet MD8 “more Even” from ~2 pp noise.  
- Deep trees on 22k odds rows without tier/cluster structure.  
- Random K-fold — use **VFLM chronological** split only.

## Artifacts

- `models/odd_even/plots/odd_pct_tier_clash_heatmap.png`  
- `models/odd_even/plots/odd_pct_by_tier_gap.png`  
- `models/odd_even/plots/poisson_odd_calibration.png`  
- `models/odd_even/tier_clash_odd_even_summary.json`  
- `models/odd_even/clash_type_odd_rates.csv`