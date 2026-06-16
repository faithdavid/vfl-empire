#!/usr/bin/env python3
"""Plot Odd/Even parity from canonical VFL results."""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "models" / "odd_even" / "plots"
OUT.mkdir(parents=True, exist_ok=True)

plt.style.use("seaborn-v0_8-darkgrid")


def fetch_matchday():
    sql = """
    WITH complete AS (
      SELECT s.id AS pk FROM vfl_seasons s
      JOIN vfl_matchdays md ON md.season_id=s.id
      JOIN vfl_results_v2 r ON r.matchday_id=md.id
      WHERE s.season_name ~ '^VFLM'
      GROUP BY s.id HAVING COUNT(DISTINCT md.matchday_number)=30 AND COUNT(r.id)=240
    )
    SELECT md.matchday_number,
           COUNT(*) FILTER (WHERE (r.total_goals%2)=1) AS odd,
           COUNT(*) AS n
    FROM vfl_results_v2 r
    JOIN vfl_matchdays md ON md.id=r.matchday_id
    WHERE md.season_id IN (SELECT pk FROM complete)
    GROUP BY md.matchday_number ORDER BY 1
    """
    with get_db() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def fetch_season_odd_counts():
    sql = """
    WITH complete AS (
      SELECT s.id AS pk, s.season_name FROM vfl_seasons s
      JOIN vfl_matchdays md ON md.season_id=s.id
      JOIN vfl_results_v2 r ON r.matchday_id=md.id
      WHERE s.season_name ~ '^VFLM'
      GROUP BY s.id, s.season_name
      HAVING COUNT(DISTINCT md.matchday_number)=30 AND COUNT(r.id)=240
    )
    SELECT COUNT(*) FILTER (WHERE (r.total_goals%2)=1) AS odd_count
    FROM vfl_results_v2 r
    JOIN vfl_matchdays md ON md.id=r.matchday_id
    JOIN complete c ON c.pk=md.season_id
    GROUP BY c.season_name
    """
    with get_db() as cur:
        cur.execute(sql)
        return [r["odd_count"] for r in cur.fetchall()]


def fetch_per_md_slot():
    """Odd share by fixture index within MD (row_number over fixtures per season,md)."""
    sql = """
    WITH complete AS (
      SELECT s.id AS pk FROM vfl_seasons s
      JOIN vfl_matchdays md ON md.season_id=s.id
      JOIN vfl_results_v2 r ON r.matchday_id=md.id
      WHERE s.season_name ~ '^VFLM'
      GROUP BY s.id HAVING COUNT(DISTINCT md.matchday_number)=30 AND COUNT(r.id)=240
    ),
    ranked AS (
      SELECT (r.total_goals%2) AS is_odd,
             ROW_NUMBER() OVER (
               PARTITION BY md.season_id, md.matchday_number
               ORDER BY r.id
             ) AS slot
      FROM vfl_results_v2 r
      JOIN vfl_matchdays md ON md.id=r.matchday_id
      WHERE md.season_id IN (SELECT pk FROM complete)
    )
    SELECT slot, COUNT(*) n,
           SUM(is_odd)::float/COUNT(*) AS pct_odd
    FROM ranked WHERE slot <= 8
    GROUP BY slot ORDER BY slot
    """
    with get_db() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def main():
    md = fetch_matchday()
    mds = [r["matchday_number"] for r in md]
    pct_odd = [100 * r["odd"] / r["n"] for r in md]
    even_pct = [100 - x for x in pct_odd]

    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(1, 31)
    ax.bar(x - 0.2, pct_odd, width=0.4, label="Odd", color="#3b82f6", alpha=0.85)
    ax.bar(x + 0.2, even_pct, width=0.4, label="Even", color="#64748b", alpha=0.85)
    ax.axhline(50, color="#f59e0b", ls="--", lw=1.2, label="50% fair line")
    ax.set_xlabel("Matchday")
    ax.set_ylabel("% of fixtures")
    ax.set_title("VFL canonical results: Odd vs Even total goals by matchday\n(826 seasons × 8 fixtures per MD)")
    ax.set_xticks(x)
    ax.set_ylim(44, 56)
    ax.legend(loc="upper right")
    fig.tight_layout()
    p1 = OUT / "odd_even_by_matchday.png"
    fig.savefig(p1, dpi=150)
    plt.close()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(mds, pct_odd, marker="o", color="#3b82f6", lw=2, markersize=6)
    ax.fill_between(mds, pct_odd, 50, alpha=0.15, color="#3b82f6")
    ax.axhline(50, color="#f59e0b", ls="--", lw=1.2)
    ax.set_xlabel("Matchday")
    ax.set_ylabel("% Odd (total goals)")
    ax.set_title("Odd share by matchday — deviation from 50%")
    ax.set_xticks(range(1, 31))
    ax.set_ylim(46, 52)
    for i, (m, p) in enumerate(zip(mds, pct_odd)):
        if p == min(pct_odd) or p == max(pct_odd):
            ax.annotate(f"{p:.1f}%", (m, p), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)
    fig.tight_layout()
    p2 = OUT / "odd_pct_line_by_matchday.png"
    fig.savefig(p2, dpi=150)
    plt.close()

    season_odds = fetch_season_odd_counts()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(season_odds, bins=range(95, 146), color="#3b82f6", edgecolor="#1e293b", alpha=0.8)
    ax.axvline(120, color="#f59e0b", ls="--", lw=2, label="120 odd / 240 (50%)")
    ax.set_xlabel("Odd results per season (of 240 fixtures)")
    ax.set_ylabel("Number of seasons")
    ax.set_title("Distribution of season-level Odd counts (826 complete seasons)")
    ax.legend()
    fig.tight_layout()
    p3 = OUT / "odd_count_per_season_hist.png"
    fig.savefig(p3, dpi=150)
    plt.close()

    slots = fetch_per_md_slot()
    fig, ax = plt.subplots(figsize=(8, 5))
    sx = [s["slot"] for s in slots]
    sp = [100 * s["pct_odd"] for s in slots]
    ax.bar(sx, sp, color="#8b5cf6", alpha=0.85)
    ax.axhline(50, color="#f59e0b", ls="--", lw=1.2)
    ax.set_xlabel("Fixture slot within matchday (1–8)")
    ax.set_ylabel("% Odd")
    ax.set_title("Parity by kickoff slot within MD (ordering by result row id)")
    ax.set_xticks(range(1, 9))
    ax.set_ylim(46, 54)
    fig.tight_layout()
    p4 = OUT / "odd_pct_by_fixture_slot.png"
    fig.savefig(p4, dpi=150)
    plt.close()

    # Summary donut-style bar
    total_odd = sum(r["odd"] for r in md)
    total_n = sum(r["n"] for r in md)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(
        [total_odd, total_n - total_odd],
        labels=[f"Odd\n{total_odd:,}\n({100*total_odd/total_n:.2f}%)", f"Even\n{total_n-total_odd:,}\n({100*(total_n-total_odd)/total_n:.2f}%)"],
        colors=["#3b82f6", "#64748b"],
        autopct="",
        startangle=90,
        wedgeprops=dict(width=0.5, edgecolor="white"),
    )
    ax.set_title(f"All canonical fixtures (n={total_n:,})")
    p5 = OUT / "odd_even_overall_pie.png"
    fig.savefig(p5, dpi=150)
    plt.close()

    print("Wrote:")
    for p in [p1, p2, p3, p4, p5]:
        print(p)


if __name__ == "__main__":
    main()