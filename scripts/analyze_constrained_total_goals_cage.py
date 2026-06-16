#!/usr/bin/env python3
"""
Full-time TOTAL GOALS live in a tight cage: ~0-7 (rarely higher).

Odd = {1,3,5,7}  |  Even = {0,2,4,6}
Fibonacci sequence {0,1,1,2,3,5,8} overlaps this integer ladder — useful as
combinatorial scaffold (sums, partitions), not as bit indices.

Analyze: empirical PMF, entropy, WC-clash conditioning, scoreline lattice.
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
FIB_SET = [0, 1, 1, 2, 3, 5, 8]  # classic; 8 caps near max total
GOAL_CAP = 7  # user: "never more really"


def load():
    sql = """
    SELECT home_goals, away_goals, total_goals_odd,
           season_name, matchday_number, home_team, away_team
    FROM v_results_odd_even_ready
    WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
    """
    with get_db() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def pmf(rows, key_fn=None):
    c = Counter()
    for r in rows:
        t = int(r["home_goals"]) + int(r["away_goals"])
        if key_fn:
            k = key_fn(r)
            c[(k, t)] += 1
        else:
            c[t] += 1
    return c


def entropy_pmf(counts: dict[int, int]) -> float:
    n = sum(counts.values())
    h = 0.0
    for v in counts.values():
        p = v / n
        if p > 0:
            h -= p * math.log2(p)
    return h


def poisson_pmf(lam, k):
    return math.exp(-lam) * lam**k / math.factorial(k)


def main():
    rows = load()
    n = len(rows)
    totals = [int(r["home_goals"]) + int(r["away_goals"]) for r in rows]
    ct = Counter(totals)
    max_t = max(ct.keys())

    # Cap analysis
    over7 = sum(v for k, v in ct.items() if k > 7)
    in_0_7 = sum(v for k, v in ct.items() if 0 <= k <= 7)

    pmf_0_7 = {k: ct.get(k, 0) for k in range(0, 8)}
    ent = entropy_pmf(pmf_0_7)
    ent_max = math.log2(8)  # uniform on 8 outcomes

    odd_mass = sum(pmf_0_7[k] for k in (1, 3, 5, 7))
    even_mass = sum(pmf_0_7[k] for k in (0, 2, 4, 6))

    # Marginal home/away
    hg = Counter(int(r["home_goals"]) for r in rows)
    ag = Counter(int(r["away_goals"]) for r in rows)

    # Scoreline lattice (h,a) with h+a<=7 dominant
    lattice = Counter((int(r["home_goals"]), int(r["away_goals"])) for r in rows)

    # Fibonacci-adjacent: totals that are Fibonacci numbers
    fib_nums = {0, 1, 2, 3, 5, 8}
    mass_fib_total = sum(ct.get(k, 0) for k in fib_nums if k <= max_t)

    # Truncated Poisson fit on 0-7
    mean_t = np.mean(totals)
    pred = {k: poisson_pmf(mean_t, k) for k in range(0, 15)}
    s = sum(pred.values())
    pred = {k: pred[k] / s for k in pred}

    # Joint as independent Poissons with means lam_h, lam_a
    lam_h = np.mean([int(r["home_goals"]) for r in rows])
    lam_a = np.mean([int(r["away_goals"]) for r in rows])
    joint = np.zeros((8, 8))
    for h in range(8):
        for a in range(8):
            joint[h, a] = poisson_pmf(lam_h, h) * poisson_pmf(lam_a, a)
    joint_p_total = Counter()
    for h in range(8):
        for a in range(8):
            joint_p_total[h + a] += joint[h, a]
    joint_p_total = {k: joint_p_total[k] for k in range(0, 15)}

    # Plot
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle("Constrained full-time goals (0-7 cage)", fontsize=11)

    ks = list(range(0, min(12, max_t + 2)))
    emp = [ct.get(k, 0) / n for k in ks]
    axes[0, 0].bar(ks, emp, color="steelblue", label="empirical")
    axes[0, 0].plot(ks, [pred.get(k, 0) for k in ks], "o--", color="orange", label=f"Poisson(λ={mean_t:.2f})")
    axes[0, 0].axvline(7.5, color="red", ls=":", label="cap ~7")
    axes[0, 0].set_xlabel("Total goals")
    axes[0, 0].legend()
    axes[0, 0].set_title(f"PMF totals (>{7}: {100*over7/n:.2f}%)")

    # Odd/even partition of totals
    labels = ["0", "1", "2", "3", "4", "5", "6", "7"]
    colors = ["#4a9" if k % 2 == 0 else "#d45" for k in range(8)]
    axes[0, 1].bar(labels, [pmf_0_7[k] / n for k in range(8)], color=colors)
    axes[0, 1].set_title(f"Even vs odd totals | P(odd)={odd_mass/n:.3f}")
    axes[0, 1].set_ylabel("P(total)")

    # Home vs away marginals 0-6
    xr = range(0, 7)
    axes[1, 0].bar([x - 0.15 for x in xr], [hg.get(x, 0) / n for x in xr], width=0.3, label="home")
    axes[1, 0].bar([x + 0.15 for x in xr], [ag.get(x, 0) / n for x in xr], width=0.3, label="away")
    axes[1, 0].set_title(f"Marginals λh={lam_h:.2f} λa={lam_a:.2f}")
    axes[1, 0].legend()

    # Heatmap scorelines h+a common
    mat = np.zeros((7, 7))
    for (h, a), c in lattice.items():
        if h < 7 and a < 7:
            mat[h, a] = c
    mat = mat / n
    im = axes[1, 1].imshow(mat, origin="lower", cmap="YlOrRd", aspect="auto")
    axes[1, 1].set_xlabel("Away goals")
    axes[1, 1].set_ylabel("Home goals")
    axes[1, 1].set_title("P(h,a) empirical (0-6)")
    plt.colorbar(im, ax=axes[1, 1], fraction=0.046)

    plt.tight_layout()
    plot_p = PLOTS / "constrained_total_goals_cage.png"
    fig.savefig(plot_p, dpi=150)
    plt.close()

    # Crack-it math roadmap
    roadmap = {
        "state_space": "T ∈ {0,1,2,3,4,5,6,7} (≈99%+ mass); scoreline (H,A) with H,A ∈ {0..6} mostly",
        "odd_even": "Odd ⇔ T∈{1,3,5,7}; Even ⇔ T∈{0,2,4,6} — partition of ℤ₈",
        "entropy_bits": round(ent, 4),
        "entropy_max_uniform_8": round(ent_max, 4),
        "fibonacci_link": (
            f"Totals in Fibonacci set {{0,1,2,3,5,8}} carry {100 * mass_fib_total / n:.1f}% mass; "
            "4,6,7 are non-Fib — Zeckendorf-code T as features"
        ),
        "models_that_fit_cage": [
            "Independent Poisson(λh)×Poisson(λa) truncated to grid — 2 params + truncate",
            "Skellam / difference distribution for spread markets",
            "Categorical T~Cat(8) with WC-clash logits — 8-way softmax (DS)",
            "Bradley-Terry sets λh,λa per team; sum T=H+A",
            "Fibonacci: partition function on compositions H+A=T with bounded parts — exact counting",
        ],
        "calibration": "Compare empirical P(T|clash) to Poisson product; KL per clash",
    }

    report = {
        "n_fixtures": n,
        "pct_total_le_7": round(100 * in_0_7 / n, 3),
        "pct_total_gt_7": round(100 * over7 / n, 3),
        "mean_total_goals": round(mean_t, 4),
        "p_odd_from_totals": round(odd_mass / n, 5),
        "pmf_total_0_7": {str(k): round(pmf_0_7[k] / n, 5) for k in range(8)},
        "entropy_total_distribution": round(ent, 5),
        "independent_poisson_predicted_total": {str(k): round(joint_p_total.get(k, 0), 5) for k in range(9)},
        "roadmap": roadmap,
        "plot": str(plot_p),
    }
    (OUT / "constrained_goals_fibonacci_cage_report.json").write_text(json.dumps(report, indent=2))

    lines = [
        "# Full-time goals: constrained cage 0-7 (your Fibonacci / discrete math frame)",
        f"N={n}  mean total={mean_t:.3f}  P(odd)={odd_mass/n:.4f}",
        f"Mass on 0-7: {100*in_0_7/n:.2f}%   >7: {100*over7/n:.2f}%",
        "",
        "PMF total goals:",
    ]
    for k in range(8):
        lines.append(f"  T={k}: {100*pmf_0_7[k]/n:.2f}%  {'ODD' if k%2 else 'EVEN'}")
    lines.extend([
        "",
        f"Entropy H(T)={ent:.3f} bits (max log2(8)={ent_max:.3f})",
        "",
        "Odd/even is a PARTITION of this 8-state space — crack T first, odd follows.",
        "Fibonacci: use as integer scaffold {0,1,2,3,5,8} for compositions H+A=T, not bit positions.",
        "",
        "Next: P(T|WC clash) 8-way model + compare to Poisson(λh)Poisson(λa).",
    ])
    (OUT / "constrained_goals_fibonacci_cage.txt").write_text("\n".join(lines))

    print("\n".join(lines))
    print(f"Plot: {plot_p}")


if __name__ == "__main__":
    main()