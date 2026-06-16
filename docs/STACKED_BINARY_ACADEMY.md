# Stacked 240-bit seasons — AI Academy playbook

## Object
Each complete season = **240 bits** (30 MD × 8 fixtures). Stack **N** seasons → matrix **(N, 240)** and optional **mega-string** length **240×N**.

## Canon mapping (math-for-AI / DS)

| Tool | What it tells you | VFL Odd/Even use |
|------|-------------------|------------------|
| **Shannon entropy** H(p) | Randomness of symbols | Global H≈1 ⇒ no simple code; don't chase "patterns" in noise |
| **Column P(1)** | 240 marginal calibrations | Slot (MD, fixture#) bias — same as parity by index |
| **Markov chain** | P(next bit \| prev) | Fixture-to-fixture memory; compare to 0.5 |
| **Run lengths** | Streaks of 0/1 | Long runs vs geometric expectation under iid |
| **Autocorrelation** | Periodicity at lag 8, 240 | MD boundary / season boundary structure |
| **N-gram surprise** | Compression vs iid | High surprise ⇒ repeated motifs (rare at 8-bit MD word) |

## Scripts & outputs
- `scripts/analyze_stacked_season_binary.py` — metrics + plot
- `surge-findings/odd_even_mega_stack.txt` — `>VFLM ####` + 240 chars per line
- `surge-findings/stacked_season_binary_report.json` — numbers
- `models/odd_even/plots/stacked_season_binary_analysis.png` — heatmap + marginals + ACF

## Sensible next models (Academy phase-up)
1. **MD as token**: 2^8=256 MD-types; season = 30-token sequence → n-gram / Markov on MD-words (not bits).
2. **Logistic on lag features**: prev bit, prev MD parity, column index.
3. **Calibration plot**: predicted P(odd) from Poisson vs column empirical.
4. **Anomaly detection**: row-wise distance from mean column vector (which seasons look unlike stack).

## Do not
- Train deep nets on mega-string without walk-forward (leakage across seasons).
- Claim edge from autocorr noise at single lag without multiple-testing control.