#!/usr/bin/env python3
"""
Per-team scoring averages vs each of the other 15 opponents (canonical results).

Adds: who scores/concedes how much vs whom; home/away splits; odd/even rate per H2H.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "surge-findings"
PLOTS = EMPIRE / "models" / "odd_even" / "plots"

TEAMS = [
    "London Guns", "Liverpool", "Manchester Blue", "Manchester Red",
    "Chelsea", "Tottenham", "Aston Villa", "Everton",
    "West Ham", "Brighton", "Leeds", "Wolverhampton",
    "Crystal Palace", "Newcastle", "Fulham", "Bournemouth",
]


def load_fixtures() -> pd.DataFrame:
    sql = """
    SELECT season_name, matchday_number, home_team, away_team,
           home_goals, away_goals, total_goals, total_goals_odd
    FROM v_results_odd_even_ready
    """
    with get_db() as cur:
        cur.execute(sql)
        return pd.DataFrame([dict(r) for r in cur.fetchall()])


def build_h2h_long(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        h, a = r["home_team"], r["away_team"]
        hg, ag = int(r["home_goals"]), int(r["away_goals"])
        rows.append({
            "team": h,
            "opponent": a,
            "role": "home",
            "team_goals": hg,
            "opp_goals": ag,
            "total_goals": hg + ag,
            "total_odd": int(r["total_goals_odd"]),
            "season_name": r["season_name"],
        })
        rows.append({
            "team": a,
            "opponent": h,
            "role": "away",
            "team_goals": ag,
            "opp_goals": hg,
            "total_goals": hg + ag,
            "total_odd": int(r["total_goals_odd"]),
            "season_name": r["season_name"],
        })
    return pd.DataFrame(rows)


def agg_h2h(long: pd.DataFrame, min_n: int = 40) -> pd.DataFrame:
    g = (
        long.groupby(["team", "opponent", "role"])
        .agg(
            n=("team_goals", "count"),
            mean_team_goals=("team_goals", "mean"),
            mean_opp_goals=("opp_goals", "mean"),
            mean_total=("total_goals", "mean"),
            pct_odd_total=("total_odd", "mean"),
            pct_win=("team_goals", lambda s: (long.loc[s.index, "team_goals"] > long.loc[s.index, "opp_goals"]).mean()),
        )
        .reset_index()
    )
    g["mean_team_goals"] = g["mean_team_goals"].round(3)
    g["mean_opp_goals"] = g["mean_opp_goals"].round(3)
    g["mean_total"] = g["mean_total"].round(3)
    g["pct_odd_total"] = (100 * g["pct_odd_total"]).round(2)
    g["pct_win"] = (100 * g["pct_win"]).round(2)
    return g[g["n"] >= min_n]


def agg_combined(long: pd.DataFrame, min_n: int = 80) -> pd.DataFrame:
    g = (
        long.groupby(["team", "opponent"])
        .agg(
            n=("team_goals", "count"),
            mean_team_goals=("team_goals", "mean"),
            mean_opp_goals=("opp_goals", "mean"),
            mean_total=("total_goals", "mean"),
            pct_odd_total=("total_odd", "mean"),
        )
        .reset_index()
    )
    g["mean_team_goals"] = g["mean_team_goals"].round(3)
    g["mean_opp_goals"] = g["mean_opp_goals"].round(3)
    g["mean_total"] = g["mean_total"].round(3)
    g["pct_odd_total"] = (100 * g["pct_odd_total"]).round(2)
    return g[g["n"] >= min_n].sort_values(["team", "mean_team_goals"], ascending=[True, False])


def plot_heatmap(combined: pd.DataFrame):
    pivot = combined.pivot(index="team", columns="opponent", values="mean_team_goals")
    pivot = pivot.reindex(index=TEAMS, columns=TEAMS)
    fig, ax = plt.subplots(figsize=(14, 12))
    im = ax.imshow(pivot.values.astype(float), cmap="YlOrRd", aspect="auto", vmin=0.6, vmax=2.4)
    ax.set_xticks(range(16))
    ax.set_yticks(range(16))
    short = [t.split()[-1][:10] for t in TEAMS]
    ax.set_xticklabels(short, rotation=90, fontsize=7)
    ax.set_yticklabels(short, fontsize=7)
    ax.set_title("Mean goals SCORED by row team vs column opponent (all venues)")
    plt.colorbar(im, ax=ax, fraction=0.03)
    plt.tight_layout()
    p = PLOTS / "h2h_mean_team_goals_matrix.png"
    fig.savefig(p, dpi=150)
    plt.close()
    return p


def insights(combined: pd.DataFrame, by_role: pd.DataFrame) -> list[str]:
    lines = []
    # Highest scoring matchups for team
    top = combined.nlargest(8, "mean_total")
    for _, r in top.iterrows():
        lines.append(
            f"High-event H2H: {r['team']} vs {r['opponent']} "
            f"avg T={r['mean_total']} (team scores {r['mean_team_goals']}, n={int(r['n'])})"
        )
    low = combined.nsmallest(6, "mean_total")
    for _, r in low.iterrows():
        lines.append(
            f"Low-event H2H: {r['team']} vs {r['opponent']} avg T={r['mean_total']} (n={int(r['n'])})"
        )
    # Odd parity outliers
    odd_hi = combined.nlargest(5, "pct_odd_total")
    for _, r in odd_hi.iterrows():
        if r["pct_odd_total"] >= 54:
            lines.append(
                f"Odd-total lean: {r['team']} vs {r['opponent']} {r['pct_odd_total']}% odd (n={int(r['n'])})"
            )
    # Home fortress vs specific opp
    home = by_role[by_role["role"] == "home"]
    for team in ["Liverpool", "Manchester Red", "Leeds", "Fulham"]:
        sub = home[home["team"] == team].nlargest(2, "mean_team_goals")
        for _, r in sub.iterrows():
            lines.append(
                f"{team} HOME vs {r['opponent']}: scores {r['mean_team_goals']}, "
                f"concedes {r['mean_opp_goals']} (n={int(r['n'])})"
            )
    lines.append(
        "Insight pool: λ_team|opponent for Poisson; scoreline PMF; filter O/U integral per H2H not league avg."
    )
    return lines


def main():
    df = load_fixtures()
    long = build_h2h_long(df)
    combined = agg_combined(long, min_n=80)
    by_role = agg_h2h(long, min_n=35)
    plot_p = plot_heatmap(combined)

    combined.to_csv(OUT / "team_vs_opponent_scoring_combined.csv", index=False)
    by_role.to_csv(OUT / "team_vs_opponent_scoring_by_role.csv", index=False)

    # Wide matrix for quick lookup
    for metric in ["mean_team_goals", "mean_total", "pct_odd_total"]:
        w = combined.pivot(index="team", columns="opponent", values=metric)
        w.to_csv(OUT / f"h2h_matrix_{metric}.csv")

    findings = insights(combined, by_role)
    report = {
        "n_fixture_rows": len(df),
        "n_h2h_pairs_combined_min80": len(combined),
        "global_mean_team_goals": round(long["team_goals"].mean(), 3),
        "findings": findings,
        "plot": str(plot_p),
    }
    (OUT / "team_h2h_scoring_report.json").write_text(json.dumps(report, indent=2))

    print(f"Fixtures: {len(df)}")
    print(f"H2H pairs (n>=80): {len(combined)}")
    print("\nTop mean_total H2H:")
    print(combined.nlargest(10, "mean_total")[["team", "opponent", "n", "mean_team_goals", "mean_opp_goals", "mean_total", "pct_odd_total"]].to_string(index=False))
    print("\nInsights:")
    for f in findings[:12]:
        print(" -", f)
    print(f"Plot: {plot_p}")


if __name__ == "__main__":
    main()