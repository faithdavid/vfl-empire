#!/usr/bin/env python3
"""
Binary chains restructured by weight-class / top-8 table alignment.

Per MD: fixtures sorted so slot 1 = strongest table clash (both-in-top-8 first,
then lowest min rank). 30×8 = 240 bits per season; stack + compare to alpha order.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402
from common.weight_class_fixture_order import (  # noqa: E402
    order_md_fixtures_weight_class,
    rank_to_wc_label,
    replay_season_bits_wc,
    compute_table,
    apply_md,
    TEAMS_16,
)

OUT = EMPIRE / "surge-findings"
PLOTS = EMPIRE / "models" / "odd_even" / "plots"
OUT.mkdir(parents=True, exist_ok=True)
PLOTS.mkdir(parents=True, exist_ok=True)


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


def build_wc_chains(rows, last_n: int | None = None):
    by_season = defaultdict(list)
    for r in rows:
        by_season[r["season_name"]].append(r)

    seasons = sorted(by_season.keys())
    if last_n:
        seasons = seasons[-last_n:]

    lines = [
        "# WC-ordered binary (1=odd, 0=even)",
        "# MD slots: top-8 clashes first, then by min table rank entering MD",
        "",
    ]
    all_bits = []
    matrices = []
    ok_seasons = []

    for season in seasons:
        bits = replay_season_bits_wc(by_season[season])
        if not bits:
            continue
        ok_seasons.append(season)
        matrices.append(bits)
        lines.append(f"=== {season} ===")
        for md in range(30):
            chunk = bits[md * 8 : (md + 1) * 8]
            lines.append(f"  MD{md+1:02d} | {''.join(str(b) for b in chunk)}")
        lines.append(f"  CHAIN | {''.join(str(b) for b in bits)}")
        lines.append("")
        all_bits.extend(bits)

    return ok_seasons, np.array(matrices, dtype=np.int8), "\n".join(lines)


def sample_md_annotations(rows, season: str, md: int):
    """Show WC slot labels for one MD."""
    by_md = defaultdict(list)
    for r in rows:
        if r["season_name"] == season:
            by_md[int(r["matchday_number"])].append(r)

    points = {t: 0 for t in TEAMS_16}
    gd = {t: 0 for t in TEAMS_16}
    gf = {t: 0 for t in TEAMS_16}
    ranks_after = {0: {t: 9 for t in TEAMS_16}}
    for m in range(1, md):
        apply_md(points, gd, gf, by_md[m])
        ranks_after[m] = compute_table(points, gd, gf)
    ranks = ranks_after.get(md - 1, ranks_after[0])
    fixes = by_md[md]
    ordered = order_md_fixtures_weight_class(fixes, ranks)
    out = []
    for i, f in enumerate(ordered, 1):
        h, a = f["home_team"], f["away_team"]
        hr, ar = ranks.get(h, 9), ranks.get(a, 9)
        out.append(
            f"slot{i}: {h}(r{hr}/{rank_to_wc_label(hr)}) vs "
            f"{a}(r{ar}/{rank_to_wc_label(ar)}) -> {int(f['total_goals_odd'])}"
        )
    return out


def entropy_binary(p1):
    if p1 <= 0 or p1 >= 1:
        return 0.0
    p0 = 1 - p1
    return -(p0 * math.log2(p0) + p1 * math.log2(p1))


def markov(flat):
    trans = Counter()
    for i in range(len(flat) - 1):
        trans[(int(flat[i]), int(flat[i + 1]))] += 1
    n0 = trans[(0, 0)] + trans[(0, 1)]
    n1 = trans[(1, 0)] + trans[(1, 1)]
    return {
        "p01": trans[(0, 1)] / n0 if n0 else 0,
        "p11": trans[(1, 1)] / n1 if n1 else 0,
    }


def plot_wc_stack(X, col_p1, seasons):
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("WC-ordered stack (top-8 clash slots)", fontsize=11)
    show = X[-80:] if len(X) > 80 else X
    axes[0, 0].imshow(show, aspect="auto", cmap="RdYlGn_r", vmin=0, vmax=1)
    axes[0, 0].set_title("Seasons × 240 WC slots")
    axes[0, 0].set_xlabel("Slot 1–8 per MD block")
    for x in range(0, 240, 8):
        axes[0, 0].axvline(x - 0.5, color="white", alpha=0.2)

    axes[0, 1].plot(col_p1, lw=1)
    axes[0, 1].axhline(0.5, ls="--", color="gray")
    axes[0, 1].set_title("P(odd) per WC slot index")
    axes[0, 1].set_xlabel("bit 0=MD1 slot1 (top clash)")

    # Slot 1-8 only (aggregate within MD)
    slot_p = [X[:, s::8].mean() for s in range(8)]
    axes[1, 0].bar(range(1, 9), slot_p, color="steelblue")
    axes[1, 0].axhline(0.5, ls="--", color="gray")
    axes[1, 0].set_xlabel("WC slot within MD (1=top clash)")
    axes[1, 0].set_ylabel("P(odd) across all MDs & seasons")
    axes[1, 0].set_title("Marginal by clash tier slot")

    dev = np.abs(col_p1 - 0.5)
    axes[1, 1].hist(dev, bins=30, color="coral")
    axes[1, 1].set_title("|P(odd)-0.5| per WC bit index")

    plt.tight_layout()
    p = PLOTS / "stacked_season_binary_wc_analysis.png"
    fig.savefig(p, dpi=150)
    plt.close()
    return p, slot_p


def main():
    rows = load_rows()
    seasons, X, text = build_wc_chains(rows)
    (OUT / "odd_even_binary_chains_wc.txt").write_text(text)

    mega = []
    for s, row in zip(seasons, X):
        mega.append(f">{s}")
        mega.append("".join(str(int(b)) for b in row))
    (OUT / "odd_even_mega_stack_wc.txt").write_text("\n".join(mega))

    flat = X.flatten()
    col_p1 = X.mean(axis=0)
    mk = markov(flat)
    ent = entropy_binary(float(flat.mean()))
    plot_path, slot_p = plot_wc_stack(X, col_p1, seasons)

    # Compare slot 1 (elite clash) vs slot 8 (weakest clash)
    slot_stats = [
        {"wc_slot": i + 1, "p_odd": round(float(X[:, i::8].mean()), 4)}
        for i in range(8)
    ]

    ann = sample_md_annotations(rows, seasons[-1], 5) if seasons else []

    report = {
        "order": "top8_clash_then_min_rank",
        "n_seasons": int(len(seasons)),
        "global_p_odd": round(float(flat.mean()), 5),
        "entropy": round(ent, 5),
        "markov_p01": round(mk["p01"], 5),
        "markov_p11": round(mk["p11"], 5),
        "wc_slot_marginals": slot_stats,
        "slot1_vs_slot8_delta_pp": round((slot_stats[0]["p_odd"] - slot_stats[7]["p_odd"]) * 100, 2),
        "top_biased_wc_slots": sorted(slot_stats, key=lambda x: abs(x["p_odd"] - 0.5), reverse=True)[:4],
        "sample_md_annotation": {seasons[-1]: ann} if ann else {},
        "files": {
            "chains": str(OUT / "odd_even_binary_chains_wc.txt"),
            "mega": str(OUT / "odd_even_mega_stack_wc.txt"),
            "plot": str(plot_path),
        },
    }
    (OUT / "stacked_season_binary_wc_report.json").write_text(json.dumps(report, indent=2))

    print(f"WC stack: {len(seasons)} seasons × 240")
    print(f"P(odd)={flat.mean():.4f} entropy={ent:.4f}")
    print(f"Markov p01={mk['p01']:.4f} p11={mk['p11']:.4f}")
    print("WC slot P(odd):", [s["p_odd"] for s in slot_stats])
    print(f"Slot1-slot8 delta pp: {report['slot1_vs_slot8_delta_pp']}")
    if ann:
        print("Sample", seasons[-1], "MD5:")
        for line in ann:
            print(" ", line)


if __name__ == "__main__":
    main()