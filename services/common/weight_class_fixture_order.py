"""
Weight-class fixture ordering for binary chains.

Within each MD, fixtures are sorted by **live table entering MD** (top-8 focus):
  1) Both teams in top 8 first (elite clashes)
  2) Then min(home_rank, away_rank) ascending
  3) Then max rank, then home_rank

Static innate tier (T1–T4) used only as tie-breaker via team name.
"""
from __future__ import annotations

from collections import defaultdict

TEAMS_16 = [
    "London Guns", "Liverpool", "Manchester Blue", "Manchester Red",
    "Chelsea", "Tottenham", "Aston Villa", "Everton",
    "West Ham", "Brighton", "Leeds", "Wolverhampton",
    "Crystal Palace", "Newcastle", "Fulham", "Bournemouth",
]

# Innate static tier (oracle) — tie-break only
STATIC_TIER = {
    "Manchester Blue": 1, "Liverpool": 1, "Manchester Red": 1,
    "Chelsea": 1, "Tottenham": 1, "London Guns": 1,
    "Aston Villa": 2, "Everton": 2, "West Ham": 2, "Brighton": 2,
    "Leeds": 3, "Wolverhampton": 3, "Crystal Palace": 3, "Newcastle": 3,
    "Fulham": 4, "Bournemouth": 4,
}

WC_LABEL = {1: "HW", 2: "UMW", 3: "LMW", 4: "FW"}


def compute_table(points, gd, gf):
    def key(t):
        return (-points[t], -gd[t], -gf[t], t)
    ordered = sorted(points.keys(), key=key)
    return {t: i + 1 for i, t in enumerate(ordered)}


def apply_md(points, gd, gf, fixtures):
    for f in fixtures:
        h, a = f["home_team"], f["away_team"]
        hg, ag = int(f["home_goals"]), int(f["away_goals"])
        gf[h] += hg
        gf[a] += ag
        gd[h] += hg - ag
        gd[a] += ag - hg
        if hg > ag:
            points[h] += 3
        elif hg < ag:
            points[a] += 3
        else:
            points[h] += 1
            points[a] += 1


def rank_to_wc_label(rank: int) -> str:
    if rank <= 4:
        return "HW"
    if rank <= 8:
        return "UMW"
    if rank <= 12:
        return "LMW"
    return "FW"


def fixture_wc_sort_key(f, h_rank: int, a_rank: int) -> tuple:
    both_top8 = int(h_rank <= 8 and a_rank <= 8)
    min_r = min(h_rank, a_rank)
    max_r = max(h_rank, a_rank)
    st = STATIC_TIER.get(f["home_team"], 3) + STATIC_TIER.get(f["away_team"], 3)
    return (-both_top8, min_r, max_r, st, h_rank, f["home_team"])


def order_md_fixtures_weight_class(fixtures, ranks_before_md: dict[str, int]) -> list:
    """Return fixtures sorted by top-8 / table weight (slot 0 = highest clash)."""
    enriched = []
    for f in fixtures:
        h, a = f["home_team"], f["away_team"]
        hr, ar = ranks_before_md.get(h, 9), ranks_before_md.get(a, 9)
        enriched.append((fixture_wc_sort_key(f, hr, ar), f, hr, ar))
    enriched.sort(key=lambda x: x[0])
    return [x[1] for x in enriched]


def replay_season_bits_wc(rows_for_season: list) -> list[int] | None:
    """240 bits in WC order, or None if incomplete."""
    by_md = defaultdict(list)
    for r in rows_for_season:
        by_md[int(r["matchday_number"])].append(r)

    points = {t: 0 for t in TEAMS_16}
    gd = {t: 0 for t in TEAMS_16}
    gf = {t: 0 for t in TEAMS_16}
    ranks_after = {0: {t: 9 for t in TEAMS_16}}

    bits = []
    for md in range(1, 31):
        md_fix = by_md.get(md, [])
        if len(md_fix) != 8:
            return None
        ranks = ranks_after.get(md - 1, ranks_after[0])
        ordered = order_md_fixtures_weight_class(md_fix, ranks)
        bits.extend(int(f["total_goals_odd"]) for f in ordered)
        apply_md(points, gd, gf, md_fix)
        ranks_after[md] = compute_table(points, gd, gf)

    return bits if len(bits) == 240 else None