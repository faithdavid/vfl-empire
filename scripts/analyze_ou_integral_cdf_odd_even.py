#!/usr/bin/env python3
"""
Integral view: O/U implied probs are CDF knots on total goals T ∈ {0..7}.

Each line sums to 1 (de-vig Over+Under):
  P(T >= 2) = implied(Over 1.5)
  P(T >= 3) = implied(Over 2.5)
  P(T <= 1) = implied(Under 1.5)
  P(T <= 2) = implied(Under 2.5)

Reconstruct P(T=k) with sum_k P(k) = 1, then P(odd) = P(1)+P(3)+P(5)+P(7).

O1.5 is often very consistent → use as primary anchor; O2.5 refines tail.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "surge-findings"
PLOTS = EMPIRE / "models" / "odd_even" / "plots"


def devig_pair(over_odds, under_odds):
    o, u = float(over_odds), float(under_odds)
    if o <= 1 or u <= 1:
        return None, None
    qo, qu = 1 / o, 1 / u
    s = qo + qu
    return qo / s, qu / s  # p_over, p_under sum to 1


def poisson_pmf(lam, kmax=7):
    pmf = [math.exp(-lam) * lam**k / math.factorial(k) for k in range(kmax + 1)]
    s = sum(pmf)
    return [p / s for p in pmf]


def fit_lambda_o15_o25(p_ge2: float, p_ge3: float) -> float:
    """λ minimizing (P_poisson(T>=2)-p_ge2)^2 + (P_poisson(T>=3)-p_ge3)^2."""

    def tail(lam, k):
        return 1 - sum(math.exp(-lam) * lam**j / math.factorial(j) for j in range(k))

    best_lam, best_err = 2.5, 1e9
    for lam in np.linspace(0.3, 5.5, 200):
        e = (tail(lam, 2) - p_ge2) ** 2 + (tail(lam, 3) - p_ge3) ** 2
        if e < best_err:
            best_err, best_lam = e, lam
    return float(best_lam)


def cdf_knot_reconstruct(p_le1: float, p_le2: float) -> list[float]:
    """
    Pin CDF at integers using Under 1.5 / Under 2.5 (integrals to 1 on split lines).
    F(1) = P(T<=1) = p_le1, F(2) = P(T<=2) = p_le2, then spread 0..7.
    """
    p0 = max(0, 1 - p_le1 - (p_le1 - p_le2))  # rough; refine below
    # Monotone: P0, P1, P2 from knots
    F1 = p_le1
    F2 = p_le2
    # P(T=0) + P(T=1) = F1, P(T=2) = F2 - F1
    # Remaining mass 1-F2 on 3,4,5,6,7 — geometric decay by empirical global shape
    global_shape = np.array([0.074, 0.190, 0.253, 0.220, 0.148, 0.073, 0.035, 0.007])
    global_shape = global_shape / global_shape.sum()
    pmf = np.zeros(8)
    pmf[0] = max(0.01, F1 * 0.35)  # split F1 to 0,1
    pmf[1] = max(0.01, F1 - pmf[0])
    pmf[2] = max(0.01, F2 - F1)
    tail = max(0.01, 1 - F2)
    tail_shape = global_shape[3:] / global_shape[3:].sum()
    pmf[3:8] = tail * tail_shape
    pmf = pmf / pmf.sum()
    return pmf.tolist()


def load_rows():
    sql = """
    WITH ou AS (
        SELECT event_id,
            MAX(CASE WHEN selection_name = 'Over 1.5' THEN odds END) AS o15,
            MAX(CASE WHEN selection_name = 'Under 1.5' THEN odds END) AS u15,
            MAX(CASE WHEN selection_name = 'Over 2.5' THEN odds END) AS o25,
            MAX(CASE WHEN selection_name = 'Under 2.5' THEN odds END) AS u25
        FROM vfl_prematch_odds
        WHERE market_name = 'Over/Under'
        GROUP BY event_id
    )
    SELECT r.total_goals, r.total_goals_odd,
           ou.o15, ou.u15, ou.o25, ou.u25
    FROM v_results_odd_even_ready r
    JOIN ou ON ou.event_id = r.event_id
    WHERE ou.o15 IS NOT NULL AND ou.u15 IS NOT NULL
      AND ou.o25 IS NOT NULL AND ou.u25 IS NOT NULL
    """
    with get_db() as cur:
        cur.execute(sql)
        return [dict(x) for x in cur.fetchall()]


def main():
    rows = load_rows()
    p_o15_list = []
    records = []

    for r in rows:
        po15, pu15 = devig_pair(r["o15"], r["u15"])
        po25, pu25 = devig_pair(r["o25"], r["u25"])
        if po15 is None:
            continue
        p_ge2 = po15
        p_ge3 = po25
        p_le1 = pu15
        p_le2 = pu25

        lam = fit_lambda_o15_o25(p_ge2, p_ge3)
        pmf_pois = poisson_pmf(lam)
        p_odd_pois = sum(pmf_pois[k] for k in (1, 3, 5, 7))

        pmf_cdf = cdf_knot_reconstruct(p_le1, p_le2)
        p_odd_cdf = sum(pmf_cdf[k] for k in (1, 3, 5, 7))

        # O1.5-only anchor: λ from single constraint P(T>=2)=p_ge2
        lam1 = fit_lambda_o15_o25(p_ge2, p_ge2)  # duplicate constraint → use only ge2
        # better: binary search λ for P(T>=2)=p_ge2 only
        lo, hi = 0.1, 8.0
        for _ in range(50):
            mid = (lo + hi) / 2
            t2 = 1 - sum(math.exp(-mid) * mid**j / math.factorial(j) for j in range(2))
            if t2 < p_ge2:
                lo = mid
            else:
                hi = mid
        lam_o15_only = (lo + hi) / 2
        pmf_o15 = poisson_pmf(lam_o15_only)
        p_odd_o15 = sum(pmf_o15[k] for k in (1, 3, 5, 7))

        actual = int(r["total_goals_odd"])
        p_o15_list.append(p_ge2)
        records.append({
            "p_ge2": p_ge2,
            "p_ge3": p_ge3,
            "p_odd_pois": p_odd_pois,
            "p_odd_cdf": p_odd_cdf,
            "p_odd_o15_only": p_odd_o15,
            "actual": actual,
            "total_goals": int(r["total_goals"]),
        })

    n = len(records)
    std_o15 = float(np.std(p_o15_list))
    mean_o15 = float(np.mean(p_o15_list))

    def acc(key, thresh=0.5):
        return np.mean([1 if (r[key] >= thresh) == r["actual"] else 0 for r in records])

    def brier(key):
        return np.mean([(r[key] - r["actual"]) ** 2 for r in records])

    # Calibration bins on p_odd from integral (poisson 2-knot)
    edges = np.linspace(0.35, 0.65, 13)
    cal = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        sub = [r for r in records if lo <= r["p_odd_pois"] < hi]
        if len(sub) < 200:
            continue
        cal.append({
            "bin": f"{lo:.2f}-{hi:.2f}",
            "n": len(sub),
            "pred": np.mean([x["p_odd_pois"] for x in sub]),
            "actual": np.mean([x["actual"] for x in sub]),
        })

    # High-confidence: |p_odd - 0.5| large
    confident = [r for r in records if abs(r["p_odd_pois"] - 0.5) >= 0.08]
    acc_conf = np.mean([1 if (r["p_odd_pois"] >= 0.5) == r["actual"] else 0 for r in confident]) if confident else 0

    # O1.5 narrow band (consistent percentages)
    band = [r for r in records if 0.68 <= r["p_ge2"] <= 0.76]
    acc_band = np.mean([1 if (r["p_odd_pois"] >= 0.5) == r["actual"] else 0 for r in band]) if band else 0
    odd_rate_band = np.mean([r["actual"] for r in band]) if band else 0

    fig, axes = plt.subplots(2, 2, figsize=(11, 9))
    fig.suptitle("Integral to 1: O1.5/O2.5 CDF → P(T) → P(odd)", fontsize=11)

    axes[0, 0].hist(p_o15_list, bins=40, color="steelblue", alpha=0.85)
    axes[0, 0].axvline(mean_o15, color="red", ls="--", label=f"mean={mean_o15:.3f}")
    axes[0, 0].set_title(f"P(Over 1.5) de-vig — std={std_o15:.4f}")
    axes[0, 0].legend()

    if cal:
        axes[0, 1].plot([c["pred"] for c in cal], [c["actual"] for c in cal], "o-")
        axes[0, 1].plot([0, 1], [0, 1], "k--")
        axes[0, 1].set_title("Calibration ∫→P(odd) Poisson 2-knot")

    methods = ["p_odd_o15_only", "p_odd_pois", "p_odd_cdf"]
    accs = [acc(m) for m in methods]
    axes[1, 0].bar(["O1.5 λ only", "O1.5+O2.5 λ", "CDF knots"], accs, color="teal")
    axes[1, 0].axhline(0.5, ls="--", color="gray")
    axes[1, 0].set_ylabel("Accuracy @ 0.5")
    axes[1, 0].set_ylim(0.48, 0.54)

    axes[1, 1].text(0.05, 0.85, f"n={n}\nstd P(O1.5)={std_o15:.4f}", transform=axes[1, 1].transAxes, fontsize=10)
    axes[1, 1].text(0.05, 0.65, f"Acc conf |p-0.5|>=0.08: {acc_conf:.3f} (n={len(confident)})", transform=axes[1, 1].transAxes, fontsize=10)
    axes[1, 1].text(0.05, 0.45, f"O1.5 band 0.68-0.76: acc={acc_band:.3f} odd%={100*odd_rate_band:.1f}% n={len(band)}", transform=axes[1, 1].transAxes, fontsize=10)
    axes[1, 1].axis("off")
    axes[1, 1].set_title("Does tight O1.5 → edge?")

    plt.tight_layout()
    plot = PLOTS / "ou_integral_cdf_odd_even.png"
    fig.savefig(plot, dpi=150)
    plt.close()

    report = {
        "integral_definition": "De-vig Over+Under=1 per line; CDF F(1.5), F(2.5) from Under; PMF on 0..7 sums to 1",
        "n_fixtures": n,
        "p_over15_mean": round(mean_o15, 4),
        "p_over15_std": round(std_o15, 4),
        "accuracy_at_50pct": {
            "o15_lambda_only": round(acc("p_odd_o15_only"), 4),
            "poisson_two_knot_o15_o25": round(acc("p_odd_pois"), 4),
            "cdf_knot_reconstruct": round(acc("p_odd_cdf"), 4),
        },
        "brier_score_lower_better": {
            "poisson_two_knot": round(brier("p_odd_pois"), 4),
            "cdf_knot": round(brier("p_odd_cdf"), 4),
        },
        "high_confidence_abs_p_odd_minus_half_ge_0.08": {
            "n": len(confident),
            "accuracy": round(acc_conf, 4),
        },
        "o15_tight_band_0.68_0.76": {
            "n": len(band),
            "accuracy_using_p_odd_pois": round(acc_band, 4),
            "empirical_odd_rate": round(float(odd_rate_band), 4),
        },
        "calibration_bins_p_odd_pois": cal,
        "verdict": [],
        "plot": str(plot),
    }

    v = []
    v.append(
        "Yes — use integral/CDF: each O/U line is a probability mass partition summing to 1; stack lines to pin P(T=0..7), then odd = sum odd atoms."
    )
    if std_o15 < 0.08:
        v.append(
            f"O1.5 implied is tight (std={std_o15:.3f}) — anchors λ well but does NOT alone imply 100% odd/even; it pins scoring level (~72% have 2+ goals)."
        )
    v.append(
        f"Two-knot Poisson (O1.5+O2.5) acc={acc('p_odd_pois'):.3f}; confident tail acc={acc_conf:.3f} on n={len(confident)}."
    )
    v.append(
        "Path to higher certainty: bet only when reconstructed P(odd) or P(even) exceeds calibrated threshold (e.g. 0.58), not when O1.5 is merely consistent."
    )
    report["verdict"] = v

    (OUT / "ou_integral_cdf_odd_even_report.json").write_text(json.dumps(report, indent=2))

    print(json.dumps({k: report[k] for k in report if k != "calibration_bins_p_odd_pois"}, indent=2))
    for line in v:
        print(" -", line)


if __name__ == "__main__":
    main()