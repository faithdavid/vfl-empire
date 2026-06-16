#!/usr/bin/env python3
"""
Isolate Odd/Even via matchday lag (X-1, X-2) + full-slate goal sums.

Angles:
  A) Fixture outcome vs table at enter MD (X-0), after MD-2 (X-2), after MD-1 (X-1).
  B) Previous slate: MD(N-1) total goals odd/even, count of odd fixtures on MD(N-1).
  C) Per season×MD: 8-fixture slate sum odd/even; distribution across corpus.
  D) Chains: prev slate parity → current fixture odd% and current slate sum odd%.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "surge-findings"
PLOTS = EMPIRE / "models" / "odd_even" / "plots"
OUT.mkdir(parents=True, exist_ok=True)
PLOTS.mkdir(parents=True, exist_ok=True)

TEAMS_16 = [
    "London Guns", "Liverpool", "Manchester Blue", "Manchester Red",
    "Chelsea", "Tottenham", "Aston Villa", "Everton",
    "West Ham", "Brighton", "Leeds", "Wolverhampton",
    "Crystal Palace", "Newcastle", "Fulham", "Bournemouth",
]


def compute_table(points, gd, gf):
    def key(t):
        return (-points[t], -gd[t], -gf[t], t)
    ordered = sorted(points.keys(), key=key)
    return {t: i + 1 for i, t in enumerate(ordered)}


def apply_md(points, gd, gf, fixtures):
    for f in fixtures:
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


def load_fixtures():
    sql = """
    SELECT season_name, matchday_number, home_team, away_team,
           home_goals, away_goals, total_goals_odd
    FROM v_results_odd_even_ready
    ORDER BY season_name, matchday_number, home_team
    """
    with get_db() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def build_matchday_slates(rows):
    """Per season×MD: slate stats."""
    by_sm = defaultdict(list)
    for r in rows:
        by_sm[(r["season_name"], r["matchday_number"])].append(r)
    slates = []
    for (season, md), fixes in by_sm.items():
        if len(fixes) != 8:
            continue
        tg = sum(int(f["home_goals"]) + int(f["away_goals"]) for f in fixes)
        n_odd = sum(int(f["total_goals_odd"]) for f in fixes)
        slates.append({
            "season_name": season,
            "matchday_number": md,
            "md_total_goals": tg,
            "md_sum_odd": int(tg % 2 == 1),
            "md_n_odd_fixtures": n_odd,
            "md_n_even_fixtures": 8 - n_odd,
            "md_avg_goals": tg / 8.0,
        })
    return pd.DataFrame(slates)


def replay_with_lag(rows, slates_df):
    slate_lookup = {
        (r.season_name, int(r.matchday_number)): r
        for r in slates_df.itertuples()
    }
    by_season = defaultdict(list)
    for r in rows:
        by_season[r["season_name"]].append(r)

    fixture_rows = []
    for season, fixtures in by_season.items():
        points = {t: 0 for t in TEAMS_16}
        gd = {t: 0 for t in TEAMS_16}
        gf = {t: 0 for t in TEAMS_16}
        ranks_after = {0: {t: 9 for t in TEAMS_16}}

        for md in range(1, 31):
            md_fix = sorted(
                [f for f in fixtures if f["matchday_number"] == md],
                key=lambda x: x["home_team"],
            )
            if len(md_fix) != 8:
                continue
            r_enter = ranks_after.get(md - 1, ranks_after[0])
            r_x2 = ranks_after.get(md - 2, ranks_after[0])
            r_x1 = ranks_after.get(md - 1, ranks_after[0])

            prev1 = slate_lookup.get((season, md - 1))
            prev2 = slate_lookup.get((season, md - 2))

            for f in md_fix:
                h, a = f["home_team"], f["away_team"]
                fixture_rows.append({
                    "season_name": season,
                    "matchday_number": md,
                    "home_team": h,
                    "away_team": a,
                    "is_odd": int(f["total_goals_odd"]),
                    "home_rank_x0": r_enter.get(h, 9),
                    "away_rank_x0": r_enter.get(a, 9),
                    "home_rank_x1": r_x1.get(h, 9),
                    "away_rank_x1": r_x1.get(a, 9),
                    "home_rank_x2": r_x2.get(h, 9),
                    "away_rank_x2": r_x2.get(a, 9),
                    "rank_diff_x0": r_enter.get(h, 9) - r_enter.get(a, 9),
                    "prev_md_sum_odd": prev1.md_sum_odd if prev1 is not None else np.nan,
                    "prev_md_n_odd": prev1.md_n_odd_fixtures if prev1 is not None else np.nan,
                    "prev_md_total_goals": prev1.md_total_goals if prev1 is not None else np.nan,
                    "prev2_md_sum_odd": prev2.md_sum_odd if prev2 is not None else np.nan,
                    "prev2_md_n_odd": prev2.md_n_odd_fixtures if prev2 is not None else np.nan,
                    "lag_pattern": (
                        f"p1_{int(prev1.md_sum_odd) if prev1 is not None else -1}"
                        f"_p2_{int(prev2.md_sum_odd) if prev2 is not None else -1}"
                    ),
                })
            apply_md(points, gd, gf, md_fix)
            ranks_after[md] = compute_table(points, gd, gf)

    return pd.DataFrame(fixture_rows)


def agg(df, cols, min_n=100):
    g = df.groupby(cols, as_index=False).agg(
        n=("is_odd", "count"), n_odd=("is_odd", "sum")
    )
    g["pct_odd"] = (100.0 * g["n_odd"] / g["n"]).round(2)
    g["pct_even"] = (100 - g["pct_odd"]).round(2)
    g["dominant_pct"] = g[["pct_odd", "pct_even"]].max(axis=1)
    return g[g["n"] >= min_n].sort_values("dominant_pct", ascending=False)


def plot_md_sum_parity(slates_df):
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle("Matchday slate parity (canonical)", fontsize=12)

    # 1) % of slates with odd total goals by MD number
    by_md = slates_df.groupby("matchday_number").agg(
        n=("md_sum_odd", "count"),
        pct_slate_odd=("md_sum_odd", "mean"),
    )
    by_md["pct_slate_odd"] *= 100
    axes[0, 0].bar(by_md.index, by_md["pct_slate_odd"], color="steelblue")
    axes[0, 0].axhline(50, color="gray", ls="--")
    axes[0, 0].set_xlabel("Matchday")
    axes[0, 0].set_ylabel("% slates with ODD sum")
    axes[0, 0].set_title("MD total-goals sum: odd vs even")

    # 2) dist of n odd fixtures per slate (0-8)
    cnt = slates_df["md_n_odd_fixtures"].value_counts().sort_index()
    axes[0, 1].bar(cnt.index, cnt.values, color="coral")
    axes[0, 1].set_xlabel("# odd fixtures on slate (of 8)")
    axes[0, 1].set_title("Per-MD fixture odd count distribution")

    # 3) md total goals histogram
    axes[1, 0].hist(slates_df["md_total_goals"], bins=range(8, 45), color="seagreen", edgecolor="white")
    axes[1, 0].set_xlabel("Sum goals on MD (all 8 games)")
    axes[1, 0].set_title("Slate goal-sum distribution")

    # 4) prev slate odd sum -> next slate odd sum
    sl = slates_df.sort_values(["season_name", "matchday_number"])
    sl["next_md_sum_odd"] = sl.groupby("season_name")["md_sum_odd"].shift(-1)
    pair = sl.dropna(subset=["next_md_sum_odd"])
    ct = pd.crosstab(pair["md_sum_odd"], pair["next_md_sum_odd"])
    im = axes[1, 1].imshow(ct.values, cmap="Blues")
    axes[1, 1].set_xticks([0, 1])
    axes[1, 1].set_yticks([0, 1])
    axes[1, 1].set_xticklabels(["next Even", "next Odd"])
    axes[1, 1].set_yticklabels(["prev Even", "prev Odd"])
    for i in range(2):
        for j in range(2):
            axes[1, 1].text(j, i, str(ct.values[i, j]), ha="center", va="center")
    axes[1, 1].set_title("MD(N) slate sum → MD(N+1) slate sum")

    plt.tight_layout()
    p = PLOTS / "matchday_slate_parity_lag.png"
    fig.savefig(p, dpi=150)
    plt.close()
    return p


def build_html(slate_by_md, lag_fix, chain_slate, chain_nodd):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def tbl(df, cols):
        rows = []
        for _, r in df.head(30).iterrows():
            cells = "".join(f"<td>{r[c]}</td>" for c in cols)
            rows.append(f"<tr>{cells}</tr>")
        hdr = "".join(f"<th>{c}</th>" for c in cols)
        return f"<table><thead><tr>{hdr}</tr></thead><tbody>{''.join(rows)}</tbody></table>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/>
<title>Odd/Even — MD lag & slate sums</title>
<style>
body{{background:#0f172a;color:#e2e8f0;font-family:system-ui;padding:1.5rem}}
h1{{color:#38bdf8}}h2{{color:#a78bfa}}.meta{{color:#94a3b8}}
table{{border-collapse:collapse;width:100%;font-size:0.85rem;margin:1rem 0}}
th,td{{border:1px solid #334155;padding:6px}}th{{background:#1e293b}}
</style></head><body>
<h1>Extrapolation angles: X-1 / X-2 + matchday sums</h1>
<p class="meta">{ts} · canonical v_results_odd_even_ready</p>

<h2>Angle 1 — Per matchday: slate total goals odd?</h2>
<p>Each MD = 8 games. <code>md_sum_odd</code> = (sum of all goals) is odd. <code>md_n_odd_fixtures</code> = count of games with odd totals (0–8).</p>
{tbl(slate_by_md, ["matchday_number","n_slates","pct_slate_sum_odd","avg_md_goals","avg_odd_fixtures"])}

<h2>Angle 2 — Fixture odd% after previous MD slate was Even/Odd (X-1)</h2>
{tbl(lag_fix, ["prev_md_sum_odd","n","pct_odd","pct_even","dominant_pct"])}

<h2>Angle 3 — Fixture odd% after prev MD had k odd fixtures (X-1 count)</h2>
{tbl(chain_nodd, ["prev_md_n_odd","n","pct_odd","pct_even","dominant_pct"])}

<h2>Angle 4 — Current MD slate sum odd% given prev slate (chain)</h2>
{tbl(chain_slate, ["prev_md_sum_odd","n","pct_next_slate_odd","pct_next_slate_even"])}

<h2>How to use</h2>
<ul>
<li><strong>Bet slate sum</strong>: use Angle 1 + 4 (MD bias + Markov from prev slate).</li>
<li><strong>Bet single fixture</strong>: combine Angle 2–3 with table cell (prior script) + same pairing.</li>
<li><strong>X-2</strong>: filter fixtures where <code>prev2_md_sum_odd</code> agrees with <code>prev_md_sum_odd</code> (both even or both odd) — narrows sample, may lift %.</li>
</ul>
</body></html>"""


def main():
    rows = load_fixtures()
    slates = build_matchday_slates(rows)
    fx = replay_with_lag(rows, slates)

    # Per MD aggregate (all seasons)
    slate_by_md = (
        slates.groupby("matchday_number")
        .agg(
            n_slates=("md_sum_odd", "count"),
            pct_slate_sum_odd=("md_sum_odd", lambda s: round(100 * s.mean(), 2)),
            avg_md_goals=("md_total_goals", "mean"),
            avg_odd_fixtures=("md_n_odd_fixtures", "mean"),
        )
        .reset_index()
    )

    lag_fix = agg(fx.dropna(subset=["prev_md_sum_odd"]), ["prev_md_sum_odd"], min_n=5000)
    chain_nodd = agg(fx.dropna(subset=["prev_md_n_odd"]), ["prev_md_n_odd"], min_n=3000)

    # Chain: prev slate parity -> current slate parity (season level)
    sl = slates.sort_values(["season_name", "matchday_number"]).copy()
    sl["prev_md_sum_odd"] = sl.groupby("season_name")["md_sum_odd"].shift(1)
    chain = sl.dropna(subset=["prev_md_sum_odd"])
    chain_slate = (
        chain.groupby("prev_md_sum_odd")
        .agg(
            n=("md_sum_odd", "count"),
            pct_next_slate_odd=("md_sum_odd", lambda s: round(100 * s.mean(), 2)),
        )
        .reset_index()
    )
    chain_slate["pct_next_slate_even"] = (100 - chain_slate["pct_next_slate_odd"]).round(2)

    # X-2 agreement filter
    fx2 = fx.dropna(subset=["prev_md_sum_odd", "prev2_md_sum_odd"])
    agree = fx2[fx2["prev_md_sum_odd"] == fx2["prev2_md_sum_odd"]]
    disagree = fx2[fx2["prev_md_sum_odd"] != fx2["prev2_md_sum_odd"]]
    print("=== X-1 prev slate sum (fixture odd%) ===")
    print(lag_fix.to_string(index=False))
    print("\n=== X-1 prev slate # odd fixtures (fixture odd%) ===")
    print(chain_nodd.to_string(index=False))
    print("\n=== MD slate sum chain (prev -> current slate odd%) ===")
    print(chain_slate.to_string(index=False))
    print(f"\nX-2 agree (p1==p2 parity): n={len(agree)} pct_odd={100*agree.is_odd.mean():.2f}%")
    print(f"X-2 disagree: n={len(disagree)} pct_odd={100*disagree.is_odd.mean():.2f}%")

    plot_path = plot_md_sum_parity(slates)

    slates.to_csv(OUT / "season_matchday_slate_parity.csv", index=False)
    slate_by_md.to_csv(OUT / "matchday_slate_parity_by_md.csv", index=False)
    fx.to_csv(OUT / "fixtures_with_md_lag_x1_x2.csv", index=False)
    lag_fix.to_csv(OUT / "fixture_odd_pct_by_prev_slate_sum.csv", index=False)
    chain_nodd.to_csv(OUT / "fixture_odd_pct_by_prev_slate_n_odd.csv", index=False)
    chain_slate.to_csv(OUT / "slate_sum_markov_chain.csv", index=False)

    html = build_html(slate_by_md, lag_fix, chain_slate, chain_nodd)
    html_path = OUT / "odd_even_matchday_lag_surge.html"
    html_path.write_text(html)

    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_slates": int(len(slates)),
        "n_fixtures_with_lag": int(len(fx)),
        "best_md_slate_odd_pct": slate_by_md.sort_values(
            "pct_slate_sum_odd", ascending=False
        ).head(3).to_dict(orient="records"),
        "x2_agree_pct_odd": round(100 * agree.is_odd.mean(), 2) if len(agree) else None,
        "x2_disagree_pct_odd": round(100 * disagree.is_odd.mean(), 2) if len(disagree) else None,
    }
    (OUT / "odd_even_lag_summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\nPlot: {plot_path}")
    print(f"HTML: {html_path}")


if __name__ == "__main__":
    main()