#!/usr/bin/env python3
"""
Latest 20 deep-market seasons (21 families): Odd/Even odds vs results.

Tag fixtures from deep prematch (OE, O/U, GG/NG, Double Chance, 1x2)
and find high-volume consistency (hit rate, implied vs actual gap).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "surge-findings"


def devig2(o, u):
    if o is None or u is None or float(o) <= 1 or float(u) <= 1:
        return None
    qo, qu = 1 / float(o), 1 / float(u)
    s = qo + qu
    return qo / s, qu / s


def vflm_num(name):
    m = re.search(r"(\d+)", name or "")
    return int(m.group(1)) if m else 0


def load_latest_20_seasons():
    sql = """
    SELECT vs.season_name,
           COUNT(DISTINCT p.event_id) AS events,
           COUNT(DISTINCT p.market_name) AS mkts
    FROM vfl_prematch_odds p
    JOIN vfl_results_v2 r ON r.event_id = p.event_id
    JOIN vfl_matchdays md ON md.id = r.matchday_id
    JOIN vfl_seasons vs ON vs.id = md.season_id
    WHERE vs.season_name LIKE 'VFLM%'
    GROUP BY vs.season_name
    HAVING COUNT(DISTINCT p.market_name) >= 20
    """
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
    rows.sort(key=lambda x: vflm_num(x["season_name"]), reverse=True)
    return [r["season_name"] for r in rows[:20]]


def load_fixture_odds(seasons: list[str]) -> pd.DataFrame:
    sql = """
    WITH base AS (
        SELECT r.season_name, r.matchday_number, r.event_id,
               r.home_team, r.away_team, r.total_goals, r.total_goals_odd,
               r.home_goals, r.away_goals
        FROM v_results_odd_even_ready r
        WHERE r.season_name = ANY(%s)
    ),
    oe AS (
        SELECT event_id,
            MAX(CASE WHEN selection_name = 'Odd' THEN odds END) AS odd_odds,
            MAX(CASE WHEN selection_name = 'Even' THEN odds END) AS even_odds
        FROM vfl_prematch_odds WHERE market_name = 'Odd/Even'
        GROUP BY event_id
    ),
    ou AS (
        SELECT event_id,
            MAX(CASE WHEN selection_name = 'Over 2.5' THEN odds END) AS o25,
            MAX(CASE WHEN selection_name = 'Under 2.5' THEN odds END) AS u25,
            MAX(CASE WHEN selection_name = 'Over 1.5' THEN odds END) AS o15,
            MAX(CASE WHEN selection_name = 'Under 1.5' THEN odds END) AS u15
        FROM vfl_prematch_odds WHERE market_name = 'Over/Under'
        GROUP BY event_id
    ),
    gg AS (
        SELECT event_id,
            MAX(CASE WHEN selection_name IN ('GG','Yes') THEN odds END) AS gg_yes,
            MAX(CASE WHEN selection_name IN ('NG','No') THEN odds END) AS gg_no
        FROM vfl_prematch_odds WHERE market_name = 'GG/NG'
        GROUP BY event_id
    ),
    dc AS (
        SELECT event_id,
            MAX(CASE WHEN selection_name = '1 2' THEN odds END) AS dc_12,
            MAX(CASE WHEN selection_name = '1 X' THEN odds END) AS dc_1x,
            MAX(CASE WHEN selection_name = 'X 2' THEN odds END) AS dc_x2
        FROM vfl_prematch_odds WHERE market_name = 'Double Chance'
        GROUP BY event_id
    ),
    m1 AS (
        SELECT event_id,
            MAX(CASE WHEN selection_name = '1' THEN odds END) AS home_win,
            MAX(CASE WHEN selection_name = 'X' THEN odds END) AS draw,
            MAX(CASE WHEN selection_name = '2' THEN odds END) AS away_win
        FROM vfl_prematch_odds WHERE market_name = '1x2'
        GROUP BY event_id
    )
    SELECT b.*, oe.*, ou.*, gg.*, dc.*, m1.*
    FROM base b
    LEFT JOIN oe ON oe.event_id = b.event_id
    LEFT JOIN ou ON ou.event_id = b.event_id
    LEFT JOIN gg ON gg.event_id = b.event_id
    LEFT JOIN dc ON dc.event_id = b.event_id
    LEFT JOIN m1 ON m1.event_id = b.event_id
    """
    with get_db() as cur:
        cur.execute(sql, (seasons,))
        return pd.DataFrame([dict(r) for r in cur.fetchall()])


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        actual_odd = int(r["total_goals_odd"])
        dv = devig2(r.get("odd_odds"), r.get("even_odds"))
        po, pe = (dv[0], dv[1]) if dv else (None, None)
        p_o25 = devig2(r.get("o25"), r.get("u25"))
        p_o25 = p_o25[0] if p_o25 else None
        p_o15 = devig2(r.get("o15"), r.get("u15"))
        p_o15 = p_o15[0] if p_o15 else None
        p_gg = devig2(r.get("gg_yes"), r.get("gg_no"))
        p_gg_yes = p_gg[0] if p_gg else None

        # 1x2 implied (3-way devig)
        h, d, a = r.get("home_win"), r.get("draw"), r.get("away_win")
        p_home = p_draw = p_away = None
        if h and d and a and min(float(h), float(d), float(a)) > 1:
            qh, qd, qa = 1 / float(h), 1 / float(d), 1 / float(a)
            s = qh + qd + qa
            p_home, p_draw, p_away = qh / s, qd / s, qa / s

        tags = []
        if po is not None:
            if po >= 0.54:
                tags.append("OE_odd_fav_strong")
            elif po >= 0.51:
                tags.append("OE_odd_fav")
            elif pe >= 0.54:
                tags.append("OE_even_fav_strong")
            elif pe >= 0.51:
                tags.append("OE_even_fav")
            else:
                tags.append("OE_coin")
        else:
            tags.append("OE_missing")

        if p_o25 is not None:
            if p_o25 >= 0.55:
                tags.append("O25_high")
            elif p_o25 <= 0.42:
                tags.append("O25_low")
        if p_o15 is not None and p_o15 >= 0.75:
            tags.append("O15_very_high")
        if p_gg_yes is not None:
            if p_gg_yes >= 0.55:
                tags.append("GG_yes_lean")
            elif p_gg_yes <= 0.42:
                tags.append("GG_no_lean")

        if p_draw is not None and p_draw >= 0.30:
            tags.append("DRAW_heavy")

        # Combo tags (deep stack)
        combo = []
        if po and pe:
            if pe >= 0.52 and p_o25 is not None and p_o25 <= 0.45:
                combo.append("COMBO_even_fav_low_o25")
            if po >= 0.52 and p_gg_yes is not None and p_gg_yes >= 0.52:
                combo.append("COMBO_odd_fav_gg_yes")
            if pe >= 0.52 and p_gg_yes is not None and p_gg_yes <= 0.45:
                combo.append("COMBO_even_fav_gg_no")

        rows.append({
            **{k: r[k] for k in r.index},
            "actual_odd": actual_odd,
            "p_implied_odd": po,
            "p_implied_even": pe,
            "p_over25": p_o25,
            "p_over15": p_o15,
            "p_gg_yes": p_gg_yes,
            "p_home": p_home,
            "p_draw": p_draw,
            "p_away": p_away,
            "tag_primary": tags[0] if tags else "none",
            "tags": "|".join(tags + combo),
        })
    return pd.DataFrame(rows)


def tag_stats(df: pd.DataFrame, min_n: int = 80) -> pd.DataFrame:
    exploded = []
    for _, r in df.iterrows():
        for t in str(r["tags"]).split("|"):
            if not t:
                continue
            exploded.append({"tag": t, "actual_odd": r["actual_odd"], "p_implied_odd": r["p_implied_odd"]})
    edf = pd.DataFrame(exploded)
    g = edf.groupby("tag").agg(
        n=("actual_odd", "count"),
        pct_odd=("actual_odd", "mean"),
        mean_p_odd=("p_implied_odd", "mean"),
    ).reset_index()
    g["pct_odd"] = (100 * g["pct_odd"]).round(2)
    g["gap_vs_implied"] = (g["pct_odd"] / 100 - g["mean_p_odd"]).round(4)
    g = g[g["n"] >= min_n].sort_values("n", ascending=False)
    return g


def oe_correlation(df: pd.DataFrame):
    sub = df.dropna(subset=["p_implied_odd", "odd_odds"])
    if sub.empty:
        return {}
    corr = float(np.corrcoef(sub["p_implied_odd"], sub["actual_odd"])[0, 1])
    # Brier
    brier = float(np.mean((sub["p_implied_odd"] - sub["actual_odd"]) ** 2))
    # Pick market favorite
    sub = sub.copy()
    sub["pick_odd"] = (sub["p_implied_odd"] >= 0.5).astype(int)
    acc = float((sub["pick_odd"] == sub["actual_odd"]).mean())
    # ROI flat 1u on OE favorite
    roi = []
    for _, r in sub.iterrows():
        pick_odd = r["p_implied_odd"] >= 0.5
        if pick_odd:
            won = r["actual_odd"] == 1
            odds = float(r["odd_odds"]) if r["odd_odds"] else 0
        else:
            won = r["actual_odd"] == 0
            odds = float(r["even_odds"]) if r["even_odds"] else 0
        if odds > 1:
            roi.append((odds - 1) if won else -1)
    roi_mean = float(np.mean(roi)) if roi else 0
    return {
        "n": len(sub),
        "corr_implied_odd_vs_outcome": round(corr, 4),
        "brier_implied_odd": round(brier, 4),
        "acc_pick_favorite": round(acc, 4),
        "roi_flat_stake_favorite": round(roi_mean, 4),
    }


def main():
    seasons = load_latest_20_seasons()
    df = load_fixture_odds(seasons)
    df = enrich(df)

    stats = tag_stats(df, min_n=60)
    oe = oe_correlation(df)

    # Consistency = high volume + |gap| or hit rate far from 50
    stats["consistency_score"] = (
        stats["n"] * (stats["pct_odd"] - 50).abs() / 50
    ).round(1)
    top_consistent = stats.nlargest(15, "consistency_score")

    # Per season stability for top tags
    top_tags = top_consistent.head(6)["tag"].tolist()
    season_stab = []
    for tag in top_tags:
        for sn, g in df.groupby("season_name"):
            sub = g[g["tags"].str.contains(tag, regex=False)]
            if len(sub) < 8:
                continue
            season_stab.append({
                "tag": tag,
                "season": sn,
                "n": len(sub),
                "pct_odd": round(100 * sub["actual_odd"].mean(), 1),
            })

    report = {
        "latest_20_deep_seasons": seasons,
        "n_fixtures": len(df),
        "n_with_odd_even_odds": int(df["p_implied_odd"].notna().sum()),
        "odd_even_correlation": oe,
        "tag_volume_table": stats.to_dict(orient="records"),
        "top_consistency_tags": top_consistent.to_dict(orient="records"),
        "findings": [],
    }

    findings = []
    if oe:
        findings.append(
            f"OE market vs result: corr={oe['corr_implied_odd_vs_outcome']}, "
            f"acc fav={oe['acc_pick_favorite']}, ROI/fav={oe['roi_flat_stake_favorite']}"
        )
    for _, row in top_consistent.head(5).iterrows():
        findings.append(
            f"Tag {row['tag']}: n={int(row['n'])}, actual odd {row['pct_odd']}%, "
            f"implied {100*row['mean_p_odd']:.1f}% if set, gap {row['gap_vs_implied']}"
        )
    findings.append(
        "Volume consistency = large n + stable pct_odd across latest 20 seasons; use combo tags for filters."
    )
    report["findings"] = findings

    df.to_csv(OUT / "deep20_odd_even_odds_results.csv", index=False)
    stats.to_csv(OUT / "deep_market_tag_consistency.csv", index=False)
    pd.DataFrame(season_stab).to_csv(OUT / "deep_tag_season_stability.csv", index=False)
    (OUT / "deep20_oe_correlation_report.json").write_text(json.dumps(report, indent=2))

    print("Seasons:", seasons[:5], "...", seasons[-1])
    print(f"Fixtures: {len(df)}, with OE: {report['n_with_odd_even_odds']}")
    print("OE:", oe)
    print("\nTop consistency tags:")
    print(top_consistent.head(10).to_string(index=False))
    for f in findings:
        print(" -", f)


if __name__ == "__main__":
    main()