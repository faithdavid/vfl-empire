#!/usr/bin/env python3
"""
Binary Odd/Even chains: 1 = odd total goals, 0 = even.
Ordered by season → matchday → fixture (home_team sort).
MD boundaries and season boundaries marked in output.
"""
from __future__ import annotations

import sys
from pathlib import Path

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db  # noqa: E402

OUT = EMPIRE / "surge-findings"
OUT.mkdir(parents=True, exist_ok=True)


def load_ordered():
    sql = """
    SELECT season_name, matchday_number, home_team, away_team, total_goals_odd
    FROM v_results_odd_even_ready
    ORDER BY season_name, matchday_number, home_team
    """
    with get_db() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def build_chains(rows, seasons_limit: int | None = None, one_season: str | None = None):
    from collections import defaultdict

    by_season_md = defaultdict(list)
    for r in rows:
        by_season_md[(r["season_name"], int(r["matchday_number"]))].append(r)

    seasons = sorted({k[0] for k in by_season_md})
    if one_season:
        seasons = [s for s in seasons if s == one_season]
    if seasons_limit:
        seasons = seasons[-seasons_limit:]

    lines = []
    lines.append("# VFL Odd/Even binary chains (1=odd, 0=even)")
    lines.append("# Fixture order within MD: alphabetical by home_team")
    lines.append("# --- = end of matchday | === = end of season")
    lines.append("")

    global_bits = []

    for season in seasons:
        mds = sorted({k[1] for k in by_season_md if k[0] == season})
        season_bits = []
        lines.append(f"=== SEASON {season} ===")
        for md in mds:
            fixes = by_season_md[(season, md)]
            if len(fixes) != 8:
                lines.append(f"  MD{md:02d} [SKIP incomplete n={len(fixes)}]")
                continue
            bits = [str(int(f["total_goals_odd"])) for f in fixes]
            bitstr = "".join(bits)
            season_bits.append(bitstr)
            global_bits.extend(bits)
            # Annotated line: MD label + binary + spaced for read
            spaced = " ".join(bits)
            lines.append(f"  MD{md:02d} | {bitstr} | {spaced}")
        lines.append(f"  SEASON_CHAIN: {''.join(season_bits)}")
        lines.append(f"  SEASON_LEN: {len(''.join(season_bits))} bits ({len(mds)} MDs)")
        lines.append("")

    lines.append("=== GLOBAL (last N seasons concatenated) ===")
    g = "".join(global_bits)
    lines.append(f"LEN={len(g)}")
    # Wrap 64 chars per line for readability
    for i in range(0, len(g), 64):
        lines.append(g[i : i + 64])
    return "\n".join(lines), g


def build_compact_md_season_markers(rows, last_seasons: int = 5):
    """One line per season with | between MDs."""
    from collections import defaultdict

    by_season_md = defaultdict(list)
    for r in rows:
        by_season_md[(r["season_name"], int(r["matchday_number"]))].append(r)

    seasons = sorted({k[0] for k in by_season_md})[-last_seasons:]
    out = []
    out.append("COMPACT: each token is one MD (8 bits); | = MD boundary; || = season boundary")
    for season in seasons:
        mds = sorted({k[1] for k in by_season_md if k[0] == season})
        md_tokens = []
        for md in mds:
            fixes = by_season_md[(season, md)]
            if len(fixes) != 8:
                continue
            md_tokens.append("".join(str(int(f["total_goals_odd"])) for f in fixes))
        out.append(f"{season}")
        out.append("|".join(md_tokens))
        out.append("||")
    return "\n".join(out)


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--seasons", type=int, default=10, help="last N seasons in full dump")
    p.add_argument("--one", type=str, default=None, help="single season e.g. 'VFLM 5405'")
    p.add_argument("--compact", type=int, default=8, help="compact view: last N seasons")
    args = p.parse_args()

    rows = load_ordered()
    text, _ = build_chains(rows, seasons_limit=args.seasons, one_season=args.one)
    path = OUT / "odd_even_binary_chains.txt"
    path.write_text(text)

    compact = build_compact_md_season_markers(rows, last_seasons=args.compact)
    cpath = OUT / "odd_even_binary_compact.txt"
    cpath.write_text(compact)

    print(path)
    print(cpath)
    print("--- sample (last season in compact) ---")
    print("\n".join(compact.split("\n")[-6:]))


if __name__ == "__main__":
    main()