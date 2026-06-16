#!/usr/bin/env python3
"""
O/U 1.5 and 2.5 prematch odds (Over + Under) → full-time odd/even.

Uses implied P(Over 1.5), P(Under 1.5), P(Over 2.5), P(Under 2.5) from odds only.
Fixture + every matchday (8 fixtures).
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "surge-findings"
PLOTS = EMPIRE / "models" / "odd_even" / "plots"


def implied_prob(over_odds, under_odds):
    o, u = float(over_odds), float(under_odds)
    if o <= 1 or u <= 1:
        return None
    qo, qu = 1 / o, 1 / u
    return qo / (qo + qu)


def poisson_odd_from_p25(p25: float) -> float:
    """Secondary: λ from O2.5 only, P(odd) on 0-7 cage."""
    def p_ge3(lam):
        return 1 - sum(math.exp(-lam) * lam**k / math.factorial(k) for k in range(3))

    lo, hi = 0.1, 8.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if p_ge3(mid) < p25:
            lo = mid
        else:
            hi = mid
    lam = (lo + hi) / 2
    p_odd = sum(math.exp(-lam) * lam**k / math.factorial(k) for k in (1, 3, 5, 7))
    p_even = sum(math.exp(-lam) * lam**k / math.factorial(k) for k in (0, 2, 4, 6))
    return p_odd / (p_odd + p_even) if (p_odd + p_even) > 0 else 0.5


def load_fixture_ou():
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
    SELECT r.season_name, r.matchday_number, r.event_id,
           r.total_goals, r.total_goals_odd,
           r.odd_odds, r.even_odds,
           ou.o15, ou.u15, ou.o25, ou.u25
    FROM v_results_odd_even_ready r
    JOIN ou ON ou.event_id = r.event_id
    WHERE ou.o15 IS NOT NULL AND ou.u15 IS NOT NULL
      AND ou.o25 IS NOT NULL AND ou.u25 IS NOT NULL
    """
    with get_db() as cur:
        cur.execute(sql)
        return [dict(x) for x in cur.fetchall()]


def bin_curve(fixture, key, edges):
    centers, rates, ns = [], [], []
    vals = [f[key] for f in fixture]
    odd = [f["actual_odd"] for f in fixture]
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        idx = [j for j, v in enumerate(vals) if lo <= v < hi]
        if len(idx) < 80:
            continue
        centers.append((lo + hi) / 2)
        rates.append(np.mean([odd[j] for j in idx]))
        ns.append(len(idx))
    return centers, rates, ns


def best_threshold(fixture, key, predict_odd_if_above: bool):
    best_acc, best_t = 0, 0.5
    for t in np.linspace(0.25, 0.75, 51):
        if predict_odd_if_above:
            pred = [1 if f[key] >= t else 0 for f in fixture]
        else:
            pred = [1 if f[key] <= t else 0 for f in fixture]
        acc = np.mean([p == f["actual_odd"] for p, f in zip(pred, fixture)])
        if acc > best_acc:
            best_acc, best_t = acc, t
    return best_acc, best_t


def analyze(rows):
    fixture = []
    for r in rows:
        p_o15 = implied_prob(r["o15"], r["u15"])
        p_o25 = implied_prob(r["o25"], r["u25"])
        if p_o15 is None or p_o25 is None:
            continue
        p_u15 = 1 - p_o15
        p_u25 = 1 - p_o25
        fixture.append({
            "season": r["season_name"],
            "md": int(r["matchday_number"]),
            "p_over15": p_o15,
            "p_under15": p_u15,
            "p_over25": p_o25,
            "p_under25": p_u25,
            "o15_odds": float(r["o15"]),
            "u15_odds": float(r["u15"]),
            "o25_odds": float(r["o25"]),
            "u25_odds": float(r["u25"]),
            "actual_odd": int(r["total_goals_odd"]),
            "total_goals": int(r["total_goals"]),
            "odd_odds": float(r["odd_odds"]) if r["odd_odds"] else None,
            "even_odds": float(r["even_odds"]) if r["even_odds"] else None,
            "p_odd_poisson_o25": poisson_odd_from_p25(p_o25),
        })

    n = len(fixture)
    base_odd = np.mean([f["actual_odd"] for f in fixture])

    # Empirical rules on O1.5 / O2.5 / U2.5
    rules = {}
    rules["predict_odd_if_p_under25_high"] = best_threshold(fixture, "p_under25", predict_odd_if_above=True)
    rules["predict_odd_if_p_over25_low"] = best_threshold(fixture, "p_over25", predict_odd_if_above=False)
    rules["predict_odd_if_p_under15_high"] = best_threshold(fixture, "p_under15", predict_odd_if_above=True)
    rules["predict_odd_if_p_over15_low"] = best_threshold(fixture, "p_over15", predict_odd_if_above=False)

    # 2D cell: low/high O1.5 x low/high O2.5 (median split)
    med15 = np.median([f["p_over15"] for f in fixture])
    med25 = np.median([f["p_over25"] for f in fixture])
    cells = {}
    for label, fn in [
        ("low_o15_low_o25", lambda f: f["p_over15"] < med15 and f["p_over25"] < med25),
        ("low_o15_high_o25", lambda f: f["p_over15"] < med15 and f["p_over25"] >= med25),
        ("high_o15_low_o25", lambda f: f["p_over15"] >= med15 and f["p_over25"] < med25),
        ("high_o15_high_o25", lambda f: f["p_over15"] >= med15 and f["p_over25"] >= med25),
    ]:
        sub = [f for f in fixture if fn(f)]
        if len(sub) >= 100:
            cells[label] = {
                "n": len(sub),
                "p_odd_actual": round(np.mean([x["actual_odd"] for x in sub]), 4),
            }

    # Matchday
    by_md = defaultdict(list)
    for f in fixture:
        by_md[(f["season"], f["md"])].append(f)

    md_rows = []
    for key, fixes in by_md.items():
        if len(fixes) != 8:
            continue
        mean_u25 = np.mean([x["p_under25"] for x in fixes])
        mean_o25 = np.mean([x["p_over25"] for x in fixes])
        mean_u15 = np.mean([x["p_under15"] for x in fixes])
        mean_o15 = np.mean([x["p_over15"] for x in fixes])
        n_odd = sum(x["actual_odd"] for x in fixes)
        slate_odd = sum(x["total_goals"] for x in fixes) % 2
        # MD rule: high mean under 2.5 -> expect more odd totals? empirical
        pred_slate_odd = 1 if mean_u25 >= 0.52 else 0
        pred_n_odd_ge4 = 1 if n_odd >= 4 else 0
        md_rows.append({
            "mean_p_under25": mean_u25,
            "mean_p_over25": mean_o25,
            "mean_p_under15": mean_u15,
            "mean_p_over15": mean_o15,
            "n_odd_actual": n_odd,
            "slate_sum_odd": slate_odd,
            "pred_slate_from_mean_u25": pred_slate_odd,
        })

    acc_slate_u25 = np.mean(
        [m["pred_slate_from_mean_u25"] == m["slate_sum_odd"] for m in md_rows]
    )

    # Quintiles by mean_p_under25 on MD
    md_sorted = sorted(md_rows, key=lambda x: x["mean_p_under25"])
    qn = len(md_sorted) // 5
    quint_u25 = []
    for i in range(5):
        chunk = md_sorted[i * qn : (i + 1) * qn if i < 4 else len(md_sorted)]
        if not chunk:
            continue
        quint_u25.append({
            "q": i + 1,
            "mean_p_under25": round(np.mean([c["mean_p_under25"] for c in chunk]), 4),
            "pct_slate_odd": round(100 * np.mean([c["slate_sum_odd"] for c in chunk]), 2),
            "avg_n_odd_games": round(np.mean([c["n_odd_actual"] for c in chunk]), 2),
            "n_md": len(chunk),
        })

    poisson_acc = np.mean(
        [1 if (f["p_odd_poisson_o25"] >= 0.5) == f["actual_odd"] else 0 for f in fixture]
    )

    return fixture, rules, cells, md_rows, acc_slate_u25, quint_u25, poisson_acc, base_odd, med15, med25


def plot(fixture, quint_u25):
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle("O/U 1.5 & 2.5 odds → full-time odd/even", fontsize=11)
    edges = np.linspace(0.15, 0.85, 15)

    for ax, key, title in [
        (axes[0, 0], "p_over15", "Implied P(Over 1.5)"),
        (axes[0, 1], "p_under25", "Implied P(Under 2.5)"),
        (axes[1, 0], "p_over25", "Implied P(Over 2.5)"),
        (axes[1, 1], "p_under15", "Implied P(Under 1.5)"),
    ]:
        c, r, ns = bin_curve(fixture, key, edges)
        ax.plot(c, r, "o-", lw=2)
        ax.axhline(0.5, ls="--", color="gray")
        ax.set_xlabel(title)
        ax.set_ylabel("Actual P(odd total)")
        ax.set_title(title)

    plt.tight_layout()
    p = PLOTS / "ou_15_25_vs_odd_even.png"
    fig.savefig(p, dpi=150)
    plt.close()

    fig2, ax2 = plt.subplots(figsize=(8, 4))
    ax2.bar([q["q"] for q in quint_u25], [q["pct_slate_odd"] for q in quint_u25], color="teal")
    ax2.axhline(50, ls="--", color="gray")
    ax2.set_xlabel("MD quintile by mean P(Under 2.5)")
    ax2.set_ylabel("% slates odd goal-sum")
    fig2.savefig(PLOTS / "ou_md_quintile_under25.png", dpi=150)
    plt.close()
    return p


def main():
    rows = load_fixture_ou()
    fixture, rules, cells, md_rows, acc_slate, quint, poisson_acc, base_odd, med15, med25 = analyze(rows)
    plot_p = plot(fixture, quint)

    with_oe = [f for f in fixture if f["odd_odds"] and f["even_odds"]]
    oe_acc = np.mean([
        (1 if (1 / f["odd_odds"]) >= (1 / f["even_odds"]) else 0) == f["actual_odd"]
        for f in with_oe
    ])

    report = {
        "markets_used": ["Over 1.5", "Under 1.5", "Over 2.5", "Under 2.5"],
        "n_fixtures": len(fixture),
        "n_matchdays": len(md_rows),
        "baseline_p_odd": round(float(base_odd), 4),
        "median_implied_p_over15": round(float(med15), 4),
        "median_implied_p_over25": round(float(med25), 4),
        "fixture_rules_best_threshold": {
            k: {"accuracy": round(v[0], 4), "threshold": round(v[1], 4)}
            for k, v in rules.items()
        },
        "fixture_2x2_cells_o15_o25": cells,
        "fixture_poisson_from_o25_only": round(poisson_acc, 4),
        "fixture_direct_odd_even_odds": round(float(oe_acc), 4),
        "matchday_slate_odd_rule_mean_u25_ge_0.52": round(acc_slate, 4),
        "matchday_quintiles_by_mean_p_under25": quint,
        "plot": str(plot_p),
    }

    verdict = []
    best_rule = max(rules.items(), key=lambda x: x[1][0])
    verdict.append(
        f"Best single-line rule: {best_rule[0]} acc={best_rule[1][0]:.3f} @ threshold={best_rule[1][1]:.3f}"
    )
    if cells:
        extreme = max(cells.items(), key=lambda x: abs(x[1]["p_odd_actual"] - 0.5))
        verdict.append(
            f"Strongest 2D cell {extreme[0]}: P(odd)={extreme[1]['p_odd_actual']:.3f} n={extreme[1]['n']}"
        )
    if quint and len(quint) >= 2:
        verdict.append(
            f"MD: low vs high mean P(Under 2.5) slate odd% "
            f"Q1={quint[0]['pct_slate_odd']}% Q5={quint[-1]['pct_slate_odd']}%"
        )
    verdict.append("Use O1.5+O2.5 together for λ cage; U2.5/U1.5 for low-score odd lean (1,3).")
    report["verdict"] = verdict

    (OUT / "ou_15_25_vs_odd_even_report.json").write_text(json.dumps(report, indent=2))

    print(f"Fixtures (O1.5+O2.5): {len(fixture)}")
    print(f"Medians: P(O1.5)={med15:.3f} P(O2.5)={med25:.3f}")
    for k, v in rules.items():
        print(f"  {k}: acc={v[0]:.3f} @ t={v[1]:.3f}")
    print("2x2 cells:", cells)
    print(f"MD slate rule (mean U2.5): {acc_slate:.3f}")
    print("Quintiles U25 slate odd%:", [q["pct_slate_odd"] for q in quint])
    for v in verdict:
        print(" -", v)
    print(f"Plot: {plot_p}")


if __name__ == "__main__":
    main()