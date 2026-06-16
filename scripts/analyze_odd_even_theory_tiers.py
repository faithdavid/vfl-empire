#!/usr/bin/env python3
"""
Odd/Even: proven models + VFL weight-class / tier clash analysis.

Theory layers:
  1) Poisson totals — P(Odd) = sum_{i+j odd} Pois(i;λh)*Pois(j;λa)  [independent goals]
  2) Empirical parity by tier clash (static T1–T4 or X-2 table tiers)
  3) Bradley-Terry → expected total intensity (tier strength gap)

Outputs: clash heatmap, theory comparison CSV, plots.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import poisson

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "models" / "odd_even"
PLOTS = OUT / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)

# Innate weight class (oracle / 16-team ladder) — stable across eras
TEAM_TIERS = {
    "Manchester Blue": "T1",
    "Liverpool": "T1",
    "Manchester Red": "T1",
    "Chelsea": "T1",
    "Tottenham": "T1",
    "London Guns": "T1",
    "Aston Villa": "T2",
    "Everton": "T2",
    "West Ham": "T2",
    "Brighton": "T2",
    "Leeds": "T3",
    "Wolverhampton": "T3",
    "Crystal Palace": "T3",
    "Newcastle": "T3",
    "Fulham": "T4",
    "Bournemouth": "T4",
}

TIER_ORDER = {"T1": 1, "T2": 2, "T3": 3, "T4": 4}


def tier(team: str) -> str:
    return TEAM_TIERS.get(team, "T3")


def clash_label(h: str, a: str) -> str:
    th, ta = tier(h), tier(a)
    gap = abs(TIER_ORDER[th] - TIER_ORDER[ta])
    if th == ta:
        return f"equal_{th}"
    heavy = th if TIER_ORDER[th] < TIER_ORDER[ta] else ta
    light = ta if heavy == th else th
    return f"{heavy}_vs_{light}_gap{gap}"


def poisson_p_odd(lam_h: float, lam_a: float, max_g: int = 10) -> float:
    p = 0.0
    for i in range(max_g + 1):
        pi = poisson.pmf(i, lam_h)
        for j in range(max_g + 1):
            if (i + j) % 2 == 1:
                p += pi * poisson.pmf(j, lam_a)
    return float(p)


def load_fixtures() -> pd.DataFrame:
    sql = """
    SELECT home_team, away_team, home_goals, away_goals, total_goals,
           (total_goals % 2) AS is_odd, matchday_number, vflm_num
    FROM v_results_odd_even_ready
    """
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
    df = pd.DataFrame(rows)
    df["home_tier"] = df["home_team"].map(tier)
    df["away_tier"] = df["away_team"].map(tier)
    df["tier_gap"] = (df["home_tier"].map(TIER_ORDER) - df["away_tier"].map(TIER_ORDER)).abs()
    df["clash"] = [clash_label(h, a) for h, a in zip(df["home_team"], df["away_team"])]
    return df


def team_lambdas(df: pd.DataFrame) -> tuple[dict, dict]:
    """Empirical avg goals for/against per team (MLE rates for Poisson)."""
    lam_h, lam_a = {}, {}
    for t in df["home_team"].unique():
        sub = df[df["home_team"] == t]
        lam_h[t] = sub["home_goals"].mean()
    for t in df["away_team"].unique():
        sub = df[df["away_team"] == t]
        lam_a[t] = sub["away_goals"].mean()
    return lam_h, lam_a


def main():
    df = load_fixtures()
    n = len(df)
    global_odd = df["is_odd"].mean()

    # --- Empirical by tier clash (symmetric matrix T1–T4) ---
    tiers = ["T1", "T2", "T3", "T4"]
    mat = np.zeros((4, 4))
    cnt = np.zeros((4, 4))
    for _, r in df.iterrows():
        i = TIER_ORDER[r["home_tier"]] - 1
        j = TIER_ORDER[r["away_tier"]] - 1
        mat[i, j] += r["is_odd"]
        cnt[i, j] += 1
    pct = np.divide(mat, cnt, where=cnt > 0, out=np.full_like(mat, np.nan))

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(pct * 100, cmap="RdYlBu_r", vmin=46, vmax=52)
    ax.set_xticks(range(4))
    ax.set_yticks(range(4))
    ax.set_xticklabels(tiers)
    ax.set_yticklabels(tiers)
    ax.set_xlabel("Away tier")
    ax.set_ylabel("Home tier")
    ax.set_title("% Odd total goals — tier clash matrix (canonical results)")
    for i in range(4):
        for j in range(4):
            if cnt[i, j] > 0:
                ax.text(j, i, f"{pct[i,j]*100:.1f}%\n(n={int(cnt[i,j])})", ha="center", va="center", fontsize=8)
    plt.colorbar(im, ax=ax, label="% Odd")
    fig.tight_layout()
    p_heat = PLOTS / "odd_pct_tier_clash_heatmap.png"
    fig.savefig(p_heat, dpi=150)
    plt.close()

    # Gap effect
    gap_stats = (
        df.groupby("tier_gap")
        .agg(n=("is_odd", "count"), pct_odd=("is_odd", "mean"))
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(gap_stats["tier_gap"], gap_stats["pct_odd"] * 100, color="#6366f1", alpha=0.85)
    ax.axhline(50, color="#f59e0b", ls="--")
    ax.set_xlabel("|Home tier − Away tier| (0=same weight class)")
    ax.set_ylabel("% Odd")
    ax.set_title("Parity vs tier gap (weight-class distance)")
    fig.tight_layout()
    p_gap = PLOTS / "odd_pct_by_tier_gap.png"
    fig.savefig(p_gap, dpi=150)
    plt.close()

    # Poisson model from team lambdas
    lam_h, lam_a = team_lambdas(df)
    pois_p = []
    for _, r in df.iterrows():
        pois_p.append(poisson_p_odd(lam_h[r["home_team"]], lam_a[r["away_team"]]))
    df["poisson_p_odd"] = pois_p

    # Calibration bin
    df["pois_bin"] = pd.qcut(df["poisson_p_odd"], 10, duplicates="drop")
    cal = df.groupby("pois_bin", observed=True).agg(
        n=("is_odd", "count"),
        emp=("is_odd", "mean"),
        pred=("poisson_p_odd", "mean"),
    )

    fig, ax = plt.subplots(figsize=(7, 5))
    x = range(len(cal))
    ax.plot(x, cal["pred"], "o-", label="Poisson P(Odd)", color="#3b82f6")
    ax.plot(x, cal["emp"], "s-", label="Empirical", color="#10b981")
    ax.axhline(0.5, color="#94a3b8", ls=":")
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"Q{i+1}" for i in x], fontsize=8)
    ax.set_ylabel("P(Odd)")
    ax.set_title("Poisson totals model — decile calibration vs empirical")
    ax.legend()
    fig.tight_layout()
    p_cal = PLOTS / "poisson_odd_calibration.png"
    fig.savefig(p_cal, dpi=150)
    plt.close()

    # Top clash types by volume
    clash_tbl = (
        df.groupby("clash")
        .agg(n=("is_odd", "count"), pct_odd=("is_odd", "mean"))
        .sort_values("n", ascending=False)
        .head(15)
    )
    clash_tbl["pct_odd"] = (clash_tbl["pct_odd"] * 100).round(2)

    summary = {
        "fixtures": int(n),
        "global_pct_odd": round(100 * global_odd, 4),
        "poisson_brier": float(((df["poisson_p_odd"] - df["is_odd"]) ** 2).mean()),
        "tier_gap_stats": gap_stats.assign(pct_odd=(gap_stats["pct_odd"] * 100).round(2)).to_dict(orient="records"),
        "top_clashes": clash_tbl.reset_index().to_dict(orient="records"),
        "theory_notes": [
            "Poisson independent goals: standard for O/U and parity; VFL scorelines are discrete (34 states) — use as first-order.",
            "Tier clash: static T1–T4 = innate weight class; live X-2 standings (truth-bot) = dynamic class per MD.",
            "Odd/Even near 50%: edge only if clash or λ_total shifts P(Odd) away from book implied (vig).",
            "Next: Skellam/Bivariate Poisson + odds-cluster O2.5/GG fingerprint (entropy archetypes).",
        ],
    }
    (OUT / "tier_clash_odd_even_summary.json").write_text(json.dumps(summary, indent=2))
    clash_tbl.to_csv(OUT / "clash_type_odd_rates.csv")

    print(json.dumps(summary, indent=2))
    print("Plots:", p_heat, p_gap, p_cal)


if __name__ == "__main__":
    main()