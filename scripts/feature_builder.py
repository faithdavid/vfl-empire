#!/usr/bin/env python3
"""
feature_builder.py — Rich Per-Fixture Feature Engineering for VFL Prediction
==============================================================================
Builds a comprehensive feature vector for each VFL fixture using:
  - League table: rank, points, form, GF/GA rates
  - H2H history: win rates, goal patterns, market hit rates
  - Odds data: implied probabilities, line movement
  - Season context: regime, goals-per-game, over rates

Output: DataFrame with one row per prediction, ready for ML training.

Usage:
    python feature_builder.py --export /tmp/vfl_rich_features.csv
    python feature_builder.py --fixture "Chelsea" "Liverpool" --matchday 15

Author: VFL Engineering — Lord FaithDavid's Empire
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))
from common.db_manager import get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [FEATURES] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("features")

# ═══════════════════════════════════════════════════════════════════════════════
# LEAGUE TABLE FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

def _form_score(form_str: str, n: int = 5) -> float:
    """Convert form string 'WDLWW' → score [0,1]. W=3, D=1, L=0 per 3*n max."""
    if not form_str:
        return 0.5
    pts = {"W": 3, "D": 1, "L": 0}
    chars = [c for c in form_str.upper() if c in pts][-n:]
    if not chars:
        return 0.5
    total = sum(pts[c] for c in chars)
    return total / (3.0 * len(chars))

def get_league_features(matchday_id: int) -> Dict[str, Dict]:
    """
    Returns dict keyed by team_name → {rank, points, played, form_score,
    goals_per_game, goals_against_per_game, goal_diff_per_game, ...}
    """
    with get_db() as cur:
        cur.execute("""
            SELECT team_name, rank, points, played, won, draw, lost,
                   goals_for, goals_against, goal_diff, form
            FROM vfl_league_snapshots
            WHERE matchday_id = %s
        """, (matchday_id,))
        rows = cur.fetchall()

    features = {}
    for (team, rank, pts, played, won, draw, lost,
         gf, ga, gd, form) in rows:
        p = max(played or 1, 1)
        features[team.lower()] = {
            "rank": rank or 10,
            "points": pts or 0,
            "played": played or 0,
            "won": won or 0,
            "draw": draw or 0,
            "lost": lost or 0,
            "goals_for": gf or 0,
            "goals_against": ga or 0,
            "goal_diff": gd or 0,
            "goals_per_game": round((gf or 0) / p, 3),
            "goals_against_per_game": round((ga or 0) / p, 3),
            "goal_diff_per_game": round((gd or 0) / p, 3),
            "win_rate": round((won or 0) / p, 3),
            "draw_rate": round((draw or 0) / p, 3),
            "loss_rate": round((lost or 0) / p, 3),
            "form_score": _form_score(form or ""),
            "points_per_game": round((pts or 0) / p, 3),
        }
    return features

# ═══════════════════════════════════════════════════════════════════════════════
# H2H FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

_h2h_cache: Dict[Tuple[str, str], Dict] = {}

def _normalize_team(name: str) -> str:
    aliases = {
        "man city": "manchester blue",
        "manchester city": "manchester blue",
        "man utd": "manchester red",
        "manchester united": "manchester red",
        "arsenal": "london guns",
        "wolves": "wolverhampton",
    }
    n = name.strip().lower()
    return aliases.get(n, n)

def get_h2h_features(home: str, away: str, min_games: int = 3) -> Dict:
    """
    H2H stats for this exact matchup (both directions) from vfl_results_v2.
    """
    hn = _normalize_team(home)
    an = _normalize_team(away)
    key = (hn, an)

    if key in _h2h_cache:
        return _h2h_cache[key]

    with get_db() as cur:
        cur.execute("""
            SELECT r.home_goals, r.away_goals,
                   LOWER(r.home_team), LOWER(r.away_team)
            FROM vfl_results_v2 r
            WHERE (LOWER(r.home_team) = %s AND LOWER(r.away_team) = %s)
               OR (LOWER(r.home_team) = %s AND LOWER(r.away_team) = %s)
        """, (hn, an, an, hn))
        rows = cur.fetchall()

    n = len(rows)
    if n < min_games:
        # Fall back to individual team stats if H2H sparse
        result = _get_team_goal_stats(home, away)
        _h2h_cache[key] = result
        return result

    home_wins = draws = away_wins = 0
    totals = []
    for (hg, ag, rh, ra) in rows:
        total = (hg or 0) + (ag or 0)
        totals.append(total)
        if rh == hn:
            # home team perspective
            if (hg or 0) > (ag or 0):
                home_wins += 1
            elif (hg or 0) == (ag or 0):
                draws += 1
            else:
                away_wins += 1
        else:
            # reversed perspective
            if (ag or 0) > (hg or 0):
                home_wins += 1
            elif (hg or 0) == (ag or 0):
                draws += 1
            else:
                away_wins += 1

    avg_goals = np.mean(totals)
    std_goals = np.std(totals)

    result = {
        "h2h_count": n,
        "h2h_home_win_rate": round(home_wins / n, 3),
        "h2h_draw_rate": round(draws / n, 3),
        "h2h_away_win_rate": round(away_wins / n, 3),
        "h2h_avg_goals": round(avg_goals, 3),
        "h2h_std_goals": round(std_goals, 3),
        "h2h_over_05_rate": round(sum(1 for t in totals if t > 0.5) / n, 3),
        "h2h_over_15_rate": round(sum(1 for t in totals if t > 1.5) / n, 3),
        "h2h_over_25_rate": round(sum(1 for t in totals if t > 2.5) / n, 3),
        "h2h_over_35_rate": round(sum(1 for t in totals if t > 3.5) / n, 3),
        "h2h_over_45_rate": round(sum(1 for t in totals if t > 4.5) / n, 3),
        "h2h_under_15_rate": round(sum(1 for t in totals if t < 1.5) / n, 3),
        "h2h_under_25_rate": round(sum(1 for t in totals if t < 2.5) / n, 3),
        "h2h_under_35_rate": round(sum(1 for t in totals if t < 3.5) / n, 3),
        "h2h_gg_rate": round(sum(1 for hg, ag, _, __ in rows if (hg or 0) > 0 and (ag or 0) > 0) / n, 3),
        "h2h_ng_rate": round(sum(1 for hg, ag, _, __ in rows if (hg or 0) == 0 or (ag or 0) == 0) / n, 3),
        "h2h_data_quality": min(n / 20.0, 1.0),  # confidence in H2H data
    }
    _h2h_cache[key] = result
    return result

def _get_team_goal_stats(home: str, away: str) -> Dict:
    """Fallback: use each team's individual goal stats when H2H sparse."""
    hn = _normalize_team(home)
    an = _normalize_team(away)

    with get_db() as cur:
        # Home team stats as home
        cur.execute("""
            SELECT AVG(r.home_goals + r.away_goals),
                   AVG(CASE WHEN r.home_goals + r.away_goals > 1.5 THEN 1.0 ELSE 0.0 END),
                   AVG(CASE WHEN r.home_goals + r.away_goals > 2.5 THEN 1.0 ELSE 0.0 END),
                   AVG(CASE WHEN r.home_goals + r.away_goals < 3.5 THEN 1.0 ELSE 0.0 END),
                   COUNT(*)
            FROM vfl_results_v2 r
            WHERE LOWER(r.home_team) = %s
        """, (hn,))
        hr = cur.fetchone()

        cur.execute("""
            SELECT AVG(r.home_goals + r.away_goals),
                   AVG(CASE WHEN r.home_goals + r.away_goals > 1.5 THEN 1.0 ELSE 0.0 END),
                   AVG(CASE WHEN r.home_goals + r.away_goals > 2.5 THEN 1.0 ELSE 0.0 END),
                   AVG(CASE WHEN r.home_goals + r.away_goals < 3.5 THEN 1.0 ELSE 0.0 END),
                   COUNT(*)
            FROM vfl_results_v2 r
            WHERE LOWER(r.away_team) = %s
        """, (an,))
        ar = cur.fetchone()

    def safe(v, default=0.5): return float(v) if v is not None else default

    avg_g = (safe(hr[0], 2.0) + safe(ar[0], 2.0)) / 2
    o15 = (safe(hr[1], 0.7) + safe(ar[1], 0.7)) / 2
    o25 = (safe(hr[2], 0.5) + safe(ar[2], 0.5)) / 2
    u35 = (safe(hr[3], 0.7) + safe(ar[3], 0.7)) / 2
    n = min(safe(hr[4] if hr else 0, 0), safe(ar[4] if ar else 0, 0))

    return {
        "h2h_count": int(n),
        "h2h_home_win_rate": 0.4,
        "h2h_draw_rate": 0.25,
        "h2h_away_win_rate": 0.35,
        "h2h_avg_goals": round(avg_g, 3),
        "h2h_std_goals": 1.2,
        "h2h_over_05_rate": 0.95,
        "h2h_over_15_rate": round(o15, 3),
        "h2h_over_25_rate": round(o25, 3),
        "h2h_over_35_rate": round(1 - u35, 3),
        "h2h_over_45_rate": 0.2,
        "h2h_under_15_rate": round(1 - o15, 3),
        "h2h_under_25_rate": round(1 - o25, 3),
        "h2h_under_35_rate": round(u35, 3),
        "h2h_gg_rate": 0.55,
        "h2h_ng_rate": 0.45,
        "h2h_data_quality": 0.3,  # low quality — no direct H2H
    }

# ═══════════════════════════════════════════════════════════════════════════════
# SEASON / REGIME FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

_season_stats_cache: Dict[str, Dict] = {}

def get_season_stats(season_name: str) -> Dict:
    if season_name in _season_stats_cache:
        return _season_stats_cache[season_name]

    with get_db() as cur:
        cur.execute("""
            SELECT
                AVG(r.home_goals + r.away_goals) as avg_goals,
                AVG(CASE WHEN r.home_goals + r.away_goals > 1.5 THEN 1.0 ELSE 0.0 END) as over_15,
                AVG(CASE WHEN r.home_goals + r.away_goals > 2.5 THEN 1.0 ELSE 0.0 END) as over_25,
                AVG(CASE WHEN r.home_goals + r.away_goals > 3.5 THEN 1.0 ELSE 0.0 END) as over_35,
                AVG(CASE WHEN r.home_goals + r.away_goals < 3.5 THEN 1.0 ELSE 0.0 END) as under_35,
                AVG(CASE WHEN r.home_goals > 0 AND r.away_goals > 0 THEN 1.0 ELSE 0.0 END) as gg_rate,
                COUNT(*) as n
            FROM vfl_results_v2 r
            JOIN vfl_matchdays m ON r.matchday_id = m.id
            JOIN vfl_seasons s ON m.season_id = s.id
            WHERE s.season_name = %s
        """, (season_name,))
        row = cur.fetchone()

    def s(v, d): return round(float(v), 3) if v is not None else d

    result = {
        "season_avg_goals": s(row[0] if row else None, 2.5),
        "season_over_15_rate": s(row[1] if row else None, 0.70),
        "season_over_25_rate": s(row[2] if row else None, 0.50),
        "season_over_35_rate": s(row[3] if row else None, 0.30),
        "season_under_35_rate": s(row[4] if row else None, 0.70),
        "season_gg_rate": s(row[5] if row else None, 0.55),
        "season_matches": int(row[6]) if row and row[6] else 0,
    }
    _season_stats_cache[season_name] = result
    return result

# ═══════════════════════════════════════════════════════════════════════════════
# ODDS FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

def get_odds_features(event_id: Optional[str], home: str, away: str,
                      matchday: int, season_name: str) -> Dict:
    """Pull odds from vfl_odds_v2 for implied probability features."""
    defaults = {
        "odds_home": 2.5, "odds_draw": 3.2, "odds_away": 2.8,
        "odds_over_15": 1.25, "odds_under_35": 1.30,
        "odds_over_25": 1.85, "odds_under_25": 1.90,
        "odds_gg": 1.65, "odds_ng": 2.10,
        "impl_home": 0.40, "impl_draw": 0.31, "impl_away": 0.36,
        "impl_over_15": 0.80, "impl_under_35": 0.77,
        "impl_over_25": 0.54, "impl_gg": 0.61,
        "odds_source": "default",
    }

    try:
        with get_db() as cur:
            # Try vfl_odds_v2 by event_id or team+matchday
            if event_id:
                cur.execute("""
                    SELECT market_name, odds, event_id
                    FROM vfl_odds_v2
                    WHERE event_id = %s
                """, (event_id,))
            else:
                cur.execute("""
                    SELECT o.market_name, o.odds, o.event_id
                    FROM vfl_odds_v2 o
                    JOIN vfl_matchdays m ON o.matchday_id = m.id
                    JOIN vfl_seasons s ON m.season_id = s.id
                    WHERE s.season_name = %s
                      AND m.matchday_number = %s
                      AND (LOWER(o.home_team) = LOWER(%s) OR LOWER(o.home_team) LIKE %s)
                      AND (LOWER(o.away_team) = LOWER(%s) OR LOWER(o.away_team) LIKE %s)
                    LIMIT 50
                """, (season_name, matchday, home, f"%{home.lower()[:5]}%",
                      away, f"%{away.lower()[:5]}%"))

            rows = cur.fetchall()

        if not rows:
            return defaults

        market_odds: Dict[str, float] = {}
        for (market, odds_val, _) in rows:
            if market and odds_val:
                market_odds[market.lower()] = float(odds_val)

        def get_o(keys, default):
            for k in keys:
                for mk, v in market_odds.items():
                    if k in mk:
                        return v
            return default

        h_odds = get_o(["home win", "1x", "home"], 2.5)
        d_odds = get_o(["draw", " x ", "x2"], 3.2)
        a_odds = get_o(["away win", "x2", "away"], 2.8)
        o15_odds = get_o(["over 1.5", "over1.5"], 1.25)
        u35_odds = get_o(["under 3.5", "under3.5"], 1.30)
        o25_odds = get_o(["over 2.5", "over2.5"], 1.85)
        u25_odds = get_o(["under 2.5", "under2.5"], 1.90)
        gg_odds = get_o(["gg", "both score", "btts", "goal/goal"], 1.65)
        ng_odds = get_o(["ng", "no goal", "no/no"], 2.10)

        def impl(o): return round(1.0 / max(o, 1.01), 3)

        return {
            "odds_home": h_odds, "odds_draw": d_odds, "odds_away": a_odds,
            "odds_over_15": o15_odds, "odds_under_35": u35_odds,
            "odds_over_25": o25_odds, "odds_under_25": u25_odds,
            "odds_gg": gg_odds, "odds_ng": ng_odds,
            "impl_home": impl(h_odds), "impl_draw": impl(d_odds), "impl_away": impl(a_odds),
            "impl_over_15": impl(o15_odds), "impl_under_35": impl(u35_odds),
            "impl_over_25": impl(o25_odds), "impl_gg": impl(gg_odds),
            "odds_source": "db",
        }

    except Exception as e:
        log.debug(f"Odds lookup failed for {home} vs {away}: {e}")
        return defaults

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN FEATURE BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_feature_row(
    home: str,
    away: str,
    matchday_id: int,
    matchday_number: int,
    season_name: str,
    event_id: Optional[str],
    league_features: Dict,
    # Targets (None if predicting future)
    home_goals: Optional[int] = None,
    away_goals: Optional[int] = None,
) -> Dict:
    """Build one complete feature vector for a fixture."""
    hn = home.lower()
    an = away.lower()

    lf = league_features  # already loaded for this matchday
    hf = lf.get(hn, lf.get(home, {}))  # home team features
    af = lf.get(an, lf.get(away, {}))  # away team features

    h2h = get_h2h_features(home, away)
    season = get_season_stats(season_name)
    odds = get_odds_features(event_id, home, away, matchday_number, season_name)

    row: Dict = {
        # Identity
        "home_team": home,
        "away_team": away,
        "season_name": season_name,
        "matchday": matchday_number,
        "event_id": event_id or "",

        # League table — home
        "home_rank": hf.get("rank", 10),
        "home_points": hf.get("points", 0),
        "home_played": hf.get("played", 0),
        "home_goals_per_game": hf.get("goals_per_game", 1.5),
        "home_goals_against_per_game": hf.get("goals_against_per_game", 1.5),
        "home_goal_diff_per_game": hf.get("goal_diff_per_game", 0.0),
        "home_win_rate": hf.get("win_rate", 0.4),
        "home_draw_rate": hf.get("draw_rate", 0.25),
        "home_form_score": hf.get("form_score", 0.5),
        "home_points_per_game": hf.get("points_per_game", 1.0),

        # League table — away
        "away_rank": af.get("rank", 10),
        "away_points": af.get("points", 0),
        "away_played": af.get("played", 0),
        "away_goals_per_game": af.get("goals_per_game", 1.5),
        "away_goals_against_per_game": af.get("goals_against_per_game", 1.5),
        "away_goal_diff_per_game": af.get("goal_diff_per_game", 0.0),
        "away_win_rate": af.get("win_rate", 0.35),
        "away_draw_rate": af.get("draw_rate", 0.25),
        "away_form_score": af.get("form_score", 0.5),
        "away_points_per_game": af.get("points_per_game", 1.0),

        # Differential features
        "rank_diff": hf.get("rank", 10) - af.get("rank", 10),
        "points_diff": hf.get("points", 0) - af.get("points", 0),
        "form_diff": hf.get("form_score", 0.5) - af.get("form_score", 0.5),
        "goals_diff": hf.get("goals_per_game", 1.5) - af.get("goals_per_game", 1.5),
        "expected_total_goals": hf.get("goals_per_game", 1.5) + af.get("goals_against_per_game", 1.5),

        # H2H features
        **h2h,

        # Season regime
        **season,

        # Odds / implied probs
        **odds,
    }

    # Targets (only set during training, not prediction)
    if home_goals is not None and away_goals is not None:
        total = home_goals + away_goals
        row.update({
            "actual_home_goals": home_goals,
            "actual_away_goals": away_goals,
            "actual_total_goals": total,
            # Market targets
            "target_over_05": int(total > 0.5),
            "target_over_15": int(total > 1.5),
            "target_over_25": int(total > 2.5),
            "target_over_35": int(total > 3.5),
            "target_over_45": int(total > 4.5),
            "target_under_15": int(total < 1.5),
            "target_under_25": int(total < 2.5),
            "target_under_35": int(total < 3.5),
            "target_home_win": int(home_goals > away_goals),
            "target_draw": int(home_goals == away_goals),
            "target_away_win": int(away_goals > home_goals),
            "target_gg": int(home_goals > 0 and away_goals > 0),
            "target_ng": int(home_goals == 0 or away_goals == 0),
        })

    return row

def build_full_training_dataset(limit: Optional[int] = None) -> pd.DataFrame:
    """
    Build complete training dataset from all settled matchdays in Postgres.
    Each row = one fixture with full features + all market targets.
    """
    log.info("Building full training dataset...")

    with get_db() as cur:
        # Get all matchdays that have both results AND league snapshots
        query = """
            SELECT DISTINCT
                m.id as matchday_id,
                m.matchday_number,
                s.season_name,
                s.season_id
            FROM vfl_matchdays m
            JOIN vfl_seasons s ON m.season_id = s.id
            WHERE EXISTS (
                SELECT 1 FROM vfl_results_v2 r WHERE r.matchday_id = m.id
            )
            AND EXISTS (
                SELECT 1 FROM vfl_league_snapshots l WHERE l.matchday_id = m.id
            )
            ORDER BY m.id ASC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        matchdays = cur.fetchall()

    log.info(f"Found {len(matchdays)} matchdays with results+league data")

    rows = []
    errors = 0

    for i, (md_id, md_num, season_name, season_id) in enumerate(matchdays):
        if i % 100 == 0:
            log.info(f"  Processing matchday {i}/{len(matchdays)}: {season_name} MD{md_num}")

        # Load league features for this matchday (one DB call for all 16 teams)
        try:
            league_feats = get_league_features(md_id)
        except Exception as e:
            log.debug(f"League features failed for MD{md_id}: {e}")
            league_feats = {}

        # Get results for this matchday
        try:
            with get_db() as cur:
                cur.execute("""
                    SELECT r.home_team, r.away_team, r.home_goals, r.away_goals,
                           r.event_id
                    FROM vfl_results_v2 r
                    WHERE r.matchday_id = %s
                """, (md_id,))
                results = cur.fetchall()
        except Exception as e:
            log.debug(f"Results query failed: {e}")
            continue

        for (home, away, hg, ag, event_id) in results:
            try:
                row = build_feature_row(
                    home=home,
                    away=away,
                    matchday_id=md_id,
                    matchday_number=md_num,
                    season_name=season_name,
                    event_id=event_id,
                    league_features=league_feats,
                    home_goals=hg,
                    away_goals=ag,
                )
                rows.append(row)
            except Exception as e:
                errors += 1
                if errors < 10:
                    log.debug(f"Row build failed {home} vs {away}: {e}")

    log.info(f"Built {len(rows):,} feature rows ({errors} errors)")
    df = pd.DataFrame(rows)
    log.info(f"Dataset shape: {df.shape}")
    return df

def build_live_fixture_features(
    home: str,
    away: str,
    matchday_id: int,
    matchday_number: int,
    season_name: str,
    event_id: Optional[str] = None,
) -> Dict:
    """Build features for a live fixture (no targets)."""
    league_feats = get_league_features(matchday_id)
    return build_feature_row(
        home=home,
        away=away,
        matchday_id=matchday_id,
        matchday_number=matchday_number,
        season_name=season_name,
        event_id=event_id,
        league_features=league_feats,
    )

# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VFL Feature Builder")
    parser.add_argument("--export", type=str, help="Export training CSV to path")
    parser.add_argument("--limit", type=int, help="Limit matchdays for testing")
    parser.add_argument("--fixture", nargs=2, metavar=("HOME", "AWAY"),
                        help="Build features for a single fixture")
    parser.add_argument("--matchday", type=int, default=1)
    args = parser.parse_args()

    if args.fixture:
        home, away = args.fixture
        # For demo, use last matchday
        with get_db() as cur:
            cur.execute("""
                SELECT m.id, m.matchday_number, s.season_name
                FROM vfl_matchdays m JOIN vfl_seasons s ON m.season_id=s.id
                ORDER BY m.id DESC LIMIT 1
            """)
            row = cur.fetchone()
        md_id, md_num, season = row if row else (1, 1, "VFLM 5200")
        feat = build_live_fixture_features(home, away, md_id, md_num, season)
        print(json.dumps(feat, indent=2, default=str))

    elif args.export:
        df = build_full_training_dataset(limit=args.limit)
        out = Path(args.export)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        log.info(f"Exported {len(df):,} rows to {out}")
        print(f"\nDataset summary:")
        print(f"  Shape: {df.shape}")
        print(f"  Targets:")
        for col in df.columns:
            if col.startswith("target_"):
                rate = df[col].mean()
                print(f"    {col}: {rate:.3f} hit rate")
    else:
        parser.print_help()
