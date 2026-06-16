#!/usr/bin/env python3
"""
Categorise by SCORELINE (H:A) + league table entering MD (X-1 / standings after MD-1).

Uncovers: which scorelines cluster when e.g. H3 vs A12, not just odd/even.
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


def replay_with_scorelines() -> pd.DataFrame:
    sql = """
    SELECT season_name, matchday_number, home_team, away_team,
           home_goals, away_goals, total_goals
    FROM v_results_odd_even_ready
    ORDER BY season_name, matchday_number, home_team
    """
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]

    records = []
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
                records.append({
                    "season_name": season,
                    "matchday_number": md,
                    "home_team": h,
                    "away_team": a,
                    "home_goals": hg,
                    "away_goals": ag,
                    "total_goals": int(f["total_goals"]),
                    "scoreline": f"{hg}:{ag}",
                    "result_cat": "H" if hg > ag else ("A" if hg < ag else "D"),
                    "home_rank_x1": hr,
                    "away_rank_x1": ar,
                    "home_tier_x1": rank_to_tier(hr),
                    "away_tier_x1": rank_to_tier(ar),
                    "table_cell": f"H{hr}_A{ar}",
                    "tier_clash": f"{rank_to_tier(hr)}x{rank_to_tier(ar)}",
                    "rank_sum": hr + ar,
                    "rank_diff": hr - ar,
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

    return pd.DataFrame(records)


def top_scorelines(df, group, min_n=40, top_k=5):
    rows = []
    for key, g in df.groupby(group):
        n = len(g)
        if n < min_n:
            continue
        vc = g["scoreline"].value_counts(normalize=True)
        top = vc.head(top_k)
        rows.append({
            "group": str(key),
            "n": n,
            "top1_scoreline": top.index[0],
            "top1_pct": round(100 * top.iloc[0], 2),
            "top2_scoreline": top.index[1] if len(top) > 1 else "",
            "top2_pct": round(100 * top.iloc[1], 2) if len(top) > 1 else 0,
            "entropy_scoreline": round(-(vc * np.log2(vc + 1e-12)).sum(), 3),
            "mean_total_goals": round(g["total_goals"].mean(), 3),
            "pct_draw": round(100 * (g["result_cat"] == "D").mean(), 2),
        })
    return pd.DataFrame(rows).sort_values("top1_pct", ascending=False)


def main():
    df = replay_with_scorelines()
    n = len(df)
    global_sl = df["scoreline"].value_counts(normalize=True)

    # Global scoreline cage
    top_global = [
        {"scoreline": k, "pct": round(100 * v, 2)}
        for k, v in global_sl.head(15).items()
    ]

    by_tier = top_scorelines(df, "tier_clash", min_n=500)
    by_cell_top = top_scorelines(df, "table_cell", min_n=80)

    # Rank-sum buckets (table gravity)
    df["rank_sum_bucket"] = pd.cut(
        df["rank_sum"],
        bins=[0, 10, 14, 18, 22, 32],
        labels=["elite_low", "upper", "mid", "lower", "deep"],
    )
    by_bucket = top_scorelines(df, "rank_sum_bucket", min_n=200)

    # MD1 uses initial equal-ish table from 0 pts — flag
    md1 = df[df["matchday_number"] == 1]
    md_rest = df[df["matchday_number"] > 1]

    tier_rest = top_scorelines(md_rest, "tier_clash", min_n=500)

    # Heatmap: mean total goals by home_rank x away_rank (binned 4x4 tiers)
    df["hr4"] = df["home_rank_x1"].clip(1, 16).apply(lambda r: (r - 1) // 4)
    df["ar4"] = df["away_rank_x1"].clip(1, 16).apply(lambda r: (r - 1) // 4)
    heat = df.groupby(["hr4", "ar4"])["total_goals"].mean().unstack(fill_value=np.nan)

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle("Scoreline categories × table X-1", fontsize=11)

    axes[0, 0].barh(
        [x["scoreline"] for x in top_global[:10]][::-1],
        [x["pct"] for x in top_global[:10]][::-1],
        color="steelblue",
    )
    axes[0, 0].set_title("Global top scorelines %")
    axes[0, 0].set_xlabel("%")

    if not tier_rest.empty:
        labels = tier_rest["group"].head(8).tolist()[::-1]
        pcts = tier_rest["top1_pct"].head(8).tolist()[::-1]
        axes[0, 1].barh(labels, pcts, color="teal")
        axes[0, 1].set_title("Top scoreline % by tier clash (MD>1)")

    im = axes[1, 0].imshow(heat.values, aspect="auto", cmap="YlOrRd")
    axes[1, 0].set_xticks(range(4))
    axes[1, 0].set_yticks(range(4))
    axes[1, 0].set_xticklabels(["A1-4", "A5-8", "A9-12", "A13-16"])
    axes[1, 0].set_yticklabels(["H1-4", "H5-8", "H9-12", "H13-16"])
    axes[1, 0].set_title("Mean total goals (X-1 ranks 4×4)")
    plt.colorbar(im, ax=axes[1, 0], fraction=0.046)

    if not by_bucket.empty:
        axes[1, 1].scatter(
            by_bucket["mean_total_goals"],
            by_bucket["top1_pct"],
            s=by_bucket["n"] / 50,
            alpha=0.7,
        )
        for _, r in by_bucket.iterrows():
            axes[1, 1].annotate(
                str(r["group"])[:8],
                (r["mean_total_goals"], r["top1_pct"]),
                fontsize=7,
            )
        axes[1, 1].set_xlabel("Mean total goals")
        axes[1, 1].set_ylabel("Dominant scoreline %")
        axes[1, 1].set_title("Rank-sum bucket")

    plt.tight_layout()
    plot = PLOTS / "scoreline_table_xminus1.png"
    fig.savefig(plot, dpi=150)
    plt.close()

    # Strongest "typed" cells
    cells_strong = by_cell_top.nlargest(12, "top1_pct")[
        ["group", "n", "top1_scoreline", "top1_pct", "mean_total_goals", "pct_draw"]
    ].to_dict(orient="records")

    report = {
        "n_fixtures": n,
        "definition": "Scoreline H:A; table = standings entering MD (after MD-1); MD1 from 0-point table",
        "global_top_scorelines_pct": top_global,
        "by_tier_clash_md_gt_1": tier_rest.head(12).to_dict(orient="records"),
        "by_rank_sum_bucket": by_bucket.to_dict(orient="records"),
        "strongest_table_cells_min80": cells_strong,
        "findings": [],
        "plot": str(plot),
    }

    findings = []
    if not tier_rest.empty:
        best = tier_rest.iloc[0]
        findings.append(
            f"Tier clash {best['group']}: most common scoreline {best['top1_scoreline']} "
            f"at {best['top1_pct']}% (n={best['n']}) — typed outcome, not just odd/even."
        )
    findings.append(
        f"Global mode scoreline {top_global[0]['scoreline']} ({top_global[0]['pct']}%); "
        "top 5 scorelines cover ~"
        + str(round(sum(x["pct"] for x in top_global[:5]), 1))
        + "% of all games."
    )
    if cells_strong:
        c = cells_strong[0]
        findings.append(
            f"Sharpest table cell {c['group']}: {c['top1_scoreline']} {c['top1_pct']}% "
            f"(mean T={c['mean_total_goals']}, draw {c['pct_draw']}%)."
        )
    findings.append(
        "Use scoreline PMF per table_cell_x1 + O/U integral; odd/even is coarse projection of this."
    )
    report["findings"] = findings

    df.to_csv(OUT / "fixtures_scoreline_table_x1.csv", index=False)
    tier_rest.to_csv(OUT / "scoreline_by_tier_clash_x1.csv", index=False)
    by_cell_top.to_csv(OUT / "scoreline_by_table_cell_x1.csv", index=False)
    (OUT / "scoreline_table_xminus1_report.json").write_text(json.dumps(report, indent=2))

    print(f"Fixtures: {n}")
    print("Global top 5:", top_global[:5])
    print("\nTier clash (MD>1) top modes:")
    print(tier_rest.head(6)[["group", "n", "top1_scoreline", "top1_pct", "mean_total_goals"]].to_string())
    print("\nFindings:")
    for f in findings:
        print(" -", f)
    print(f"Plot: {plot}")


if __name__ == "__main__":
    main()