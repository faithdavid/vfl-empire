#!/usr/bin/env python3
"""
MSport deep markets vs Odd/Even secret:

1) Correct Score + Exact goals exist — de-vig each market to 100%, derive P(odd) from CS PMF.
2) Compare derived P(odd) to Odd/Even line (arbitrage / consistency gap).
3) Cross-market Jacobian-style: how O/U, GG, 1x2 implied shifts predict OE implied.
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

SCORE_RE = re.compile(r"^(\d+):(\d+)$")


def devig_probs(odds_list: list[float]) -> np.ndarray | None:
    if not odds_list or any(o is None or float(o) <= 1 for o in odds_list):
        return None
    q = np.array([1 / float(o) for o in odds_list])
    s = q.sum()
    if s <= 0:
        return None
    return q / s


def load_event_markets(limit_events: int = 800) -> pd.DataFrame:
    sql = """
    WITH ev AS (
        SELECT DISTINCT p.event_id
        FROM vfl_prematch_odds p
        JOIN vfl_results_v2 r ON r.event_id = p.event_id
        JOIN vfl_matchdays md ON md.id = r.matchday_id
        JOIN vfl_seasons vs ON vs.id = md.season_id
        WHERE vs.season_name LIKE 'VFLM%'
          AND EXISTS (
            SELECT 1 FROM vfl_prematch_odds x
            WHERE x.event_id = p.event_id AND x.market_name = 'Correct Score'
          )
        ORDER BY p.event_id DESC
        LIMIT {lim}
    )
    SELECT p.event_id, p.market_name, p.selection_name, p.odds,
           v.total_goals, v.total_goals_odd, v.home_goals, v.away_goals
    FROM vfl_prematch_odds p
    JOIN ev ON ev.event_id = p.event_id
    JOIN v_results_odd_even_ready v ON v.event_id = p.event_id
    """.format(lim=int(limit_events))
    with get_db() as cur:
        cur.execute(sql)
        return pd.DataFrame([dict(r) for r in cur.fetchall()])


def cs_pmf(group: pd.DataFrame) -> dict:
    scores = []
    odds = []
    for _, r in group.iterrows():
        m = SCORE_RE.match(str(r["selection_name"]).strip())
        if m:
            scores.append((int(m.group(1)), int(m.group(2))))
            odds.append(float(r["odds"]))
    if len(scores) < 5:
        return {}
    p = devig_probs(odds)
    if p is None:
        return {}
    pmf = {}
    for (h, a), prob in zip(scores, p):
        pmf[f"{h}:{a}"] = float(prob)
    return pmf


def p_odd_from_cs(pmf: dict) -> float | None:
    if not pmf:
        return None
    s = 0.0
    for k, pr in pmf.items():
        h, a = map(int, k.split(":"))
        if (h + a) % 2 == 1:
            s += pr
    return s


def market_vector(df: pd.DataFrame, event_id: str) -> dict:
    sub = df[df["event_id"] == event_id]
    if sub.empty:
        return {}
    row0 = sub.iloc[0]
    out = {
        "event_id": event_id,
        "actual_odd": int(row0["total_goals_odd"]),
        "total_goals": int(row0["total_goals"]),
    }

    cs = sub[sub["market_name"] == "Correct Score"]
    pmf = cs_pmf(cs)
    out["p_odd_from_correct_score"] = p_odd_from_cs(pmf)
    out["cs_lines"] = len(pmf)

    oe = sub[sub["market_name"] == "Odd/Even"]
    o_odd = oe.loc[oe["selection_name"] == "Odd", "odds"]
    o_ev = oe.loc[oe["selection_name"] == "Even", "odds"]
    dv = devig_probs([
        float(o_odd.iloc[0]) if len(o_odd) else None,
        float(o_ev.iloc[0]) if len(o_ev) else None,
    ])
    out["p_odd_oe_market"] = float(dv[0]) if dv is not None else None

    # Exact goals (total) — selections often 0,1,2,3,4,5,6+
    eg = sub[sub["market_name"] == "Exact goals"]
    if len(eg) >= 3:
        sel = eg["selection_name"].astype(str).tolist()
        ods = eg["odds"].astype(float).tolist()
        p = devig_probs(ods)
        if p is not None:
            p_odd_eg = 0.0
            for sname, pr in zip(sel, p):
                t = parse_total_goals_sel(sname)
                if t is not None and t % 2 == 1:
                    p_odd_eg += pr
            out["p_odd_exact_goals"] = p_odd_eg

    ou = sub[sub["market_name"] == "Over/Under"]
    o25 = ou.loc[ou["selection_name"] == "Over 2.5", "odds"]
    u25 = ou.loc[ou["selection_name"] == "Under 2.5", "odds"]
    dv2 = devig_probs([
        float(o25.iloc[0]) if len(o25) else None,
        float(u25.iloc[0]) if len(u25) else None,
    ])
    out["p_over25"] = float(dv2[0]) if dv2 is not None else None

    return out


def parse_total_goals_sel(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s.endswith("+") and s[:-1].isdigit():
        return int(s[:-1])  # treat 6+ as 6 for parity bucket (approx)
    return None


def aggregate(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["gap_cs_minus_oe"] = df["p_odd_from_correct_score"] - df["p_odd_oe_market"]
    df["cs_pick_odd"] = (df["p_odd_from_correct_score"] >= 0.5).astype(int)
    df["oe_pick_odd"] = (df["p_odd_oe_market"] >= 0.5).astype(int)
    return df


def roi_back(df: pd.DataFrame, prob_col: str, min_gap: float = 0) -> dict:
    sub = df.dropna(subset=[prob_col, "p_odd_oe_market", "actual_odd"])
    if sub.empty:
        return {}
    # Bet odd when derived prob > oe implied + gap
    roi = []
    for _, r in sub.iterrows():
        p_der = r[prob_col]
        p_oe = r["p_odd_oe_market"]
        if p_der >= p_oe + min_gap:
            pick_odd = 1
        elif p_der <= p_oe - min_gap:
            pick_odd = 0
        else:
            continue
        # use OE market odds from implied inverse (approx) — skip without raw odds
        won = (r["actual_odd"] == pick_odd)
        roi.append(1 if won else 0)  # accuracy only here
    if not roi:
        return {"n": 0}
    return {"n": len(roi), "acc": float(np.mean(roi))}


def main():
    raw = load_event_markets(1200)
    events = raw["event_id"].unique()
    rows = [market_vector(raw, e) for e in events]
    df = aggregate(rows)
    df = df.dropna(subset=["p_odd_from_correct_score", "p_odd_oe_market"])

    corr = float(df["p_odd_from_correct_score"].corr(df["p_odd_oe_market"]))
    gap = df["gap_cs_minus_oe"]
    acc_cs = float((df["cs_pick_odd"] == df["actual_odd"]).mean())
    acc_oe = float((df["oe_pick_odd"] == df["actual_odd"]).mean())
    acc_blend = float(
        (
            ((df["p_odd_from_correct_score"] >= 0.5).astype(int) == df["actual_odd"])
            & ((df["gap_cs_minus_oe"].abs() >= 0.02))
        ).sum()
    )

    # When CS disagrees with OE by >=3pp, who wins?
    disagree = df[df["gap_cs_minus_oe"].abs() >= 0.03].copy()
    if len(disagree):
        disagree["cs_right"] = (disagree["cs_pick_odd"] == disagree["actual_odd"]).astype(int)
        disagree["oe_right"] = (disagree["oe_pick_odd"] == disagree["actual_odd"]).astype(int)
        cs_wins = float(disagree["cs_right"].mean())
        oe_wins = float(disagree["oe_right"].mean())
    else:
        cs_wins = oe_wins = None

    markets_doc = [
        {"market": "Correct Score", "role": "Full H:A PMF → sum odd totals = P(odd); THE structural key"},
        {"market": "Exact goals", "role": "PMF on T∈{0..6+} → P(odd) by parity sum"},
        {"market": "Home/Away Exact goals", "role": "Joint grid → marginal totals → P(odd)"},
        {"market": "Over/Under", "role": "CDF knots on T; does not fix parity alone"},
        {"market": "Odd/Even", "role": "Direct parity; should equal CS-derived if book consistent"},
        {"market": "1x2 & O/U", "role": "Coupled margin + totals — extra constraints"},
        {"market": "HT/FT", "role": "Path constraint on halves; weak OE link"},
        {"market": "GG/NG", "role": "0:0 vs scoring; biases even slightly"},
        {"market": "Which team to score", "role": "Clean sheet mass → affects low-T even"},
    ]

    report = {
        "n_events_with_cs_and_oe": len(df),
        "corr_p_odd_cs_vs_oe_market": round(corr, 4),
        "mean_gap_cs_minus_oe": round(float(gap.mean()), 4),
        "std_gap": round(float(gap.std()), 4),
        "acc_pick_odd_from_cs": round(acc_cs, 4),
        "acc_pick_odd_from_oe": round(acc_oe, 4),
        "when_disagree_3pp_cs_acc": cs_wins,
        "when_disagree_3pp_oe_acc": oe_wins,
        "n_disagree_3pp": len(disagree),
        "markets_that_reveal_odd_even": markets_doc,
        "reverse_from_result": (
            "Ex-post: actual score maps to one CS selection; compare implied prob at "
            "result vs average implied — measures calibration, not edge."
        ),
        "normalize_100_derivative": (
            "Per market de-vig to 100%; P(odd)_CS = Σ_{h+a odd} p(h,a). "
            "Derivative insight: gap = P(odd)_CS - P(odd)_OE is the 'secret' slack; "
            "bet side where internal CS PMF disagrees with OE after normalization."
        ),
        "verdict": [],
    }

    if corr > 0.85:
        report["verdict"].append("CS and OE are highly aligned — little arb; secret is in tails (Other score).")
    if cs_wins and oe_wins and cs_wins > oe_wins + 0.02:
        report["verdict"].append("When markets disagree ≥3pp, CS-implied parity beats OE line.")
    elif cs_wins and oe_wins:
        report["verdict"].append("On disagreement, CS does not beat OE reliably — book is internally consistent.")
    report["verdict"].append(
        "Exact Score market IS the mathematical inverse of odd/even; O/E is marginal of CS PMF."
    )

    df.to_csv(OUT / "correct_score_vs_odd_even_events.csv", index=False)
    (OUT / "markets_odd_even_secret_report.json").write_text(json.dumps(report, indent=2))

    print("Events:", len(df))
    print("Corr CS-derived P(odd) vs OE market:", corr)
    print("Mean gap (CS - OE):", gap.mean())
    print("Acc CS pick:", acc_cs, "Acc OE pick:", acc_oe)
    print("Disagree >=3pp n=", len(disagree), "CS acc", cs_wins, "OE acc", oe_wins)
    print("\nMarkets (top):")
    for m in markets_doc[:5]:
        print(f"  {m['market']}: {m['role']}")
    for v in report["verdict"]:
        print("VERDICT:", v)


if __name__ == "__main__":
    main()