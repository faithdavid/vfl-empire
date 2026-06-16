#!/usr/bin/env python3
"""
Replay league table from canonical results; Odd/Even vs table position (entering MD).

Table rank before fixture = standings after previous matchday (MD1 → no prior, rank 9).
Tiers: T1 ranks 1-4, T2 5-8, T3 9-12, T4 13-16 (MSport X-2 style).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "surge-findings"
OUT.mkdir(parents=True, exist_ok=True)

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


def compute_table(points: dict[str, int], gd: dict[str, int], gf: dict[str, int]) -> dict[str, int]:
    """Return team -> rank 1..16 (1=top)."""
    teams = list(points.keys())

    def key(t):
        return (-points[t], -gd[t], -gf[t], t)

    ordered = sorted(teams, key=key)
    return {t: i + 1 for i, t in enumerate(ordered)}


def replay_seasons() -> pd.DataFrame:
    sql = """
    SELECT season_name, matchday_number, home_team, away_team,
           home_goals, away_goals, total_goals_odd
    FROM v_results_odd_even_ready
    ORDER BY season_name, matchday_number, home_team
    """
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]

    records = []
    by_season: dict[str, list] = defaultdict(list)
    for r in rows:
        by_season[r["season_name"]].append(r)

    for season, fixtures in by_season.items():
        points = {t: 0 for t in TEAMS_16}
        gd = {t: 0 for t in TEAMS_16}
        gf = {t: 0 for t in TEAMS_16}
        rank_before_md: dict[int, dict[str, int]] = {}

        for md in range(1, 31):
            rank_before_md[md] = compute_table(points, gd, gf)

        # process each md in order
        for md in range(1, 31):
            md_fix = [f for f in fixtures if f["matchday_number"] == md]
            ranks = rank_before_md[md]
            for f in md_fix:
                h, a = f["home_team"], f["away_team"]
                hr, ar = ranks.get(h, 9), ranks.get(a, 9)
                records.append({
                    "season_name": season,
                    "matchday_number": md,
                    "home_team": h,
                    "away_team": a,
                    "home_rank": hr,
                    "away_rank": ar,
                    "home_tier": rank_to_tier(hr),
                    "away_tier": rank_to_tier(ar),
                    "rank_diff": hr - ar,
                    "rank_sum": hr + ar,
                    "table_cell": f"H{hr}_A{ar}",
                    "is_odd": int(f["total_goals_odd"]),
                })
            # update table after MD
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


def agg_table(df: pd.DataFrame, group_cols: list[str], min_n: int = 30) -> pd.DataFrame:
    g = (
        df.groupby(group_cols, as_index=False)
        .agg(n=("is_odd", "count"), n_odd=("is_odd", "sum"), avg_rank_sum=("rank_sum", "mean"))
    )
    g["pct_odd"] = (100.0 * g["n_odd"] / g["n"]).round(2)
    g["pct_even"] = (100.0 - g["pct_odd"]).round(2)
    g["dominant"] = g.apply(lambda r: "Odd" if r["pct_odd"] >= 50 else "Even", axis=1)
    g["dominant_pct"] = g.apply(lambda r: max(r["pct_odd"], r["pct_even"]), axis=1)
    return g[g["n"] >= min_n].sort_values("dominant_pct", ascending=False)


def html_table(df: pd.DataFrame, title: str, cols: list[str]) -> str:
    rows = []
    for _, r in df.iterrows():
        cells = "".join(f"<td>{r[c]}</td>" for c in cols)
        po, pe = r.get("pct_odd", 0), r.get("pct_even", 0)
        hl_o = '<span class="highlight">' if po >= 55 else ""
        hl_e = '<span class="highlight">' if pe >= 55 else ""
        rows.append(f"<tr>{cells}</tr>")
    header = "".join(f"<th>{c}</th>" for c in cols)
    return f"<h2>{title}</h2><table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def build_surge_html(
    by_cell: pd.DataFrame,
    by_tier: pd.DataFrame,
    by_hrank: pd.DataFrame,
    by_diff: pd.DataFrame,
) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def render(df: pd.DataFrame, cols):
        body = []
        for _, r in df.iterrows():
            po, pe, dp = r["pct_odd"], r["pct_even"], r["dominant_pct"]
            o = f'<span class="highlight">{po:.1f}%</span>' if po >= 55 else f"{po:.1f}%"
            e = f'<span class="highlight">{pe:.1f}%</span>' if pe >= 55 else f"{pe:.1f}%"
            d = f'<span class="highlight">{dp:.1f}%</span>' if dp >= 55 else f"{dp:.1f}%"
            parts = []
            for c in cols:
                if c == "pct_odd":
                    parts.append(f"<td>{o}</td>")
                elif c == "pct_even":
                    parts.append(f"<td>{e}</td>")
                elif c == "dominant_pct":
                    parts.append(f"<td>{d}</td>")
                else:
                    parts.append(f"<td>{r[c]}</td>")
            body.append("<tr>" + "".join(parts) + "</tr>")
        hdr = "".join(f"<th>{c}</th>" for c in cols)
        return f"<table><thead><tr>{hdr}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    top_cell = by_cell.head(40)
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/>
<title>Odd/Even vs League Table Position</title>
<style>
body {{ background:#0f172a; color:#e2e8f0; font-family:system-ui; padding:1.5rem; }}
h1 {{ color:#38bdf8; }} h2 {{ color:#a78bfa; margin-top:2rem; }}
.meta {{ color:#94a3b8; }} table {{ border-collapse:collapse; width:100%; font-size:0.82rem; margin:1rem 0; }}
th,td {{ border:1px solid #334155; padding:5px 7px; }} th {{ background:#1e293b; }}
.highlight {{ color:#10b981; font-weight:bold; }}
input {{ margin:8px 0; padding:6px; background:#1e293b; color:#fff; border:1px solid #475569; }}
</style></head><body>
<h1>Odd / Even vs league table position</h1>
<p class="meta">Canonical replay: rank <strong>entering</strong> matchday (after MD−1). {ts}. n = fixtures.</p>

<h2>Tier clash (table tier entering MD)</h2>
{render(by_tier, ["home_tier","away_tier","n","pct_odd","pct_even","dominant","dominant_pct"])}

<h2>Home rank (1=top) entering MD</h2>
{render(by_hrank, ["home_rank","n","pct_odd","pct_even","dominant","dominant_pct"])}

<h2>Rank diff (home_rank − away_rank)</h2>
{render(by_diff, ["rank_diff","n","pct_odd","pct_even","dominant","dominant_pct"])}

<h2>Top table cells (home_rank × away_rank), min n≥25</h2>
<input placeholder="filter…" onkeyup="filterRows(this,'c1')"/>
<div id="c1">{render(top_cell, ["table_cell","home_rank","away_rank","n","pct_odd","pct_even","dominant","dominant_pct"])}</div>

<script>
function filterRows(inp, id) {{
  const q = inp.value.toLowerCase();
  document.querySelectorAll('#'+id+' tbody tr').forEach(tr => {{
    tr.style.display = tr.innerText.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</body></html>"""


def main():
    df = replay_seasons()
    print(f"fixtures with table context: {len(df)}")

    by_tier = agg_table(df, ["home_tier", "away_tier"], min_n=200)
    by_hrank = agg_table(df, ["home_rank"], min_n=500)
    by_diff = agg_table(df, ["rank_diff"], min_n=200)
    by_cell = agg_table(df, ["table_cell", "home_rank", "away_rank"], min_n=25)

    by_tier.to_csv(OUT / "odd_even_by_table_tier_clash.csv", index=False)
    by_cell.to_csv(OUT / "odd_even_by_table_cell.csv", index=False)
    df.to_csv(OUT / "odd_even_fixtures_with_table_rank.csv", index=False)

    html = build_surge_html(by_cell, by_tier, by_hrank, by_diff)
    path = OUT / "odd_even_table_position_surge.html"
    path.write_text(html)

    print("\n=== Tier clash (top dominant_pct) ===")
    print(by_tier.head(12).to_string(index=False))
    print("\n=== Best table cells (n>=25) ===")
    print(by_cell.head(15).to_string(index=False))
    print(f"\nHTML: {path}")


if __name__ == "__main__":
    main()