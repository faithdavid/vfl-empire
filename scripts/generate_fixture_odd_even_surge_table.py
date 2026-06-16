#!/usr/bin/env python3
"""
Fixture-pair Odd/Even purity table — canonical silver only (no history.db skew).

Grain: (home_team, away_team) across all complete-season results.
Each row = how often total goals were Odd vs Even when this pairing played.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT_DIR = EMPIRE / "surge-findings"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TEAM_TIERS = {
    "Manchester Blue": "T1", "Liverpool": "T1", "Manchester Red": "T1",
    "Chelsea": "T1", "Tottenham": "T1", "London Guns": "T1",
    "Aston Villa": "T2", "Everton": "T2", "West Ham": "T2", "Brighton": "T2",
    "Leeds": "T3", "Wolverhampton": "T3", "Crystal Palace": "T3", "Newcastle": "T3",
    "Fulham": "T4", "Bournemouth": "T4",
}

MIN_N = 8  # minimum meetings across corpus
NEAR_PCT = 90.0  # ideal "near 100%" band (often empty on canonical data)
LEAN_PCT = 60.0  # practical lean for Surge-style review


def load_pair_stats() -> pd.DataFrame:
    sql = """
    SELECT home_team, away_team,
           COUNT(*) AS n,
           SUM(total_goals_odd) AS n_odd,
           AVG(total_goals::float) AS avg_total_goals,
           COUNT(DISTINCT season_name) AS seasons_seen,
           COUNT(DISTINCT matchday_number) AS distinct_mds
    FROM v_results_odd_even_ready
    GROUP BY home_team, away_team
    HAVING COUNT(*) >= %(min_n)s
    ORDER BY n DESC
    """
    with get_db() as cur:
        cur.execute(sql, {"min_n": MIN_N})
        rows = [dict(r) for r in cur.fetchall()]
    df = pd.DataFrame(rows)
    df["n_even"] = df["n"] - df["n_odd"]
    df["pct_odd"] = (100.0 * df["n_odd"] / df["n"]).round(2)
    df["pct_even"] = (100.0 * df["n_even"] / df["n"]).round(2)
    df["dominant"] = df.apply(
        lambda r: "Odd" if r["pct_odd"] >= r["pct_even"] else "Even", axis=1
    )
    df["dominant_pct"] = df.apply(
        lambda r: max(r["pct_odd"], r["pct_even"]), axis=1
    )
    df["home_tier"] = df["home_team"].map(TEAM_TIERS).fillna("T?")
    df["away_tier"] = df["away_team"].map(TEAM_TIERS).fillna("T?")
    return df


def highlight_pct(val: float, dominant: str, side: str) -> str:
    s = f"{val:.1f}%"
    if side == dominant and val >= NEAR_PCT:
        return f'<span class="highlight">{s}</span>'
    if val >= 100.0:
        return f'<span class="highlight">{s}</span>'
    return s


def build_html(df: pd.DataFrame) -> str:
    near = df[df["dominant_pct"] >= NEAR_PCT].sort_values(
        ["dominant_pct", "n"], ascending=[False, False]
    )
    lean = df[df["dominant_pct"] >= LEAN_PCT].sort_values(
        ["dominant_pct", "n"], ascending=[False, False]
    )
    full = df.sort_values(["dominant_pct", "n"], ascending=[False, False])

    def rows_html(sub: pd.DataFrame) -> str:
        out = []
        for _, r in sub.iterrows():
            out.append(
                f"""<tr>
  <td>{r['home_team']}</td><td>{r['away_team']}</td>
  <td><span class="{r['home_tier'].lower()}">{r['home_tier']}</span></td>
  <td><span class="{r['away_tier'].lower()}">{r['away_tier']}</span></td>
  <td>{int(r['n'])}</td><td>{int(r['seasons_seen'])}</td>
  <td>{r['avg_total_goals']:.2f}</td>
  <td>{highlight_pct(r['pct_odd'], r['dominant'], 'Odd')}</td>
  <td>{highlight_pct(r['pct_even'], r['dominant'], 'Even')}</td>
  <td><strong>{r['dominant']}</strong></td>
  <td>{r['dominant_pct']:.1f}%</td>
</tr>"""
            )
        return "\n".join(out)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>VFL Fixture Odd/Even Purity — Canonical</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; padding: 1.5rem; }}
    h1 {{ color: #38bdf8; }}
    .meta {{ color: #94a3b8; margin-bottom: 1rem; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; margin-bottom: 2rem; }}
    th, td {{ border: 1px solid #334155; padding: 6px 8px; text-align: left; }}
    th {{ background: #1e293b; color: #94a3b8; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #1e293b44; }}
    .highlight {{ color: #10b981; font-weight: bold; }}
    .t1 {{ color: #10b981; font-weight: bold; }}
    .t2 {{ color: #3b82f6; }}
    .t3 {{ color: #f59e0b; }}
    .t4 {{ color: #ef4444; }}
    h2 {{ color: #a78bfa; margin-top: 2rem; }}
    input {{ padding: 8px; width: 280px; margin-bottom: 12px; background: #1e293b; border: 1px solid #475569; color: #fff; }}
  </style>
</head>
<body>
  <h1>Fixture pairing — Odd / Even purity</h1>
  <p class="meta">Source: <code>v_results_odd_even_ready</code> only (deduped canonical results). Not legacy Surge/history.db patterns.<br/>
  Generated {ts}. Min meetings n≥{MIN_N}. Highlight: dominant side ≥{NEAR_PCT:.0f}%.</p>
  <p class="meta">Pairings: fixed <strong>home × away</strong> (direction matters). Counts are all season matchdays where this fixture appeared.</p>

  <h2>Near-certain (dominant ≥ {NEAR_PCT:.0f}%) — {len(near)} pairings</h2>
  <p class="meta">On <strong>canonical</strong> silver, parity is ~50/50 per pairing — expect <em>zero</em> true ~100% rows (unlike skewed legacy Surge).</p>
  <input type="text" id="f1" placeholder="Filter table…" onkeyup="filterTable('near','f1')"/>
  <table id="near">
    <thead><tr>
      <th>Home</th><th>Away</th><th>H Tier</th><th>A Tier</th>
      <th>n</th><th>Seasons</th><th>Avg goals</th>
      <th>% Odd</th><th>% Even</th><th>Dominant</th><th>Strength</th>
    </tr></thead>
    <tbody>{rows_html(near) if len(near) else '<tr><td colspan="11">None — no pairing ≥90% on clean data</td></tr>'}</tbody>
  </table>

  <h2>Strong lean (dominant ≥ {LEAN_PCT:.0f}%) — {len(lean)} pairings</h2>
  <input type="text" id="f0" placeholder="Filter table…" onkeyup="filterTable('lean','f0')"/>
  <table id="lean">
    <thead><tr>
      <th>Home</th><th>Away</th><th>H Tier</th><th>A Tier</th>
      <th>n</th><th>Seasons</th><th>Avg goals</th>
      <th>% Odd</th><th>% Even</th><th>Dominant</th><th>Strength</th>
    </tr></thead>
    <tbody>{rows_html(lean)}</tbody>
  </table>

  <h2>All pairings (n≥{MIN_N}) — {len(full)} rows</h2>
  <input type="text" id="f2" placeholder="Filter table…" onkeyup="filterTable('all','f2')"/>
  <table id="all">
    <thead><tr>
      <th>Home</th><th>Away</th><th>H Tier</th><th>A Tier</th>
      <th>n</th><th>Seasons</th><th>Avg goals</th>
      <th>% Odd</th><th>% Even</th><th>Dominant</th><th>Strength</th>
    </tr></thead>
    <tbody>{rows_html(full)}</tbody>
  </table>
  <script>
  function filterTable(id, fid) {{
    const q = document.getElementById(fid).value.toLowerCase();
    document.querySelectorAll('#'+id+' tbody tr').forEach(tr => {{
      tr.style.display = tr.innerText.toLowerCase().includes(q) ? '' : 'none';
    }});
  }}
  </script>
</body>
</html>"""


def main():
    df = load_pair_stats()
    csv_path = OUT_DIR / "fixture_odd_even_purity_canonical.csv"
    df.to_csv(csv_path, index=False)

    near = df[df["dominant_pct"] >= NEAR_PCT].sort_values(
        ["dominant_pct", "n"], ascending=[False, False]
    )
    json_path = OUT_DIR / "fixture_odd_even_purity_canonical.json"
    json_path.write_text(
        json.dumps(near.to_dict(orient="records"), indent=2)
    )

    html_path = OUT_DIR / "fixture_odd_even_purity_canonical.html"
    html_path.write_text(build_html(df))

    print(f"pairings n>={MIN_N}: {len(df)}")
    print(f"near-certain (>={NEAR_PCT}%): {len(near)}")
    if len(near):
        print(near[
            ["home_team", "away_team", "n", "pct_odd", "pct_even", "dominant", "dominant_pct"]
        ].head(25).to_string(index=False))
    print(f"CSV: {csv_path}")
    print(f"HTML: {html_path}")


if __name__ == "__main__":
    main()