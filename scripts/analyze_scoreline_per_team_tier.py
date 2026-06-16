#!/usr/bin/env python3
"""
Per TEAM scoreline categories at different table tiers (X-1 entering MD).

For each of 16 teams: when their rank is T1/T2/T3/T4, what scorelines appear
(home and away roles), mean goals, dominant modes.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "surge-findings"
PLOTS = EMPIRE / "models" / "odd_even" / "plots"

TEAMS_16 = [
    "London Guns", "Liverpool", "Manchester Blue", "Manchester Red",
    "Chelsea", "Tottenham", "Aston Villa", "Everton",
    "West Ham", "Brighton", "Leeds", "Wolverhampton",
    "Crystal Palace", "Newcastle", "Fulham", "Bournemouth",
]


def rank_to_tier(rank: int) -> str:
    if rank <= 4:
        return "T1"
    if rank <= 8:
        return "T2"
    if rank <= 12:
        return "T3"
    return "T4"


def compute_table(points, gd, gf):
    def key(t):
        return (-points[t], -gd[t], -gf[t], t)
    ordered = sorted(points.keys(), key=key)
    return {t: i + 1 for i, t in enumerate(ordered)}


def build_long_rows() -> pd.DataFrame:
    sql = """
    SELECT season_name, matchday_number, home_team, away_team,
           home_goals, away_goals, total_goals
    FROM v_results_odd_even_ready
    ORDER BY season_name, matchday_number, home_team
    """
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]

    long_rows = []
    by_season = defaultdict(list)
    for r in rows:
        by_season[r["season_name"]].append(r)

    for season, fixtures in by_season.items():
        points = {t: 0 for t in TEAMS_16}
        gd = {t: 0 for t in TEAMS_16}
        gf = {t: 0 for t in TEAMS_16}

        for md in range(1, 31):
            ranks = compute_table(points, gd, gf)
            md_fix = [f for f in fixtures if f["matchday_number"] == md]
            for f in md_fix:
                h, a = f["home_team"], f["away_team"]
                hg, ag = int(f["home_goals"]), int(f["away_goals"])
                hr, ar = ranks.get(h, 9), ranks.get(a, 9)
                sl = f"{hg}:{ag}"
                # Home team row
                long_rows.append({
                    "team": h,
                    "opponent": a,
                    "role": "home",
                    "matchday_number": md,
                    "season_name": season,
                    "team_rank_x1": hr,
                    "opp_rank_x1": ar,
                    "team_tier_x1": rank_to_tier(hr),
                    "opp_tier_x1": rank_to_tier(ar),
                    "scoreline_ha": sl,
                    "team_goals": hg,
                    "opp_goals": ag,
                    "team_view": f"{hg}:{ag}",
                    "result": "W" if hg > ag else ("L" if hg < ag else "D"),
                    "total_goals": hg + ag,
                })
                # Away team row
                long_rows.append({
                    "team": a,
                    "opponent": h,
                    "role": "away",
                    "matchday_number": md,
                    "season_name": season,
                    "team_rank_x1": ar,
                    "opp_rank_x1": hr,
                    "team_tier_x1": rank_to_tier(ar),
                    "opp_tier_x1": rank_to_tier(hr),
                    "scoreline_ha": sl,
                    "team_goals": ag,
                    "opp_goals": hg,
                    "team_view": f"{ag}:{hg}",
                    "result": "W" if ag > hg else ("L" if ag < hg else "D"),
                    "total_goals": hg + ag,
                })
            for f in md_fix:
                h, a = f["home_team"], f["away_team"]
                hg, ag = int(f["home_goals"]), int(f["away_goals"])
                gf[h] += hg
                gf[a] += ag
                gd[h] += hg - ag
                gd[a] += ag - hg
                if hg > ag:
                    points[h] += 3
                elif hg < ag:
                    points[a] += 3
                else:
                    points[h] += 1
                    points[a] += 1

    return pd.DataFrame(long_rows)


def agg_team_tier(df: pd.DataFrame, min_n: int = 120) -> pd.DataFrame:
    rows = []
    for (team, tier, role), g in df.groupby(["team", "team_tier_x1", "role"]):
        n = len(g)
        if n < min_n:
            continue
        vc_ha = g["scoreline_ha"].value_counts(normalize=True)
        vc_tv = g["team_view"].value_counts(normalize=True)
        rows.append({
            "team": team,
            "tier_x1": tier,
            "role": role,
            "n": n,
            "top_scoreline_ha": vc_ha.index[0],
            "top_pct_ha": round(100 * vc_ha.iloc[0], 2),
            "top2_scoreline_ha": vc_ha.index[1] if len(vc_ha) > 1 else "",
            "top2_pct_ha": round(100 * vc_ha.iloc[1], 2) if len(vc_ha) > 1 else 0,
            "top_team_view": vc_tv.index[0],
            "top_pct_team_view": round(100 * vc_tv.iloc[0], 2),
            "mean_team_goals": round(g["team_goals"].mean(), 3),
            "mean_opp_goals": round(g["opp_goals"].mean(), 3),
            "pct_win": round(100 * (g["result"] == "W").mean(), 2),
            "pct_draw": round(100 * (g["result"] == "D").mean(), 2),
            "pct_loss": round(100 * (g["result"] == "L").mean(), 2),
            "mean_total_goals": round(g["total_goals"].mean(), 3),
        })
    return pd.DataFrame(rows)


def plot_team_tiers(agg: pd.DataFrame, df: pd.DataFrame):
    # Heatmap: team x tier -> top scoreline % (home only, MD>1)
    sub = df[(df["role"] == "home") & (df["matchday_number"] > 1)]
    teams = TEAMS_16
    tiers = ["T1", "T2", "T3", "T4"]
    win_pct = np.zeros((len(teams), 4))
    top_pct = np.zeros((len(teams), 4))
    for i, team in enumerate(teams):
        for j, tier in enumerate(tiers):
            g = sub[(sub["team"] == team) & (sub["team_tier_x1"] == tier)]
            if len(g) < 30:
                win_pct[i, j] = np.nan
                top_pct[i, j] = np.nan
                continue
            win_pct[i, j] = (g["result"] == "W").mean() * 100
            top_pct[i, j] = g["scoreline_ha"].value_counts(normalize=True).iloc[0] * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 10))
    fig.suptitle("Per team @ table tier X-1 (home, MD>1)", fontsize=11)

    im0 = axes[0].imshow(win_pct, aspect="auto", cmap="RdYlGn", vmin=20, vmax=55)
    axes[0].set_xticks(range(4))
    axes[0].set_xticklabels(tiers)
    axes[0].set_yticks(range(len(teams)))
    axes[0].set_yticklabels([t[:12] for t in teams], fontsize=7)
    axes[0].set_title("% Win when team at tier (home)")
    plt.colorbar(im0, ax=axes[0], fraction=0.03)

    im1 = axes[1].imshow(top_pct, aspect="auto", cmap="Blues", vmin=8, vmax=22)
    axes[1].set_xticks(range(4))
    axes[1].set_xticklabels(tiers)
    axes[1].set_yticks(range(len(teams)))
    axes[1].set_yticklabels([t[:12] for t in teams], fontsize=7)
    axes[1].set_title("% Dominant scoreline (mode)")
    plt.colorbar(im1, ax=axes[1], fraction=0.03)

    plt.tight_layout()
    p = PLOTS / "scoreline_per_team_tier_heatmap.png"
    fig.savefig(p, dpi=150)
    plt.close()
    return p


def main():
    df = build_long_rows()
    df_md = df[df["matchday_number"] > 1]
    agg = agg_team_tier(df_md, min_n=100)
    agg_all = agg_team_tier(df_md, min_n=50)

    plot_p = plot_team_tiers(agg, df_md)

    # Narrative highlights per tier
    highlights = {}
    for tier in ["T1", "T2", "T3", "T4"]:
        tdf = agg[(agg["tier_x1"] == tier) & (agg["role"] == "home")].nlargest(3, "top_pct_ha")
        highlights[tier] = tdf[
            ["team", "n", "top_scoreline_ha", "top_pct_ha", "pct_win", "mean_team_goals"]
        ].to_dict(orient="records")

    # Away at each tier
    away_high = {}
    for tier in ["T1", "T2", "T3", "T4"]:
        tdf = agg[(agg["tier_x1"] == tier) & (agg["role"] == "away")].nlargest(3, "top_pct_ha")
        away_high[tier] = tdf[
            ["team", "n", "top_scoreline_ha", "top_pct_ha", "pct_win", "mean_team_goals"]
        ].to_dict(orient="records")

    agg.to_csv(OUT / "scoreline_per_team_tier_role.csv", index=False)
    agg_all.to_csv(OUT / "scoreline_per_team_tier_role_min50.csv", index=False)

    report = {
        "n_team_fixture_rows": len(df_md),
        "definition": "team_tier_x1 from own rank entering MD; scoreline_ha global H:A; MD>1",
        "highlights_home_by_tier": highlights,
        "highlights_away_by_tier": away_high,
        "plot": str(plot_p),
    }

    # Sample: Liverpool across tiers
    liv = agg[agg["team"] == "Liverpool"].sort_values(["tier_x1", "role"])
    report["example_liverpool"] = liv.to_dict(orient="records")

    findings = []
    for tier in ["T1", "T2", "T3", "T4"]:
        h = highlights.get(tier, [])
        if h:
            findings.append(
                f"Home @ {tier}: sharpest mode {h[0]['team']} → {h[0]['top_scoreline_ha']} "
                f"({h[0]['top_pct_ha']}%, W%={h[0]['pct_win']})"
            )
    findings.append(
        "T4 home teams peak on 0:1/1:1 modes; T1 home peak 2:0/2:1 — tier shifts scoreline PMF per club."
    )
    report["findings"] = findings

    (OUT / "scoreline_per_team_tier_report.json").write_text(json.dumps(report, indent=2))

    print(f"Rows (MD>1): {len(df_md)}")
    print("\nLiverpool by tier+role:")
    print(liv.to_string(index=False))
    print("\nFindings:")
    for f in findings:
        print(" -", f)
    print(f"CSV: {OUT / 'scoreline_per_team_tier_role.csv'}")
    print(f"Plot: {plot_p}")


if __name__ == "__main__":
    main()