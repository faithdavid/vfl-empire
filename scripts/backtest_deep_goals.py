#!/usr/bin/env python3
"""Backtest deep_goals stack on canonical PG prematch + results. No live/bot wiring."""
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
from common.deep_goals_predictor import devig, pmf_from_ou  # noqa: E402

OUT = EMPIRE / "surge-findings"
SCORE_RE = re.compile(r"^(\d+):(\d+)$")


def load_h2h() -> dict[tuple[str, str], float]:
    p = OUT / "team_vs_opponent_scoring_combined.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    return {(r.team, r.opponent): float(r.mean_total) for r in df.itertuples()}


def fetch_prematch_batch(limit_events: int = 3000) -> pd.DataFrame:
    sql = f"""
    SELECT p.event_id, p.market_name, p.selection_name, p.specifiers, p.odds,
           v.home_team, v.away_team, v.total_goals, v.home_goals, v.away_goals,
           v.season_name, v.matchday_number
    FROM vfl_prematch_odds p
    JOIN v_results_odd_even_ready v ON v.event_id = p.event_id
    WHERE v.season_name ~ '^VFLM [0-9]+$'
    ORDER BY v.season_name DESC, p.event_id DESC
    LIMIT {limit_events * 150}
    """
    with get_db() as cur:
        cur.execute(sql)
        return pd.DataFrame([dict(r) for r in cur.fetchall()])


def build_odds_dict_and_markets(g: pd.DataFrame) -> tuple[dict, list]:
    odds_dict: dict = {}
    markets: list = []
    ou_by_line: dict[str, dict] = {}

    for _, r in g.iterrows():
        mn = str(r.market_name)
        sel = str(r.selection_name)
        spec = str(r.specifiers or "")
        try:
            val = float(r.odds)
        except (TypeError, ValueError):
            continue
        if val <= 1.0:
            continue

        if mn == "Over/Under":
            line = None
            for ln in ("1.5", "2.5", "3.5"):
                if ln in spec or sel.endswith(ln):
                    line = ln
                    break
            if line:
                ou_by_line.setdefault(line, {"outcomes": []})
                ou_by_line[line]["name"] = "Over/Under"
                ou_by_line[line]["specifiers"] = f"total={line}"
                if sel.startswith("Over"):
                    ou_by_line[line]["outcomes"].append(
                        {"description": sel, "odds": val}
                    )
                    key = {"1.5": "o15", "2.5": "o25", "3.5": "o35"}[line]
                    odds_dict[key] = val
                elif sel.startswith("Under"):
                    ou_by_line[line]["outcomes"].append(
                        {"description": sel, "odds": val}
                    )
                    key = {"1.5": "u15", "2.5": "u25", "3.5": "u35"}[line]
                    odds_dict[key] = val
        elif mn == "Correct Score":
            m = SCORE_RE.match(sel.strip())
            if m:
                markets.append(
                    {
                        "name": "Correct Score",
                        "outcomes": [{"description": sel, "odds": val}],
                    }
                )

    for line, mk in ou_by_line.items():
        if len(mk.get("outcomes", [])) >= 2:
            markets.append(mk)

    return odds_dict, markets


def predict_row(home: str, away: str, odds_dict: dict, markets: list, h2h: dict) -> dict:
    from common.deep_goals_predictor import predict_from_odds_dict

    return predict_from_odds_dict(home, away, odds_dict, markets=markets)


def backtest(df_raw: pd.DataFrame, h2h: dict) -> dict:
    events = df_raw["event_id"].unique()
    rows = []
    for eid in events:
        g = df_raw[df_raw.event_id == eid]
        if g.empty:
            continue
        home = g["home_team"].iloc[0]
        away = g["away_team"].iloc[0]
        actual_t = int(g["total_goals"].iloc[0])
        hs = int(g["home_goals"].iloc[0]) if pd.notna(g["home_goals"].iloc[0]) else None
        aw = int(g["away_goals"].iloc[0]) if pd.notna(g["away_goals"].iloc[0]) else None
        season = g["season_name"].iloc[0]
        odds_dict, markets = build_odds_dict_and_markets(g)
        if odds_dict.get("o25") is None or odds_dict.get("u25") is None:
            continue
        pred = predict_row(home, away, odds_dict, markets, h2h)
        et = pred.get("E_total_blend")
        lean = pred.get("o25_lean", "")
        top = pred.get("top_scorelines") or []
        top1 = top[0]["scoreline"] if top else None
        top3 = {t["scoreline"] for t in top[:3]}
        actual_sl = f"{hs}:{aw}" if hs is not None and aw is not None else None

        over_hit = actual_t >= 3
        under_hit = actual_t <= 2
        pick_over = lean == "Over 2.5"
        o25_correct = (pick_over and over_hit) or (not pick_over and under_hit)

        o_odds = float(odds_dict["o25"])
        u_odds = float(odds_dict["u25"])
        stake_odds = o_odds if pick_over else u_odds
        pnl = (stake_odds - 1.0) if o25_correct else -1.0

        rows.append(
            {
                "event_id": eid,
                "season_name": season,
                "home_team": home,
                "away_team": away,
                "E_total_blend": et,
                "actual_total": actual_t,
                "abs_err": abs(et - actual_t) if et is not None else None,
                "o25_lean": lean,
                "o25_correct": o25_correct,
                "stake_odds": stake_odds,
                "pnl_unit": pnl,
                "top1_scoreline": top1,
                "actual_scoreline": actual_sl,
                "top1_hit": actual_sl == top1 if actual_sl and top1 else None,
                "top3_hit": actual_sl in top3 if actual_sl else None,
            }
        )

    bt = pd.DataFrame(rows)
    if bt.empty:
        return {"error": "no rows with O/U 2.5"}

    n = len(bt)
    mae = float(bt["abs_err"].mean())
    within1 = float((bt["abs_err"] <= 1).mean())
    o25_acc = float(bt["o25_correct"].mean())
    roi = float(bt["pnl_unit"].sum() / n)
    top1_rate = float(bt["top1_hit"].dropna().mean()) if bt["top1_hit"].notna().any() else None
    top3_rate = float(bt["top3_hit"].dropna().mean()) if bt["top3_hit"].notna().any() else None

    by_season = (
        bt.groupby("season_name")
        .agg(
            n=("pnl_unit", "count"),
            mae=("abs_err", "mean"),
            o25_acc=("o25_correct", "mean"),
            roi=("pnl_unit", "mean"),
        )
        .reset_index()
        .sort_values("season_name")
    )

    seasons = sorted(bt["season_name"].unique(), key=lambda s: int(s.split()[-1]))
    split = max(1, int(len(seasons) * 0.7))
    train_s = set(seasons[:split])
    test_s = set(seasons[split:])
    test_bt = bt[bt["season_name"].isin(test_s)]
    wf = {}
    if len(test_bt) > 0:
        wf = {
            "holdout_seasons": len(test_s),
            "n_test": len(test_bt),
            "test_mae": float(test_bt["abs_err"].mean()),
            "test_o25_acc": float(test_bt["o25_correct"].mean()),
            "test_roi": float(test_bt["pnl_unit"].mean()),
        }

    report = {
        "n_fixtures": n,
        "mae_total_goals": round(mae, 4),
        "pct_within_1_goal": round(within1, 4),
        "o25_lean_accuracy": round(o25_acc, 4),
        "o25_flat_stake_roi_per_bet": round(roi, 4),
        "total_pnl_units": round(float(bt["pnl_unit"].sum()), 2),
        "top1_scoreline_hit_rate": round(top1_rate, 4) if top1_rate is not None else None,
        "top3_scoreline_hit_rate": round(top3_rate, 4) if top3_rate is not None else None,
        "walk_forward_holdout": wf,
        "note": "Flat 1u on O2.5 lean at closing prematch odds; no gates; no bots.",
    }
    bt.to_csv(OUT / "backtest_deep_goals_fixtures.csv", index=False)
    by_season.to_csv(OUT / "backtest_deep_goals_by_season.csv", index=False)
    (OUT / "backtest_deep_goals_report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    h2h = load_h2h()
    print("Loading prematch + results...")
    raw = fetch_prematch_batch(2500)
    print(f"Rows: {len(raw)}, events: {raw['event_id'].nunique()}")
    report = backtest(raw, h2h)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()