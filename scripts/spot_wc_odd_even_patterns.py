#!/usr/bin/env python3
"""
Weight-class ordering exists to SPOT patterns → odd/even full-time goals.

For each fixture (entering-MD table ranks):
  - WC bucket: HW(1-4), UMW(5-8), LMW(9-12), FW(13-16)
  - Clash pattern: home_bucket × away_bucket (e.g. HW×FW)
  - WC slot 1-8 within MD (top clash first)

Outputs: heatmaps, ranked patterns, per-season pattern chains for eyeballing.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402
from common.weight_class_fixture_order import (  # noqa: E402
    TEAMS_16,
    apply_md,
    compute_table,
    order_md_fixtures_weight_class,
    rank_to_wc_label,
)

OUT = EMPIRE / "surge-findings"
PLOTS = EMPIRE / "models" / "odd_even" / "plots"
BUCKETS = ["HW", "UMW", "LMW", "FW"]
BI = {b: i for i, b in enumerate(BUCKETS)}


def rank_bucket(rank: int) -> str:
    return rank_to_wc_label(rank)


def load_rows():
    sql = """
    SELECT season_name, matchday_number, home_team, away_team,
           home_goals, away_goals, total_goals_odd
    FROM v_results_odd_even_ready
    ORDER BY season_name, matchday_number, home_team
    """
    with get_db() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def replay_wc_fixtures(rows_for_season: list) -> list[dict] | None:
    by_md = defaultdict(list)
    for r in rows_for_season:
        by_md[int(r["matchday_number"])].append(r)

    points = {t: 0 for t in TEAMS_16}
    gd = {t: 0 for t in TEAMS_16}
    gf = {t: 0 for t in TEAMS_16}
    ranks_after = {0: {t: 9 for t in TEAMS_16}}

    out = []
    season_name = rows_for_season[0]["season_name"]
    for md in range(1, 31):
        md_fix = by_md.get(md, [])
        if len(md_fix) != 8:
            return None
        ranks = ranks_after.get(md - 1, ranks_after[0])
        ordered = order_md_fixtures_weight_class(md_fix, ranks)
        for slot, f in enumerate(ordered, 1):
            h, a = f["home_team"], f["away_team"]
            hr, ar = ranks.get(h, 9), ranks.get(a, 9)
            hb, ab = rank_bucket(hr), rank_bucket(ar)
            both_top8 = hr <= 8 and ar <= 8
            min_r = min(hr, ar)
            out.append({
                "season": season_name,
                "md": md,
                "wc_slot": slot,
                "home": h,
                "away": a,
                "h_rank": hr,
                "a_rank": ar,
                "h_bucket": hb,
                "a_bucket": ab,
                "clash": f"{hb}×{ab}",
                "both_top8": both_top8,
                "min_rank": min_r,
                "odd": int(f["total_goals_odd"]),
            })
        apply_md(points, gd, gf, md_fix)
        ranks_after[md] = compute_table(points, gd, gf)

    return out if len(out) == 240 else None


def aggregate(fixtures: list[dict]) -> dict:
    clash = defaultdict(lambda: {"n": 0, "odd": 0})
    slot = defaultdict(lambda: {"n": 0, "odd": 0})
    slot_clash = defaultdict(lambda: {"n": 0, "odd": 0})
    top8 = defaultdict(lambda: {"n": 0, "odd": 0})

    matrix = np.zeros((4, 4, 2))

    for f in fixtures:
        o = f["odd"]
        clash[f["clash"]]["n"] += 1
        clash[f["clash"]]["odd"] += o
        slot[f["wc_slot"]]["n"] += 1
        slot[f["wc_slot"]]["odd"] += o
        key = (f["wc_slot"], f["clash"])
        slot_clash[key]["n"] += 1
        slot_clash[key]["odd"] += o
        t8 = "top8_both" if f["both_top8"] else "not_top8_both"
        top8[t8]["n"] += 1
        top8[t8]["odd"] += o
        hi, ai = BI[f["h_bucket"]], BI[f["a_bucket"]]
        matrix[hi, ai, 0] += 1
        matrix[hi, ai, 1] += o

    def to_pct(d):
        rows = []
        for k, v in d.items():
            n, od = v["n"], v["odd"]
            if n < 30:
                continue
            p = od / n
            rows.append({
                "key": k if not isinstance(k, tuple) else f"slot{k[0]}_{k[1]}",
                "n": n,
                "p_odd": round(p, 4),
                "p_even": round(1 - p, 4),
                "lean": "ODD" if p >= 0.5 else "EVEN",
                "edge_pp": round(abs(p - 0.5) * 100, 2),
            })
        return sorted(rows, key=lambda x: x["edge_pp"], reverse=True)

    return {
        "clash": to_pct(clash),
        "wc_slot": to_pct({str(k): v for k, v in slot.items()}),
        "slot_clash": to_pct(slot_clash),
        "top8_flag": to_pct(top8),
        "matrix_n": matrix[:, :, 0].tolist(),
        "matrix_p_odd": np.where(
            matrix[:, :, 0] > 0,
            matrix[:, :, 1] / matrix[:, :, 0],
            np.nan,
        ).tolist(),
    }


def build_pattern_chains(all_fixtures: list[dict], last_seasons: int = 8):
    by_season = defaultdict(list)
    for f in all_fixtures:
        by_season[f["season"]].append(f)
    seasons = sorted(by_season.keys())[-last_seasons:]
    lines = [
        "# WC pattern chains — spot what leads to odd (1) vs even (0) goals",
        "# MD: 8 bits = WC slots 1..8 | tokens = slot:HW×FW:bit",
        "",
    ]
    for s in seasons:
        fixes = sorted(by_season[s], key=lambda x: (x["md"], x["wc_slot"]))
        lines.append(f"=== {s} ===")
        for md in range(1, 31):
            chunk = [x for x in fixes if x["md"] == md]
            bits = "".join(str(x["odd"]) for x in chunk)
            tokens = " ".join(f"{x['wc_slot']}:{x['clash']}:{x['odd']}" for x in chunk)
            lines.append(f"  MD{md:02d} {bits} | {tokens}")
        lines.append("")
    return "\n".join(lines)


def html_report(agg: dict, top_clash: list, top_slot_clash: list) -> str:
    def table(rows, cols):
        h = "<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
        body = ""
        for r in rows[:40]:
            body += "<tr>" + "".join(f"<td>{r.get(c,'')}</td>" for c in cols) + "</tr>"
        return f"<table border='1' cellpadding='4'>{h}{body}</table>"

    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>WC patterns → odd/even</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#e6edf3;padding:1rem}}
table{{border-collapse:collapse}} th{{background:#21262d}}</style></head><body>
<h1>Weight-class patterns → full-time odd/even goals</h1>
<p>Fixtures ordered by table clash so you can <strong>spot</strong> which weight-class meetings skew scoring parity.</p>
<h2>Clash patterns (home WC × away WC)</h2>
{table(top_clash, ['key','n','p_odd','p_even','lean','edge_pp'])}
<h2>WC slot on slate (1 = strongest clash)</h2>
{table(agg['wc_slot'], ['key','n','p_odd','p_even','lean','edge_pp'])}
<h2>Slot + clash (best for spotting repeats)</h2>
{table(top_slot_clash[:35], ['key','n','p_odd','p_even','lean','edge_pp'])}
<h2>Both teams top-8 at kickoff</h2>
{table(agg['top8_flag'], ['key','n','p_odd','p_even','lean','edge_pp'])}
</body></html>"""


def plot_matrix_fixed(matrix_p, matrix_n, slot_stats):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Spot patterns: WC clash → odd/even goals", fontsize=11)
    data = np.array(matrix_p)
    nmat = np.array(matrix_n)
    im = axes[0].imshow(data, cmap="RdYlGn_r", vmin=0.46, vmax=0.54)
    axes[0].set_xticks(range(4))
    axes[0].set_yticks(range(4))
    axes[0].set_xticklabels(BUCKETS)
    axes[0].set_yticklabels(BUCKETS)
    axes[0].set_title("P(odd) by clash type")
    for i in range(4):
        for j in range(4):
            if not np.isnan(data[i, j]) and nmat[i, j] >= 100:
                axes[0].text(j, i, f"{data[i,j]:.1%}", ha="center", va="center", fontsize=9, color="white")
    plt.colorbar(im, ax=axes[0], fraction=0.046)

    pvals = [x["p_odd"] for x in sorted(slot_stats, key=lambda x: int(x["key"]))]
    axes[1].bar(range(1, 9), pvals, color="steelblue")
    axes[1].axhline(0.5, ls="--", color="gray")
    axes[1].set_xticks(range(1, 9))
    axes[1].set_title("P(odd) by WC slot (1=top clash)")
    axes[1].set_ylabel("P(odd)")

    plt.tight_layout()
    p = PLOTS / "wc_clash_pattern_odd_even.png"
    fig.savefig(p, dpi=150)
    plt.close()
    return p


def main():
    rows = load_rows()
    by_season = defaultdict(list)
    for r in rows:
        by_season[r["season_name"]].append(r)

    all_fix = []
    for season in sorted(by_season.keys()):
        fx = replay_wc_fixtures(by_season[season])
        if fx:
            all_fix.extend(fx)

    agg = aggregate(all_fix)
    chains = build_pattern_chains(all_fix, 8)
    (OUT / "wc_pattern_chains_spot.txt").write_text(chains)

    plot_path = plot_matrix_fixed(agg["matrix_p_odd"], agg["matrix_n"], agg["wc_slot"])

    top_clash = agg["clash"][:16]
    top_sc = agg["slot_clash"][:25]

    (OUT / "wc_odd_even_pattern_spot.html").write_text(html_report(agg, top_clash, top_sc))

    report = {
        "purpose": "WC order to spot patterns leading to odd vs even full-time goals",
        "n_fixtures": len(all_fix),
        "top_clash_patterns": top_clash[:12],
        "wc_slots": agg["wc_slot"],
        "best_slot_clash_combos": top_sc[:15],
        "top8_both": agg["top8_flag"],
        "how_to_read": [
            "Each MD: 8 bits left-to-right = WC slots 1..8 (elite clash first).",
            "Spot same clash string across seasons in wc_pattern_chains_spot.txt.",
            "4×4 heatmap = stable home×away bucket bias (n shown in cells).",
            "edge_pp = |P(odd)-0.5|; tables filter n≥30.",
        ],
        "files": {
            "chains": str(OUT / "wc_pattern_chains_spot.txt"),
            "html": str(OUT / "wc_odd_even_pattern_spot.html"),
            "plot": str(plot_path),
        },
    }
    (OUT / "wc_odd_even_pattern_spot_report.json").write_text(json.dumps(report, indent=2))

    print(f"Fixtures: {len(all_fix)}")
    print("Top clash patterns:")
    for r in top_clash[:8]:
        print(f"  {r['key']:12} n={r['n']:5} P(odd)={r['p_odd']:.3f} lean={r['lean']} edge={r['edge_pp']}pp")
    print("WC slots:")
    for r in sorted(agg["wc_slot"], key=lambda x: int(x["key"])):
        print(f"  slot {r['key']} P(odd)={r['p_odd']:.3f} n={r['n']}")
    print(f"Chains: {OUT / 'wc_pattern_chains_spot.txt'}")


if __name__ == "__main__":
    main()