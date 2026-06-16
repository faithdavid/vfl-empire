#!/usr/bin/env python3
"""
Stack 240-bit Odd/Even season chains; analyze with math-for-AI/DS canon.

Per season: 30 MD × 8 fixtures = 240 bits (1=odd, 0=even).
Stack: matrix shape (n_seasons, 240) + optional mega-concatenation.

Academy angles:
  - Information / entropy (bits per symbol, max 1.0 for fair coin)
  - Run-length & compression (pattern vs noise)
  - Markov transitions P(0→1), P(1→1) on stacked stream
  - Marginal P(1) per bit index (column) across seasons
  - Autocorrelation at lags 1,8,240 (fixture, MD, season structure)
  - N-gram counts (length 2–8) vs uniform baseline
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "surge-findings"
PLOTS = EMPIRE / "models" / "odd_even" / "plots"
OUT.mkdir(parents=True, exist_ok=True)
PLOTS.mkdir(parents=True, exist_ok=True)


def load_season_matrices():
    sql = """
    SELECT season_name, matchday_number, home_team, total_goals_odd
    FROM v_results_odd_even_ready
    ORDER BY season_name, matchday_number, home_team
    """
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]

    by_sm = defaultdict(list)
    for r in rows:
        by_sm[(r["season_name"], int(r["matchday_number"]))].append(int(r["total_goals_odd"]))

    seasons = []
    matrices = []
    for season in sorted({k[0] for k in by_sm}):
        bits = []
        ok = True
        for md in range(1, 31):
            key = (season, md)
            if key not in by_sm or len(by_sm[key]) != 8:
                ok = False
                break
            bits.extend(by_sm[key])
        if ok and len(bits) == 240:
            seasons.append(season)
            matrices.append(bits)

    X = np.array(matrices, dtype=np.int8)  # (n_seasons, 240)
    return seasons, X


def entropy_binary(p1: float) -> float:
    if p1 <= 0 or p1 >= 1:
        return 0.0
    p0 = 1 - p1
    return -(p0 * math.log2(p0) + p1 * math.log2(p1))


def markov_stream(bits: np.ndarray) -> dict:
    flat = bits.flatten()
    trans = Counter()
    for i in range(len(flat) - 1):
        trans[(int(flat[i]), int(flat[i + 1]))] += 1
    n0 = trans[(0, 0)] + trans[(0, 1)]
    n1 = trans[(1, 0)] + trans[(1, 1)]
    return {
        "p01": trans[(0, 1)] / n0 if n0 else 0,
        "p11": trans[(1, 1)] / n1 if n1 else 0,
        "p00": trans[(0, 0)] / n0 if n0 else 0,
        "p10": trans[(1, 0)] / n1 if n1 else 0,
        "counts": {f"{a}{b}": trans[(a, b)] for a in (0, 1) for b in (0, 1)},
    }


def run_lengths(flat: np.ndarray) -> dict:
    runs = []
    if len(flat) == 0:
        return {"mean": 0, "max": 0, "n_runs": 0}
    cur = flat[0]
    ln = 1
    for b in flat[1:]:
        if b == cur:
            ln += 1
        else:
            runs.append(ln)
            cur = b
            ln = 1
    runs.append(ln)
    return {"mean": float(np.mean(runs)), "max": int(max(runs)), "n_runs": len(runs)}


def autocorr_binary(x: np.ndarray, max_lag: int = 50) -> np.ndarray:
    x = x.astype(float)
    x -= x.mean()
    n = len(x)
    if n < 2 or x.std() == 0:
        return np.zeros(max_lag + 1)
    ac = []
    denom = np.dot(x, x)
    for lag in range(max_lag + 1):
        if lag == 0:
            ac.append(1.0)
        else:
            ac.append(float(np.dot(x[:-lag], x[lag:]) / denom))
    return np.array(ac)


def ngram_surprise(flat: np.ndarray, n: int) -> float:
    """Mean -log2 freq vs uniform 0.5^n baseline (higher = more structured)."""
    if len(flat) < n:
        return 0.0
    grams = Counter()
    for i in range(len(flat) - n + 1):
        key = tuple(int(flat[i + j]) for j in range(n))
        grams[key] += 1
    total = sum(grams.values())
    uniform = 1.0 / (2**n)
    ll = 0.0
    for c in grams.values():
        p = c / total
        ll += -math.log2(p) * c
    ll /= total
    baseline = -math.log2(uniform)
    return baseline - ll  # positive if more compressible than iid


def plot_stack(seasons, X: np.ndarray, col_p1: np.ndarray, ac: np.ndarray):
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Stacked 240-bit seasons (1=odd, 0=even)", fontsize=11)

    # Heatmap: last 80 seasons × 240 (crop if huge)
    show = X[-80:] if len(X) > 80 else X
    axes[0, 0].imshow(show, aspect="auto", cmap="RdYlGn_r", vmin=0, vmax=1, interpolation="nearest")
    axes[0, 0].set_xlabel("Bit index (0..239)")
    axes[0, 0].set_ylabel(f"Season row (last {len(show)})")
    axes[0, 0].set_title("Stack: each row = one season (240 bits)")
    for x in [8, 16, 24, 32, 64, 128, 192, 232]:
        axes[0, 0].axvline(x - 0.5, color="white", alpha=0.15, lw=0.5)

    # P(odd) per bit index across seasons
    axes[0, 1].plot(col_p1, color="steelblue", lw=1)
    axes[0, 1].axhline(0.5, color="gray", ls="--")
    axes[0, 1].set_xlabel("Bit index (fixture slot in season)")
    axes[0, 1].set_ylabel("P(1) across seasons")
    axes[0, 1].set_title("Column marginal (calibration-style)")
    for x in range(0, 240, 8):
        axes[0, 1].axvline(x, color="gray", alpha=0.1)

    # Autocorrelation on mega-stream
    axes[1, 0].stem(range(len(ac)), ac, linefmt="C0-", markerfmt=" ", basefmt=" ")
    axes[1, 0].axhline(0, color="gray")
    axes[1, 0].axvline(8, color="orange", alpha=0.5, label="lag 8 (1 MD)")
    axes[1, 0].axvline(240, color="red", alpha=0.5, label="lag 240 (1 season)")
    axes[1, 0].set_xlim(0, min(80, len(ac) - 1))
    axes[1, 0].set_xlabel("Lag (bits)")
    axes[1, 0].set_title("Autocorrelation (concatenated stack)")
    axes[1, 0].legend(fontsize=8)

    # Histogram column deviation from 0.5
    dev = np.abs(col_p1 - 0.5)
    axes[1, 1].hist(dev, bins=30, color="coral", edgecolor="white")
    axes[1, 1].set_xlabel("|P(1) - 0.5| per bit index")
    axes[1, 1].set_title("How far slots drift from fair coin")

    plt.tight_layout()
    p = PLOTS / "stacked_season_binary_analysis.png"
    fig.savefig(p, dpi=150)
    plt.close()
    return p


def export_mega_stack(seasons, X: np.ndarray):
    lines = []
    lines.append("MEGA_STACK: one line per season, 240 chars, oldest→newest")
    lines.append("SEASON_BOUNDARY= newline")
    for s, row in zip(seasons, X):
        lines.append(f">{s}")
        lines.append("".join(str(int(b)) for b in row))
    mega = "".join("".join(str(int(b)) for b in row) for row in X)
    lines.append("")
    lines.append(f"CONCAT_ALL_SEASONS len={len(mega)}")
    for i in range(0, len(mega), 240):
        chunk = mega[i : i + 240]
        if len(chunk) == 240:
            lines.append(chunk)
    path = OUT / "odd_even_mega_stack.txt"
    path.write_text("\n".join(lines))
    return path, mega


def main():
    seasons, X = load_season_matrices()
    n, d = X.shape
    flat = X.flatten()
    p1_global = float(flat.mean())
    col_p1 = X.mean(axis=0)
    ent_global = entropy_binary(p1_global)
    ent_cols_mean = float(np.mean([entropy_binary(p) for p in col_p1]))

    mk = markov_stream(X)
    rl = run_lengths(flat)
    ac = autocorr_binary(flat, max_lag=80)
    ng2 = ngram_surprise(flat, 2)
    ng8 = ngram_surprise(flat, 8)

    mega_path, mega = export_mega_stack(seasons, X)
    plot_path = plot_stack(seasons, X, col_p1, ac)

    # Top / bottom bit indices by |p-0.5|
    idx = np.argsort(np.abs(col_p1 - 0.5))[::-1]
    top_slots = []
    for i in idx[:15]:
        md = i // 8 + 1
        slot = i % 8 + 1
        top_slots.append({
            "bit_index": int(i),
            "matchday": int(md),
            "fixture_slot": int(slot),
            "p_odd": round(float(col_p1[i]), 4),
        })

    report = {
        "n_seasons_stacked": int(n),
        "bits_per_season": 240,
        "total_bits": int(flat.size),
        "global_p_odd": round(p1_global, 5),
        "entropy_bits_per_symbol_global": round(ent_global, 5),
        "entropy_mean_per_column": round(ent_cols_mean, 5),
        "markov_on_concat_stack": {
            k: round(float(v), 5) for k, v in mk.items() if k != "counts"
        },
        "markov_counts": {k: int(v) for k, v in mk["counts"].items()},
        "run_length": {k: int(v) if isinstance(v, (np.integer, int)) and k == "max" else float(v) if k == "mean" else int(v) for k, v in rl.items()},
        "autocorr_lag1": round(float(ac[1]), 5),
        "autocorr_lag8": round(float(ac[8]), 5) if len(ac) > 8 else None,
        "autocorr_lag240": round(float(ac[240]), 5) if len(ac) > 240 else None,
        "ngram_surprise_2bit": round(ng2, 5),
        "ngram_surprise_8bit": round(ng8, 5),
        "top_biased_slots": top_slots,
        "files": {
            "mega_stack": str(mega_path),
            "plot": str(plot_path),
        },
        "academy_playbook": [
            "Entropy ≈1 and surprise≈0 → treat as iid noise; no edge from bit pattern alone.",
            "Column marginals → per (MD, slot) bias; stack filter for betting.",
            "Markov p01≠p10 → short memory; weak sequential rule at fixture level.",
            "Autocorr spike at lag 8 or 240 → MD/season periodicity (check plot).",
            "Next: HMM on MD-level 8-bit words, or CNN on (seasons×240) heatmap for anomaly seasons.",
        ],
    }
    rpath = OUT / "stacked_season_binary_report.json"
    rpath.write_text(json.dumps(report, indent=2))

    print(f"Seasons stacked: {n} × 240 = {flat.size} bits")
    print(f"Global P(odd)={p1_global:.4f} entropy={ent_global:.4f} (max 1.0)")
    print(f"Markov: P(0→1)={mk['p01']:.4f} P(1→1)={mk['p11']:.4f}")
    print(f"Run length mean={rl['mean']:.2f} max={rl['max']}")
    print(f"Autocorr lag1={ac[1]:.4f} lag8={ac[8]:.4f}")
    print(f"Ngram surprise 2={ng2:.4f} 8={ng8:.4f}")
    print(f"Mega: {mega_path}")
    print(f"Plot: {plot_path}")
    print(f"Report: {rpath}")


if __name__ == "__main__":
    main()