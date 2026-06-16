"""
Deep prematch → E[total goals], top scorelines, O2.5 lean.

Works from MSport event markets list (live API) or flat odds dict + optional CS rows.
"""
from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

SCORE_RE = re.compile(r"^(\d+):(\d+)$")
GLOBAL_P_T = np.array([0.074, 0.190, 0.253, 0.220, 0.148, 0.073, 0.035, 0.007])
GLOBAL_P_T /= GLOBAL_P_T.sum()

_H2H_CACHE: dict[tuple[str, str], float] | None = None


def devig(odds: list[float]) -> np.ndarray | None:
    if not odds or any(x is None or float(x) <= 1 for x in odds):
        return None
    q = np.array([1.0 / float(x) for x in odds])
    s = q.sum()
    return q / s if s > 0 else None


def pmf_from_ou(p_le1: float, p_le2: float, p_le3: float | None = None) -> np.ndarray:
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


def load_h2h_prior() -> dict[tuple[str, str], float]:
    global _H2H_CACHE
    if _H2H_CACHE is not None:
        return _H2H_CACHE
    from pathlib import Path

    p = Path(__file__).resolve().parents[1] / ".." / "surge-findings" / "team_vs_opponent_scoring_combined.csv"
    p = p.resolve()
    _H2H_CACHE = {}
    if p.exists():
        import pandas as pd

        df = pd.read_csv(p)
        for r in df.itertuples():
            _H2H_CACHE[(r.team, r.opponent)] = float(r.mean_total)
    return _H2H_CACHE


def _parse_msport_markets(markets: list[dict]) -> dict[str, Any]:
    """Flatten MSport event markets into lookup structures."""
    ou: dict[str, tuple[float | None, float | None]] = {}
    cs_rows: list[tuple[str, float]] = []
    eg_rows: list[tuple[int, float]] = []

    for mk in markets or []:
        name = (mk.get("name") or "").strip()
        spec = (mk.get("specifiers") or "").strip()
        for o in mk.get("outcomes") or []:
            desc = (o.get("description") or o.get("name") or "").strip()
            raw = o.get("odds") or o.get("price")
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if val <= 1.0:
                continue

            if name == "Over/Under":
                line = None
                if "1.5" in spec or desc.endswith("1.5"):
                    line = "1.5"
                elif "2.5" in spec or desc.endswith("2.5"):
                    line = "2.5"
                elif "3.5" in spec or desc.endswith("3.5"):
                    line = "3.5"
                if line:
                    o_key, u_key = ou.setdefault(line, (None, None))
                    if desc.startswith("Over"):
                        ou[line] = (val, u_key)
                    elif desc.startswith("Under"):
                        ou[line] = (o_key, val)
            elif name == "Correct Score":
                m = SCORE_RE.match(desc.replace("-", ":"))
                if m:
                    cs_rows.append((f"{m.group(1)}:{m.group(2)}", val))
            elif name == "Exact goals":
                s = desc.replace("+", "")
                if s.isdigit():
                    eg_rows.append((int(s), val))

    return {"ou": ou, "cs_rows": cs_rows, "eg_rows": eg_rows}


def predict_from_odds_dict(
    home: str,
    away: str,
    odds_dict: dict[str, Any],
    markets: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Build deep goals pick from shallow odds_dict and/or full MSport markets.
    """
    parsed = _parse_msport_markets(markets or [])
    ou = parsed["ou"]

    def pair(line: str, o_key: str, u_key: str):
        if line in ou and ou[line][0] and ou[line][1]:
            return ou[line]
        o, u = odds_dict.get(o_key), odds_dict.get(u_key)
        if o and u:
            return float(o), float(u)
        return None, None

    p_o15, p_u15 = pair("1.5", "o15", "u15")
    p_o25, p_u25 = pair("2.5", "o25", "u25")
    p_o35, p_u35 = pair("3.5", "o35", "u35")

    pmf_ou = e_ou = None
    p_over25 = None
    if p_u15 is not None and p_u25 is not None:
        dv_u15 = devig([p_o15, p_u15])  # type: ignore
        dv_u25 = devig([p_o25, p_u25])  # type: ignore
        if dv_u15 is not None and dv_u25 is not None:
            p_le1, p_le2 = float(dv_u15[1]), float(dv_u25[1])
            p_le3 = None
            if p_u35 is not None and p_o35 is not None:
                dv3 = devig([p_o35, p_u35])
                if dv3 is not None:
                    p_le3 = float(dv3[1])
            pmf_ou = pmf_from_ou(p_le1, p_le2, p_le3)
            e_ou = float((np.arange(8) * pmf_ou).sum())
            p_over25 = float(dv_u25[0])

    e_exact = None
    if len(parsed["eg_rows"]) >= 4:
        sels, ods = zip(*parsed["eg_rows"])
        p = devig(list(ods))
        if p is not None:
            e_exact = float(sum(s * pr for s, pr in zip(sels, p)))

    top_cs: list[dict] = []
    if len(parsed["cs_rows"]) >= 5:
        odds = [x[1] for x in parsed["cs_rows"]]
        p = devig(odds)
        if p is not None:
            for (sc, _), pr in sorted(zip(parsed["cs_rows"], p), key=lambda x: -x[1])[:5]:
                top_cs.append({"scoreline": sc, "p": round(float(pr), 4)})

    h2h = load_h2h_prior()
    h2h_t = h2h.get((home, away))

    parts, weights = [], []
    if e_ou is not None:
        parts.append(e_ou)
        weights.append(0.45)
    if e_exact is not None:
        parts.append(e_exact)
        weights.append(0.25)
    if h2h_t is not None:
        parts.append(h2h_t)
        weights.append(0.30)
    if parts:
        w = np.array(weights[: len(parts)])
        w /= w.sum()
        e_blend = float(np.dot(w, parts))
    elif e_ou is not None:
        e_blend = e_ou
    else:
        e_blend = h2h_t if h2h_t is not None else 2.57

    if len(top_cs) < 3:
        lam_h = e_blend * 0.52
        lam_a = e_blend * 0.48
        poisson_top = []
        for h in range(4):
            for a in range(4):
                ph = math.exp(-lam_h) * lam_h**h / math.factorial(h)
                pa = math.exp(-lam_a) * lam_a**a / math.factorial(a)
                poisson_top.append((f"{h}:{a}", ph * pa))
        poisson_top.sort(key=lambda x: -x[1])
        top_cs = [{"scoreline": s, "p": round(p, 4)} for s, p in poisson_top[:3]]

    p_odd = None
    if pmf_ou is not None:
        p_odd = float(pmf_ou[1] + pmf_ou[3] + pmf_ou[5] + pmf_ou[7])

    o25_lean = "Over 2.5" if (p_over25 or 0) >= 0.5 else "Under 2.5"
    if p_over25 is None and pmf_ou is not None:
        p_over25 = float(1.0 - pmf_ou[0] - pmf_ou[1] - pmf_ou[2])
        o25_lean = "Over 2.5" if p_over25 >= 0.5 else "Under 2.5"

    mood = "high" if e_blend >= 2.85 else ("low" if e_blend <= 2.2 else "neutral")

    return {
        "E_total_blend": round(e_blend, 2),
        "E_total_ou": round(e_ou, 2) if e_ou is not None else None,
        "E_total_h2h": round(h2h_t, 2) if h2h_t is not None else None,
        "p_over25": round(p_over25, 3) if p_over25 is not None else None,
        "o25_lean": o25_lean,
        "p_odd_total": round(p_odd, 3) if p_odd is not None else None,
        "scoring_mood": mood,
        "top_scorelines": top_cs[:3],
        "pipeline": "deep_goals_v1",
    }


def format_scorelines_short(top: list[dict]) -> str:
    if not top:
        return "—"
    parts = []
    for t in top:
        pct = t.get("p", 0) * 100
        parts.append(f"{t.get('scoreline', '?')} ({pct:.0f}%)")
    return ", ".join(parts)