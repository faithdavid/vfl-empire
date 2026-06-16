#!/usr/bin/env python3
"""
Read stacked 240-bit seasons through a Fibonacci lens (full-time odd/even).

Angles:
  1) Bit at Fibonacci indices (1,2,3,5,8,13,21,34,55,89,144,233) mod season length
  2) Golden split: first φ·240 vs rest — odd density
  3) Fibonacci recurrence on per-MD odd *counts* (0-8), not bits
  4) Zeckendorf: decompose MD odd-counts; compare to uniform
  5) WC stack + alpha stack both
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
from common.weight_class_fixture_order import replay_season_bits_wc  # noqa: E402

OUT = EMPIRE / "surge-findings"
PLOTS = EMPIRE / "models" / "odd_even" / "plots"
PHI = (1 + math.sqrt(5)) / 2

FIBS = []
a, b = 1, 1
while b <= 240:
    FIBS.append(b)
    a, b = b, a + b
# 1,2,3,5,8,13,21,34,55,89,144,233 — 0-indexed positions use fib-1 for bit index


def fib_indices_0based(max_i: int = 240) -> list[int]:
    """0-based bit indices < max_i that are Fibonacci numbers."""
    out = []
    a, b = 1, 1
    while a <= max_i:
        if a <= max_i:
            out.append(a - 1)  # fib 1 -> index 0
        a, b = b, a + b
    return sorted(set(out))


def load_alpha_matrix():
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
    seasons, mats = [], []
    for season in sorted({k[0] for k in by_sm}):
        bits = []
        ok = True
        for md in range(1, 31):
            key = (season, md)
            if key not in by_sm or len(by_sm[key]) != 8:
                ok = False
                break
            bits.extend(by_sm[key])
        if ok:
            seasons.append(season)
            mats.append(bits)
    return seasons, np.array(mats, dtype=np.int8)


def load_wc_matrix():
    sql = """
    SELECT season_name, matchday_number, home_team, away_team,
           home_goals, away_goals, total_goals_odd
    FROM v_results_odd_even_ready
    """
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
    by_season = defaultdict(list)
    for r in rows:
        by_season[r["season_name"]].append(r)
    seasons, mats = [], []
    for season in sorted(by_season.keys()):
        bits = replay_season_bits_wc(by_season[season])
        if bits:
            seasons.append(season)
            mats.append(bits)
    return seasons, np.array(mats, dtype=np.int8)


def analyze_fib_positions(X: np.ndarray, label: str) -> dict:
    fib_idx = fib_indices_0based(240)
    non_fib = [i for i in range(240) if i not in fib_idx]
    flat_fib = X[:, fib_idx].flatten()
    flat_non = X[:, non_fib].flatten()
    flat_all = X.flatten()

    # Golden section split on linear season read
    cut = int(240 / PHI)  # ~148
    part_a = X[:, :cut].flatten()
    part_b = X[:, cut:].flatten()

    return {
        "label": label,
        "fib_indices_1based": [i + 1 for i in fib_idx],
        "n_fib_positions": len(fib_idx),
        "p_odd_at_fib_positions": round(float(flat_fib.mean()), 5),
        "p_odd_at_non_fib": round(float(flat_non.mean()), 5),
        "delta_fib_minus_non_pp": round((float(flat_fib.mean()) - float(flat_non.mean())) * 100, 3),
        "golden_split_index": cut,
        "p_odd_first_phi_segment": round(float(part_a.mean()), 5),
        "p_odd_rest_segment": round(float(part_b.mean()), 5),
        "delta_golden_pp": round((float(part_a.mean()) - float(part_b.mean())) * 100, 3),
        "global_p_odd": round(float(flat_all.mean()), 5),
    }


def md_odd_counts(X: np.ndarray) -> np.ndarray:
    """Per season per MD: count of odd fixtures (0-8). Shape (n, 30)."""
    n = X.shape[0]
    counts = np.zeros((n, 30), dtype=np.int8)
    for md in range(30):
        counts[:, md] = X[:, md * 8 : (md + 1) * 8].sum(axis=1)
    return counts


def fib_recurrence_residual(counts: np.ndarray) -> dict:
    """
    For each season, MD t: residual = count[t] - (count[t-1] + count[t-2]) for t>=2.
    If 'Fibonacci-like', residuals small / structured.
    """
    res = []
    for row in counts:
        for t in range(2, 30):
            res.append(int(row[t]) - int(row[t - 1]) - int(row[t - 2]))
    c = Counter(res)
    return {
        "residual_counts": dict(sorted(c.items())),
        "mean_abs_residual": round(float(np.mean(np.abs(res))), 4),
        "pct_residual_zero": round(100 * c[0] / len(res), 2),
    }


def zeckendorf_digit_dist(counts_flat: np.ndarray) -> dict:
    """Zeckendorf representation of each MD odd-count (0-8); digit frequency."""
    fibs = [1, 2, 3, 5, 8]
    digit_ct = Counter()

    def zeck(n):
        if n <= 0:
            return []
        for f in reversed(fibs):
            if f <= n:
                return [f] + zeck(n - f)
        return []

    for c in counts_flat:
        z = zeck(int(c))
        for d in z:
            digit_ct[d] += 1
        if not z:
            digit_ct[0] += 1
    return dict(digit_ct)


def lucas_fib_walk_bits(row: np.ndarray) -> str:
    """Walk 240 bits using step sizes cycling Fibonacci (mod 240), collect visited."""
    steps = [1, 1, 2, 3, 5, 8, 13, 21]
    pos = 0
    visited = []
    seen = set()
    for _ in range(240):
        if pos in seen:
            break
        seen.add(pos)
        visited.append(int(row[pos]))
        step = steps[len(visited) % len(steps)]
        pos = (pos + step) % 240
    return "".join(str(b) for b in visited)


def plot_fib(X, fib_idx, report_alpha, report_wc):
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle("Fibonacci read on full-time odd/even (1=odd)", fontsize=11)

    col = X.mean(axis=0)
    axes[0, 0].plot(col, color="steelblue", lw=1)
    for i in fib_idx:
        axes[0, 0].axvline(i, color="gold", alpha=0.5, lw=0.8)
    axes[0, 0].set_title("P(odd) per bit index (gold=Fib positions)")
    axes[0, 0].set_xlabel("WC slot index 0..239")

    cut = int(240 / PHI)
    axes[0, 1].bar(["[0,φ)", "[φ,240)"], [
        report_wc["p_odd_first_phi_segment"],
        report_wc["p_odd_rest_segment"],
    ], color=["goldenrod", "gray"])
    axes[0, 1].axhline(0.5, ls="--")
    axes[0, 1].set_ylabel("P(odd)")
    axes[0, 1].set_title(f"Golden split at index {cut}")

    counts = md_odd_counts(X)
    axes[1, 0].hist(counts.flatten(), bins=range(0, 10), align="left", color="teal", rwidth=0.8)
    axes[1, 0].set_title("Per-MD count of odd fixtures (0-8)")
    axes[1, 0].set_xlabel("odd count")

    fib_p = [col[i] for i in fib_idx]
    axes[1, 1].stem([i + 1 for i in fib_idx], fib_p, linefmt="gold", markerfmt="o")
    axes[1, 1].axhline(0.5, ls="--", color="gray")
    axes[1, 1].set_title("P(odd) only at Fibonacci indices (1-based)")
    axes[1, 1].set_xlabel("Fib index position in season")

    plt.tight_layout()
    p = PLOTS / "fibonacci_read_odd_even.png"
    fig.savefig(p, dpi=150)
    plt.close()
    return p


def main():
    _, Xa = load_alpha_matrix()
    seasons, Xw = load_wc_matrix()
    fib_idx = fib_indices_0based(240)

    ra = analyze_fib_positions(Xa, "alpha_home_sort")
    rw = analyze_fib_positions(Xw, "wc_top8_clash")

    counts_w = md_odd_counts(Xw)
    rec = fib_recurrence_residual(counts_w)
    zeck = zeckendorf_digit_dist(counts_w.flatten())

    # Fib walk on last season
    walk = lucas_fib_walk_bits(Xw[-1]) if len(Xw) else ""
    walk_p_odd = walk.count("1") / len(walk) if walk else 0

    plot_path = plot_fib(Xw, fib_idx, ra, rw)

    lines = [
        "# Fibonacci read — full-time odd/even binary",
        f"Fibonacci 1-based positions in 240-bit season: {ra['fib_indices_1based']}",
        "",
        "## Position sampling",
        f"WC: P(odd) AT fib positions = {rw['p_odd_at_fib_positions']}",
        f"WC: P(odd) at other positions = {rw['p_odd_at_non_fib']}",
        f"Delta (fib - non) = {rw['delta_fib_minus_non_pp']} pp",
        "",
        "## Golden ratio φ split (linear read)",
        f"First {rw['golden_split_index']} bits (≈240/φ): P(odd)={rw['p_odd_first_phi_segment']}",
        f"Remainder: P(odd)={rw['p_odd_rest_segment']}",
        f"Delta pp = {rw['delta_golden_pp']}",
        "",
        "## Fibonacci on MD *counts* (not bits)",
        f"count[MD_t] - count[t-1] - count[t-2]: {rec['pct_residual_zero']}% exactly zero",
        f"mean |residual| = {rec['mean_abs_residual']}",
        f"residual histogram (top): {dict(list(rec['residual_counts'].items())[:8])}",
        "",
        "## Fibonacci walk (last season)",
        f"Season {seasons[-1] if seasons else 'n/a'}: walk len={len(walk)} P(odd)={walk_p_odd:.4f}",
        f"First 64 walk bits: {walk[:64]}",
        "",
        "Interpretation: if Fib were structural, fib positions or φ-split would deviate >>2pp from 50%.",
    ]
    (OUT / "fibonacci_read_odd_even.txt").write_text("\n".join(lines))

    report = {
        "phi": round(PHI, 6),
        "fib_positions_1based": ra["fib_indices_1based"],
        "alpha_order": ra,
        "wc_order": rw,
        "md_odd_count_fib_recurrence": rec,
        "zeckendorf_digit_usage_on_counts_0_8": zeck,
        "fib_walk_last_season": {
            "season": seasons[-1] if seasons else None,
            "length": len(walk),
            "p_odd": round(walk_p_odd, 5),
            "bitstring_prefix": walk[:120],
        },
        "academy_note": (
            "Fibonacci is a fixed index set (low Kolmogorov complexity); "
            "test is whether P(odd) at those indices differs from marginal. "
            "MD-count recurrence tests if slate parity follows additive memory — "
            "expect ~high residual variance if iid."
        ),
        "plot": str(plot_path),
    }
    (OUT / "fibonacci_read_odd_even_report.json").write_text(json.dumps(report, indent=2))

    print("\n".join(lines[-12:]))
    print(f"Report: {OUT / 'fibonacci_read_odd_even_report.json'}")


if __name__ == "__main__":
    main()