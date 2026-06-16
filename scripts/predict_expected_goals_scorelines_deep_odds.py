#!/usr/bin/env python3
"""
Unified deep-odds → expected total goals + top scorelines.

Layers (all de-vig to 100% per market):
  1) O/U 1.5, 2.5, 3.5 → CDF knots → P(T=0..7) → E[T]
  2) Exact goals → PMF on T → E[T] refine
  3) Correct Score → top H:A scorelines (book truth for scoreline)
  4) Optional H2H prior from team_vs_opponent_scoring_combined.csv

This is the logic we had in fixture_intelligence + ou_integral; now on PG deep prematch.
"""
from __future__ import annotations

import json
import math
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
GLOBAL_P_T = np.array([0.074, 0.190, 0.253, 0.220, 0.148, 0.073, 0.035, 0.007])
GLOBAL_P_T /= GLOBAL_P_T.sum()


def devig(odds: list[float]) -> np.ndarray | None:
    if not odds or any(x is None or float(x) <= 1 for x in odds):
        return None
    q = np.array([1.0 / float(x) for x in odds])
    s = q.sum()
    return q / s if s > 0 else None


def pmf_from_ou(p_le1: float, p_le2: float, p_le3: float | None = None) -> np.ndarray:
    """Under 1.5 / 2.5 / 3.5 → P(T=k) on 0..7."""
    F1, F2 = p_le1, p_le2
    F3 = p_le3 if p_le3 is not None else min(0.98, F2 + 0.35)
    pmf = np.zeros(8)
    pmf[0] = max(0.005, F1 * 0.38)
    pmf[1] = max(0.005, F1 - pmf[0])
    pmf[2] = max(0.005, F2 - F1)
    if F3 > F2:
        pmf[3] = max(0.005, F3 - F2)
        tail = max(0.01, 1 - F3)
        sh = GLOBAL_P_T[4:] / GLOBAL_P_T[4:].sum()
        pmf[4:] = tail * sh
    else:
        tail = max(0.01, 1 - F2)
        sh = GLOBAL_P_T[3:] / GLOBAL_P_T[3:].sum()
        pmf[3:] = tail * sh
    pmf /= pmf.sum()
    return pmf


def load_h2h() -> dict[tuple[str, str], float]:
    p = OUT / "team_vs_opponent_scoring_combined.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    return {(r.team, r.opponent): float(r.mean_total) for r in df.itertuples()}


def fetch_events(n: int = 500) -> pd.DataFrame:
    sql = f"""
    SELECT p.event_id, p.market_name, p.selection_name, p.specifiers, p.odds,
           v.home_team, v.away_team, v.total_goals AS actual_total
    FROM vfl_prematch_odds p
    JOIN v_results_odd_even_ready v ON v.event_id = p.event_id
    WHERE v.season_name LIKE 'VFLM%'
    ORDER BY p.event_id DESC
    LIMIT {n * 120}
    """
    with get_db() as cur:
        cur.execute(sql)
        return pd.DataFrame([dict(r) for r in cur.fetchall()])


def predict_one(g: pd.DataFrame, h2h: dict) -> dict:
    home = g["home_team"].iloc[0]
    away = g["away_team"].iloc[0]
    eid = g["event_id"].iloc[0]
    actual = g["actual_total"].iloc[0]

    def get_ou(line: str):
        sub = g[(g.market_name == "Over/Under") & (g.specifiers.astype(str).str.contains(line, na=False))]
        if sub.empty:
            sub = g[g.market_name == "Over/Under"]
        o = sub[sub.selection_name == f"Over {line}"]
        u = sub[sub.selection_name == f"Under {line}"]
        if len(o) and len(u):
            dv = devig([float(o.iloc[0].odds), float(u.iloc[0].odds)])
            if dv is not None:
                return float(dv[0]), float(dv[1])
        return None, None

    p_o15, p_u15 = get_ou("1.5")
    p_o25, p_u25 = get_ou("2.5")
    p_o35, p_u35 = get_ou("3.5")

    pmf_ou = None
    if p_u15 is not None and p_u25 is not None:
        p_le3 = p_u35 if p_u35 is not None else None
        pmf_ou = pmf_from_ou(p_u15, p_u25, p_le3)
        e_ou = float((np.arange(8) * pmf_ou).sum())
    else:
        e_ou = None

    # Exact goals
    eg = g[g.market_name == "Exact goals"]
    e_exact = None
    if len(eg) >= 4:
        sels, ods = [], []
        for _, r in eg.iterrows():
            s = str(r.selection_name).strip()
            if s.replace("+", "").isdigit():
                sels.append(int(s.replace("+", "")))
                ods.append(float(r.odds))
        if len(sels) >= 4:
            p = devig(ods)
            if p is not None:
                e_exact = float(sum(s * pr for s, pr in zip(sels, p)))

    # Correct score top 3
    cs = g[g.market_name == "Correct Score"]
    top_cs = []
    if len(cs) >= 5:
        rows = []
        for _, r in cs.iterrows():
            m = SCORE_RE.match(str(r.selection_name).strip())
            if m:
                rows.append((f"{m.group(1)}:{m.group(2)}", float(r.odds)))
        if rows:
            odds = [x[1] for x in rows]
            p = devig(odds)
            if p is not None:
                for (sc, _), pr in sorted(zip(rows, p), key=lambda x: -x[1])[:5]:
                    top_cs.append({"scoreline": sc, "p": round(float(pr), 4)})

    # Blend expected total
    parts, weights = [], []
    if e_ou is not None:
        parts.append(e_ou)
        weights.append(0.45)
    if e_exact is not None:
        parts.append(e_exact)
        weights.append(0.25)
    h2h_t = h2h.get((home, away))
    if h2h_t is not None:
        parts.append(h2h_t)
        weights.append(0.30)
    if parts:
        w = np.array(weights[: len(parts)])
        w /= w.sum()
        e_blend = float(np.dot(w, parts))
    else:
        e_blend = 2.57

    # Poisson split for supplemental top scores if CS thin
    lam_h = e_blend * 0.52
    lam_a = e_blend * 0.48
    poisson_top = []
    for h in range(4):
        for a in range(4):
            ph = math.exp(-lam_h) * lam_h**h / math.factorial(h)
            pa = math.exp(-lam_a) * lam_a**a / math.factorial(a)
            poisson_top.append((f"{h}:{a}", ph * pa))
    poisson_top.sort(key=lambda x: -x[1])
    poisson_top = [{"scoreline": s, "p": round(p, 4)} for s, p in poisson_top[:5]]

    top_final = top_cs if len(top_cs) >= 3 else poisson_top

    return {
        "event_id": eid,
        "home_team": home,
        "away_team": away,
        "E_total_ou_cdf": round(e_ou, 3) if e_ou is not None else None,
        "E_total_exact_goals": round(e_exact, 3) if e_exact is not None else None,
        "E_total_h2h": round(h2h_t, 3) if h2h_t is not None else None,
        "E_total_blend": round(e_blend, 3),
        "P_T_pmf_ou": [round(float(x), 4) for x in pmf_ou] if pmf_ou is not None else None,
        "top_scorelines_book_cs": top_cs[:3],
        "top_scorelines_model": top_final[:3],
        "actual_total": int(actual) if pd.notna(actual) else None,
    }


def main():
    h2h = load_h2h()
    raw = fetch_events(600)
    events = raw["event_id"].unique()[:500]
    rows = []
    for eid in events:
        g = raw[raw.event_id == eid]
        rows.append(predict_one(g, h2h))
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "deep_odds_expected_goals_scorelines.csv", index=False)

    sub = df.dropna(subset=["E_total_blend", "actual_total"])
    mae = float((sub["E_total_blend"] - sub["actual_total"]).abs().mean())
    within1 = float((sub["E_total_blend"] - sub["actual_total"]).abs().le(1).mean())

    report = {
        "n_fixtures": len(df),
        "mae_expected_total_vs_actual": round(mae, 3),
        "pct_within_1_goal": round(within1, 3),
        "logic": [
            "O/U lines de-vig → CDF → P(T=0..7) → E[T] (same as ou_integral_cdf)",
            "Exact goals de-vig → E[T] refine",
            "Correct Score de-vig → top 3 H:A (direct scoreline from book)",
            "H2H mean_total prior blend",
            "We CAN state expected goals; odd/even profit was separate failure",
        ],
        "sample": rows[:3],
    }
    (OUT / "deep_odds_expected_goals_report.json").write_text(json.dumps(report, indent=2))

    print(f"Fixtures: {len(df)}")
    print(f"MAE E[total] vs actual: {mae:.3f}")
    print(f"Within ±1 goal: {within1:.1%}")
    print("Sample:")
    for r in rows[:2]:
        print(
            f"  {r['home_team']} v {r['away_team']} E[T]={r['E_total_blend']} "
            f"actual={r['actual_total']} top={r['top_scorelines_book_cs'] or r['top_scorelines_model']}"
        )


if __name__ == "__main__":
    main()