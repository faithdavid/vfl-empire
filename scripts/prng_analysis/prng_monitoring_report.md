# Academic RNG Analysis Framework - Consolidated Statistical Report

This report compiles the results of four distinct advanced analytical scripts evaluating virtual football odds distributions.

## 🚨 SYSTEM MONITORS AND DRIFT ALERTS

> [!WARNING]
> **[CRITICAL]** **Entropy Drift in Batch 4**
> Mean Entropy shifted by 1.6362 bits (previous batch standard deviation: 0.0672). This represents a massive change in game uncertainty.

> [!WARNING]
> **[WARNING]** **Distribution Family Shift in Batch 4**
> Fitted distribution family changed from 'Bivariate Poisson' to 'Independent Poisson'. This indicates a potential game engine algorithm swap.

> [!WARNING]
> **[HIGH]** **Phase Space Attractor Shift in Batch 4**
> Largest Lyapunov Exponent flipped sign (from 0.1418 to 0.0000), signifying a structural state transition between chaotic and periodic sequence characteristics.

## 📊 BATCH-BY-BATCH STATISTICAL PROFILES

### Batch 1 (Snapshots 0 to 250)
- **Statistical Fingerprint**:
  - Mean Shannon Entropy: `4.1597` bits (std: `0.0682`)
  - Parametric Family Fit: Best match is **Bivariate Poisson**
  - Bivariate Poisson lambda Home: `1.3311`, Away: `1.1309`, Cov: `0.0803` (KL-Divergence: `0.001514`)
  - NIST SP 800-22 tests (Entropy series): Monobit: `PASS` (p=1.0000) | Runs: `PASS` (p=0.4479) | Spectral: `PASS` (p=0.0295)
- **State-Space Dynamics (Takens' Reconstruction)**:
  - Embedding dimension $m$: `3`, Time delay $\tau$: `1`
  - Correlation Dimension $D_2$: `2.7901`
  - Largest Lyapunov Exponent (LLE): `0.1463`
  - Recurrence Plot: RR = `0.0196%`, DET = `0.0000%`
  - Verdict: *Consistent with High-Dimensional Randomness*
- **Lattice Cryptanalysis (LLL reduction)**:
  - Observed Shortest Basis Vector Norm: `5.9627`
  - Expected Gaussian Heuristic Bound: `5.9270`
  - Hidden Linearity Score: `0.9940`
  - Verdict: *Lattice basis conforms to high-dimensional randomness*
- **Predictive Odds Consistency and Calibration**:
  - Out-of-sample Mean Absolute Error: `0.002887`
  - Multi-class Brier Score: `0.925712` (vs Uniform baseline `0.967742`)
  - Expected Calibration Error (ECE): `0.0000%`
  - Verdict: *Odds Show High Predictive and Calibration Consistency*

---

### Batch 2 (Snapshots 250 to 500)
- **Statistical Fingerprint**:
  - Mean Shannon Entropy: `4.1594` bits (std: `0.0694`)
  - Parametric Family Fit: Best match is **Bivariate Poisson**
  - Bivariate Poisson lambda Home: `1.3315`, Away: `1.1311`, Cov: `0.0799` (KL-Divergence: `0.001508`)
  - NIST SP 800-22 tests (Entropy series): Monobit: `PASS` (p=1.0000) | Runs: `PASS` (p=0.8993) | Spectral: `PASS` (p=0.4682)
- **State-Space Dynamics (Takens' Reconstruction)**:
  - Embedding dimension $m$: `3`, Time delay $\tau$: `1`
  - Correlation Dimension $D_2$: `2.6979`
  - Largest Lyapunov Exponent (LLE): `0.1316`
  - Recurrence Plot: RR = `0.0229%`, DET = `14.2857%`
  - Verdict: *Consistent with High-Dimensional Randomness*
- **Lattice Cryptanalysis (LLL reduction)**:
  - Observed Shortest Basis Vector Norm: `13.6942`
  - Expected Gaussian Heuristic Bound: `5.9270`
  - Hidden Linearity Score: `0.4328`
  - Verdict: *Lattice basis conforms to high-dimensional randomness*
- **Predictive Odds Consistency and Calibration**:
  - Out-of-sample Mean Absolute Error: `0.002871`
  - Multi-class Brier Score: `0.919260` (vs Uniform baseline `0.967742`)
  - Expected Calibration Error (ECE): `0.0000%`
  - Verdict: *Odds Show High Predictive and Calibration Consistency*

---

### Batch 3 (Snapshots 500 to 750)
- **Statistical Fingerprint**:
  - Mean Shannon Entropy: `4.1558` bits (std: `0.0672`)
  - Parametric Family Fit: Best match is **Bivariate Poisson**
  - Bivariate Poisson lambda Home: `1.3171`, Away: `1.1325`, Cov: `0.0819` (KL-Divergence: `0.001650`)
  - NIST SP 800-22 tests (Entropy series): Monobit: `PASS` (p=1.0000) | Runs: `PASS` (p=0.6129) | Spectral: `PASS` (p=0.6634)
- **State-Space Dynamics (Takens' Reconstruction)**:
  - Embedding dimension $m$: `3`, Time delay $\tau$: `1`
  - Correlation Dimension $D_2$: `2.7925`
  - Largest Lyapunov Exponent (LLE): `0.1418`
  - Recurrence Plot: RR = `0.0196%`, DET = `0.0000%`
  - Verdict: *Consistent with High-Dimensional Randomness*
- **Lattice Cryptanalysis (LLL reduction)**:
  - Observed Shortest Basis Vector Norm: `8.0786`
  - Expected Gaussian Heuristic Bound: `5.9270`
  - Hidden Linearity Score: `0.7337`
  - Verdict: *Lattice basis conforms to high-dimensional randomness*
- **Predictive Odds Consistency and Calibration**:
  - Out-of-sample Mean Absolute Error: `0.003052`
  - Multi-class Brier Score: `0.926000` (vs Uniform baseline `0.967742`)
  - Expected Calibration Error (ECE): `0.0000%`
  - Verdict: *Odds Show High Predictive and Calibration Consistency*

---

### Batch 4 (Snapshots 750 to 1000)
- **Statistical Fingerprint**:
  - Mean Shannon Entropy: `2.5196` bits (std: `0.0000`)
  - Parametric Family Fit: Best match is **Independent Poisson**
  - Bivariate Poisson lambda Home: `0.5000`, Away: `0.4000`, Cov: `0.0000` (KL-Divergence: `-0.000000`)
  - NIST SP 800-22 tests (Entropy series): Monobit: `FAIL` (p=0.0000) | Runs: `FAIL` (p=0.0000) | Spectral: `FAIL` (p=0.0023)
- **State-Space Dynamics (Takens' Reconstruction)**:
  - Embedding dimension $m$: `1`, Time delay $\tau$: `1`
  - Correlation Dimension $D_2$: `0.0000`
  - Largest Lyapunov Exponent (LLE): `0.0000`
  - Recurrence Plot: RR = `0.0000%`, DET = `0.0000%`
  - Verdict: *Consistent with High-Dimensional Randomness*
- **Lattice Cryptanalysis (LLL reduction)**:
  - Observed Shortest Basis Vector Norm: `1.4142`
  - Expected Gaussian Heuristic Bound: `5.9270`
  - Hidden Linearity Score: `4.1911`
  - Verdict: *WARNING: Moderate Linear Dependencies Identified*
- **Predictive Odds Consistency and Calibration**:
  - Out-of-sample Mean Absolute Error: `0.000000`
  - Multi-class Brier Score: `0.704690` (vs Uniform baseline `0.967742`)
  - Expected Calibration Error (ECE): `0.7105%`
  - Verdict: *Odds Show High Predictive and Calibration Consistency*

---