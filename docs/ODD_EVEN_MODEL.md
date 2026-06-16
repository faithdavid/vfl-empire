# Odd/Even (MSport) — modeling pack

## Market
- **MSport name:** `Odd/Even` in `vfl_prematch_odds`
- **Selections:** `Odd`, `Even` (total goals parity)
- **Label:** `total_goals_odd` = 1 if total goals odd, else 0

## Gold view
`v_results_odd_even_ready` — **816** complete seasons (30×240), left join Odd/Even odds.

```bash
sudo -u postgres psql -d vfl_empire -f scripts/sql/create_odd_even_mart.sql
# GRANT already applied for vfl_user
```

## Export / train
```bash
cd faith-workspace/vfl-empire
.venv/bin/python scripts/export_odd_even_dataset.py
.venv/bin/python scripts/train_odd_even_decision_tree.py --cutoff-vflm 5200
```

Artifacts: `models/odd_even/odd_even_dt.joblib`, `odd_even_metrics.json`, `v_results_odd_even_ready.csv`

## Current walk-forward (honest)
- Train: seasons with `vflm_num < 5200` (rows with odds)
- Test: **5290–5401** (~15.8k fixtures with Odd/Even lines)
- **~49%** accuracy / ROC ~0.50 — parity is hard; **favorite side** (~51.6% acc) still **negative ROI** at posted odds (~-9.5% flat)

**Next levers:** join **O/U 2.5** or **Correct Score** implied totals per `event_id`; team rolling odd-rate; only bet when `|implied_odd_norm - 0.5| > edge threshold`.

## Results layer
Canonical results only (`dedupe_results_canonical.py` already run). Use this view for all Odd/Even work — do not train on pre-dedupe stacks.