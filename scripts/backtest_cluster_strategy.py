#!/usr/bin/env python3
"""
Aggressive Cluster Strategy Backtester
=======================================
Tests the odds fingerprint cluster strategy across ALL historical VFL seasons.

Strategy: For each matchday (8 fixtures), classify each match by its odds
fingerprint, rank by edge (hit_rate - 1/avg_odds), pick top 2, then
simulate three betting approaches:
  1. Singles: flat 1 unit per pick
  2. 2-leg parlays: 1 unit parlay on the top 2 picks
  3. Weighted: stake proportional to edge

Outputs per-season + overall performance, plus cluster breakdown analysis.

Usage:
    python backtest_cluster_strategy.py
    python backtest_cluster_strategy.py --min-seasons 5080
    python backtest_cluster_strategy.py --output results.json

Author: VFL Engineering Team
"""

import sqlite3
import json
import math
import sys
import os
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data'
ODDS_DB = os.path.join(BASE_DIR, 'databases', 'vfl_odds.db')
RESULTS_DB = os.path.join(BASE_DIR, 'databases', 'vfl_results.db')
SCRIPTS_DIR = '/home/ubuntu/faith-workspace/vfl-empire/scripts'
OUTPUT_DIR = '/home/ubuntu/faith-workspace/vfl-empire/data'

# ──────────────────────────────────────────────────────────────────────
# CLUSTER CENTROIDS (same as odds_cluster_classifier.py)
# ──────────────────────────────────────────────────────────────────────
CLUSTER_CENTROIDS = [
    [0.8547, 0.6250, 0.5263, 0.6803],
    [0.6993, 0.4255, 0.4505, 0.8475],
    [0.6711, 0.3968, 0.4673, 0.8696],
    [0.8000, 0.5464, 0.5882, 0.7576],
    [0.7576, 0.4950, 0.4237, 0.8000],
    [0.7353, 0.4630, 0.4902, 0.8197],
    [0.8333, 0.5882, 0.5747, 0.7143],
    [0.8475, 0.6173, 0.6289, 0.6897],
]

CLUSTER_RECOMMENDATIONS = [
    {'market': 'NG',   'hit_rate': 0.531, 'avg_odds': 1.84},
    {'market': 'NG',   'hit_rate': 0.590, 'avg_odds': 1.61},
    {'market': 'GG',   'hit_rate': 0.491, 'avg_odds': 2.14},
    {'market': 'GG',   'hit_rate': 0.585, 'avg_odds': 1.70},
    {'market': 'O2.5', 'hit_rate': 0.520, 'avg_odds': 2.02},
    {'market': 'U2.5', 'hit_rate': 0.593, 'avg_odds': 1.65},
    {'market': 'GG',   'hit_rate': 0.585, 'avg_odds': 1.74},
    {'market': 'GG',   'hit_rate': 0.616, 'avg_odds': 1.59},
]

NUM_CLUSTERS = len(CLUSTER_CENTROIDS)

# Market verification functions
MARKET_VERIFY = {
    'O1.5': lambda tg, hg, ag: 1 if tg > 1.5 else 0,
    'O2.5': lambda tg, hg, ag: 1 if tg > 2.5 else 0,
    'U2.5': lambda tg, hg, ag: 1 if tg < 2.5 else 0,
    'U3.5': lambda tg, hg, ag: 1 if tg < 3.5 else 0,
    'GG':   lambda tg, hg, ag: 1 if hg > 0 and ag > 0 else 0,
    'NG':   lambda tg, hg, ag: 1 if hg == 0 or ag == 0 else 0,
}

MARKET_ODDS_KEY = {
    'O1.5': 'o15', 'O2.5': 'o25', 'U2.5': 'u25',
    'U3.5': 'u35', 'GG': 'gg', 'NG': 'ng',
}


# ──────────────────────────────────────────────────────────────────────
# CORE FUNCTIONS
# ──────────────────────────────────────────────────────────────────────

def euclidean_distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def compute_prob_vector(o15, o25, gg, u35):
    return [1.0 / o15, 1.0 / o25, 1.0 / gg, 1.0 / u35]


def classify_match(o15, o25, gg, u35):
    """Classify and return nearest cluster info."""
    if any(v is None or v <= 1.0 for v in [o15, o25, gg, u35]):
        return {'cluster_id': -1}
    vec = compute_prob_vector(o15, o25, gg, u35)
    best_cid, best_dist = 0, float('inf')
    for i, cent in enumerate(CLUSTER_CENTROIDS):
        d = euclidean_distance(vec, cent)
        if d < best_dist:
            best_dist, best_cid = d, i
    rec = CLUSTER_RECOMMENDATIONS[best_cid]
    return {
        'cluster_id': best_cid,
        'rec_bet': rec['market'],
        'hit_rate': rec['hit_rate'],
        'avg_odds': rec['avg_odds'],
        'distance': best_dist,
        'edge': rec['hit_rate'] - (1.0 / rec['avg_odds']),
    }


def verify_pick(market, total_goals, home_goals, away_goals):
    """Check if a bet would have won given actual score."""
    fn = MARKET_VERIFY.get(market)
    if fn is None:
        return 0
    return fn(total_goals, home_goals, away_goals)


def get_actual_odds_for_market(odds_dict, market):
    """Get the actual odds for a given market from the odds dict."""
    key = MARKET_ODDS_KEY.get(market)
    if key is None:
        return None
    return odds_dict.get(key)


# ──────────────────────────────────────────────────────────────────────
# DATA LOADING
# ──────────────────────────────────────────────────────────────────────

def load_all_seasons_with_data():
    """Load ALL seasons' matches with odds + results from the databases.

    Uses the same JOIN approach as odds_reverse_engineer.py:
    event_details (vfl_odds.db) JOIN results (vfl_results.db) ON
    season_id + match_day + home_team + away_team, then JOIN deep_markets
    ON event_id.

    Returns list of match dicts with full odds and results.
    """
    conn_odds = sqlite3.connect(ODDS_DB)
    conn_odds.row_factory = sqlite3.Row

    print("Loading all historical matches...", file=sys.stderr)

    try:
        # Attach results DB
        conn_odds.execute(f"ATTACH DATABASE '{RESULTS_DB}' AS res;")

        # Use the same join as odds_reverse_engineer.py
        query = """
            SELECT 
              e.event_id, 
              e.season_name, 
              e.match_day, 
              e.home_team, 
              e.away_team,
              r.home_goals, 
              r.away_goals, 
              r.total_goals,
              MAX(CASE WHEN d.market_name = 'Over/Under' AND d.specifiers = 'total=1.5' AND d.selection_name = 'Over 1.5' THEN d.odds END) as o15_odds,
              MAX(CASE WHEN d.market_name = 'Over/Under' AND d.specifiers = 'total=1.5' AND d.selection_name = 'Under 1.5' THEN d.odds END) as u15_odds,
              MAX(CASE WHEN d.market_name = 'Over/Under' AND d.specifiers = 'total=2.5' AND d.selection_name = 'Over 2.5' THEN d.odds END) as o25_odds,
              MAX(CASE WHEN d.market_name = 'Over/Under' AND d.specifiers = 'total=2.5' AND d.selection_name = 'Under 2.5' THEN d.odds END) as u25_odds,
              MAX(CASE WHEN d.market_name = 'Over/Under' AND d.specifiers = 'total=3.5' AND d.selection_name = 'Over 3.5' THEN d.odds END) as o35_odds,
              MAX(CASE WHEN d.market_name = 'Over/Under' AND d.specifiers = 'total=3.5' AND d.selection_name = 'Under 3.5' THEN d.odds END) as u35_odds,
              MAX(CASE WHEN d.market_name = 'GG/NG' AND d.selection_name = 'Yes' THEN d.odds END) as gg_odds,
              MAX(CASE WHEN d.market_name = 'GG/NG' AND d.selection_name = 'No' THEN d.odds END) as ng_odds
            FROM event_details e
            JOIN res.results r ON e.season_id = r.season_id AND e.match_day = r.match_day AND e.home_team = r.home_team AND e.away_team = r.away_team
            JOIN deep_markets d ON e.event_id = d.event_id
            WHERE r.status = 3
            GROUP BY e.event_id
            ORDER BY e.season_name, e.match_day
        """

        cursor = conn_odds.execute(query)
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        if not rows:
            print("ERROR: No results found.", file=sys.stderr)
            return []

        # Build matches, filtering for complete odds
        matches = []
        skipped_incomplete = 0

        for row in rows:
            required = ['o15_odds', 'o25_odds', 'gg_odds', 'u35_odds']
            if not all(row.get(k) is not None and row[k] > 1.0 for k in required):
                skipped_incomplete += 1
                continue

            matches.append({
                'event_id': row['event_id'],
                'season_id': row.get('season_id', ''),
                'season_name': row['season_name'],
                'match_day': row['match_day'],
                'home_team': row['home_team'],
                'away_team': row['away_team'],
                'home_goals': row['home_goals'],
                'away_goals': row['away_goals'],
                'total_goals': row['total_goals'],
                'o15': row['o15_odds'],
                'u15': row.get('u15_odds'),
                'o25': row['o25_odds'],
                'u25': row.get('u25_odds'),
                'o35': row.get('o35_odds'),
                'u35': row['u35_odds'],
                'gg': row['gg_odds'],
                'ng': row.get('ng_odds'),
            })

        print(f"  Loaded {len(matches)} matches with full odds+results", file=sys.stderr)
        print(f"  Skipped (incomplete odds): {skipped_incomplete}", file=sys.stderr)
        return matches

    finally:
        conn_odds.close()


def group_by_season_matchday(matches):
    """Group matches into {season: {matchday: [matches]}}."""
    groups = defaultdict(lambda: defaultdict(list))
    for m in matches:
        groups[m['season_name']][m['match_day']].append(m)
    return groups


# ──────────────────────────────────────────────────────────────────────
# BACKTESTING ENGINE
# ──────────────────────────────────────────────────────────────────────

def backtest_season(season_matches):
    """Run full backtest on a single season's worth of matchday-grouped matches.

    Returns detailed performance statistics.
    """
    # Track picks for this season
    all_picks_singles = []
    all_picks_parlay = []
    all_picks_weighted = []

    # Cluster hit rate tracking
    cluster_stats = defaultdict(lambda: {'picks': 0, 'wins': 0, 'total_stake': 0.0, 'total_return': 0.0})

    for md_id, fixtures in sorted(season_matches.items()):
        if len(fixtures) < 2:
            continue

        # Classify each fixture
        scored = []
        for fx in fixtures:
            cls = classify_match(fx['o15'], fx['o25'], fx['gg'], fx['u35'])
            if cls['cluster_id'] == -1:
                continue

            actual_odds = get_actual_odds_for_market(fx, cls['rec_bet'])
            if actual_odds is None or actual_odds <= 1.0:
                continue

            scored.append({
                **cls,
                'home_team': fx['home_team'],
                'away_team': fx['away_team'],
                'match_day': md_id,
                'total_goals': fx['total_goals'],
                'home_goals': fx['home_goals'],
                'away_goals': fx['away_goals'],
                'actual_odds': actual_odds,
            })

        # Sort by edge descending
        scored.sort(key=lambda x: x['edge'], reverse=True)

        if len(scored) < 2:
            continue

        # Top 2 picks
        pick1, pick2 = scored[0], scored[1]

        # Simulate picks
        for pick in [pick1, pick2]:
            is_win = verify_pick(pick['rec_bet'], pick['total_goals'],
                                  pick['home_goals'], pick['away_goals'])
            pick['is_win'] = bool(is_win)

            # Singles (flat 1 unit)
            all_picks_singles.append({
                'match_day': pick['match_day'],
                'home_team': pick['home_team'],
                'away_team': pick['away_team'],
                'market': pick['rec_bet'],
                'odds': pick['actual_odds'],
                'win': is_win,
                'stake': 1.0,
                'return': pick['actual_odds'] if is_win else 0.0,
                'cluster_id': pick['cluster_id'],
                'edge': pick['edge'],
                'hit_rate': pick['hit_rate'],
            })

            # Track cluster performance
            cid = pick['cluster_id']
            cluster_stats[cid]['picks'] += 1
            cluster_stats[cid]['wins'] += is_win
            cluster_stats[cid]['total_stake'] += 1.0
            cluster_stats[cid]['total_return'] += pick['actual_odds'] if is_win else 0.0

        # 2-leg parlay (1 unit)
        parlay_odds = pick1['actual_odds'] * pick2['actual_odds']
        parlay_win = 1 if pick1['is_win'] and pick2['is_win'] else 0
        all_picks_parlay.append({
            'match_day': md_id,
            'leg1': f"{pick1['home_team']} {pick1['rec_bet']} @{pick1['actual_odds']:.2f}",
            'leg2': f"{pick2['home_team']} {pick2['rec_bet']} @{pick2['actual_odds']:.2f}",
            'combined_odds': parlay_odds,
            'win': parlay_win,
            'stake': 1.0,
            'return': parlay_odds if parlay_win else 0.0,
            'pick1_cluster': pick1['cluster_id'],
            'pick2_cluster': pick2['cluster_id'],
        })

        # Weighted (stake proportional to edge, scaled to avg 1 unit)
        total_edge = abs(pick1['edge']) + abs(pick2['edge'])
        if total_edge > 0:
            stake1 = 2.0 * abs(pick1['edge']) / total_edge if pick1['edge'] > 0 else 0.5
            stake2 = 2.0 * abs(pick2['edge']) / total_edge if pick2['edge'] > 0 else 0.5
        else:
            stake1 = stake2 = 1.0

        w1_win = verify_pick(pick1['rec_bet'], pick1['total_goals'],
                              pick1['home_goals'], pick1['away_goals'])
        w2_win = verify_pick(pick2['rec_bet'], pick2['total_goals'],
                              pick2['home_goals'], pick2['away_goals'])

        all_picks_weighted.append({
            'match_day': md_id,
            'leg1': f"{pick1['home_team']} {pick1['rec_bet']} @{pick1['actual_odds']:.2f}",
            'leg2': f"{pick2['home_team']} {pick2['rec_bet']} @{pick2['actual_odds']:.2f}",
            'stake1': round(stake1, 3),
            'stake2': round(stake2, 3),
            'total_stake': round(stake1 + stake2, 3),
            'win1': w1_win,
            'win2': w2_win,
            'return1': pick1['actual_odds'] * stake1 if w1_win else 0.0,
            'return2': pick2['actual_odds'] * stake2 if w2_win else 0.0,
            'total_return': round(
                (pick1['actual_odds'] * stake1 if w1_win else 0.0) +
                (pick2['actual_odds'] * stake2 if w2_win else 0.0), 3
            ),
        })

    return {
        'singles': all_picks_singles,
        'parlays': all_picks_parlay,
        'weighted': all_picks_weighted,
        'cluster_stats': dict(cluster_stats),
    }


def compute_stats(picks_list, label="method"):
    """Compute aggregate statistics from a list of pick results."""
    if not picks_list:
        return {
            'label': label,
            'total_bets': 0, 'wins': 0, 'hit_rate': 0.0,
            'total_stake': 0.0, 'total_return': 0.0,
            'net_profit': 0.0, 'roi': 0.0, 'avg_odds': 0.0,
        }

    total = len(picks_list)
    wins = sum(p.get('win', 0) for p in picks_list)
    total_stake = sum(p.get('stake', 1.0) for p in picks_list)
    total_return = sum(p.get('return', 0.0) for p in picks_list)

    # Handle weighted format
    if 'total_stake' in picks_list[0] and 'total_return' in picks_list[0]:
        total_stake = sum(p['total_stake'] for p in picks_list)
        total_return = sum(p['total_return'] for p in picks_list)
        wins = sum(p.get('win1', 0) + p.get('win2', 0) for p in picks_list)
        total = len(picks_list) * 2

    hit_rate = wins / total if total > 0 else 0.0
    net_profit = total_return - total_stake
    roi = (net_profit / total_stake * 100) if total_stake > 0 else 0.0

    odds_list = [p.get('odds', 0) for p in picks_list if p.get('odds', 0) > 0]
    avg_odds = sum(odds_list) / len(odds_list) if odds_list else 0.0

    return {
        'label': label,
        'total_bets': total,
        'wins': wins,
        'hit_rate': round(hit_rate, 4),
        'total_stake': round(total_stake, 2),
        'total_return': round(total_return, 2),
        'net_profit': round(net_profit, 2),
        'roi': round(roi, 2),
        'avg_odds': round(avg_odds, 2),
    }


def compute_parlay_stats(parlays):
    """Compute stats for parlay bets."""
    if not parlays:
        return {
            'label': '2-leg Parlays',
            'total_bets': 0, 'wins': 0, 'hit_rate': 0.0,
            'total_stake': 0.0, 'total_return': 0.0,
            'net_profit': 0.0, 'roi': 0.0, 'avg_odds': 0.0,
        }

    total = len(parlays)
    wins = sum(p['win'] for p in parlays)
    total_stake = sum(p['stake'] for p in parlays)
    total_return = sum(p['return'] for p in parlays)
    hit_rate = wins / total if total > 0 else 0.0
    net_profit = total_return - total_stake
    roi = (net_profit / total_stake * 100) if total_stake > 0 else 0.0
    avg_odds = sum(p['combined_odds'] for p in parlays) / total if total > 0 else 0.0

    return {
        'label': '2-leg Parlays',
        'total_bets': total,
        'wins': wins,
        'hit_rate': round(hit_rate, 4),
        'total_stake': round(total_stake, 2),
        'total_return': round(total_return, 2),
        'net_profit': round(net_profit, 2),
        'roi': round(roi, 2),
        'avg_odds': round(avg_odds, 2),
    }


# ──────────────────────────────────────────────────────────────────────
# MAIN BACKTEST
# ──────────────────────────────────────────────────────────────────────

def run_backtest(min_season_num=None):
    """Run the full backtest across all seasons."""
    matches = load_all_seasons_with_data()
    if not matches:
        print("ERROR: No matches loaded. Aborting.", file=sys.stderr)
        return None

    grouped = group_by_season_matchday(matches)

    # Filter by season number if specified
    if min_season_num is not None:
        filtered = {}
        for season_name, mds in grouped.items():
            # Extract number from season name like "VFLM 5080"
            try:
                num = int(season_name.split()[-1])
                if num >= min_season_num:
                    filtered[season_name] = mds
            except (ValueError, IndexError):
                filtered[season_name] = mds
        grouped = filtered

    print(f"\nBacktesting {len(grouped)} seasons...", file=sys.stderr)

    overall_singles = []
    overall_parlays = []
    overall_weighted = []
    per_season_results = []
    overall_cluster_stats = defaultdict(lambda: {'picks': 0, 'wins': 0, 'total_stake': 0.0, 'total_return': 0.0})
    all_md_count = 0

    for season_name in sorted(grouped.keys()):
        mds = grouped[season_name]
        result = backtest_season(mds)

        num_mds = len(mds)
        all_md_count += num_mds

        s_stats = compute_stats(result['singles'], 'Singles')
        p_stats = compute_parlay_stats(result['parlays'])
        w_stats = compute_stats(result['weighted'], 'Weighted')

        per_season_results.append({
            'season': season_name,
            'matchdays': num_mds,
            'singles': s_stats,
            'parlays': p_stats,
            'weighted': w_stats,
            'total_singles_picks': len(result['singles']),
        })

        overall_singles.extend(result['singles'])
        overall_parlays.extend(result['parlays'])
        overall_weighted.extend(result['weighted'])

        # Aggregate cluster stats
        for cid, cs in result['cluster_stats'].items():
            overall_cluster_stats[cid]['picks'] += cs['picks']
            overall_cluster_stats[cid]['wins'] += cs['wins']
            overall_cluster_stats[cid]['total_stake'] += cs['total_stake']
            overall_cluster_stats[cid]['total_return'] += cs['total_return']

        # Print season summary
        print(f"  {season_name:16s} ({num_mds:2d} MDs): "
              f"Singles HR={s_stats['hit_rate']*100:5.1f}% "
              f"ROI={s_stats['roi']:+.1f}% | "
              f"Parlay HR={p_stats['hit_rate']*100:5.1f}% "
              f"ROI={p_stats['roi']:+.1f}% | "
              f"Weighted ROI={w_stats['roi']:+.1f}%",
              file=sys.stderr)

    # Compute overall stats
    overall_s_stats = compute_stats(overall_singles, 'Singles (flat 1u)')
    overall_p_stats = compute_parlay_stats(overall_parlays)
    overall_w_stats = compute_stats(overall_weighted, 'Weighted')

    # Build cluster breakdown
    cluster_breakdown = {}
    for cid in range(NUM_CLUSTERS):
        cs = overall_cluster_stats.get(cid, {'picks': 0, 'wins': 0, 'total_stake': 0.0, 'total_return': 0.0})
        rec = CLUSTER_RECOMMENDATIONS[cid]
        hr = cs['wins'] / cs['picks'] if cs['picks'] > 0 else 0
        roi = ((cs['total_return'] - cs['total_stake']) / cs['total_stake'] * 100) if cs['total_stake'] > 0 else 0.0
        cluster_breakdown[cid] = {
            'cluster_id': cid,
            'recommended_bet': rec['market'],
            'expected_hit_rate': rec['hit_rate'],
            'expected_odds': rec['avg_odds'],
            'actual_picks': cs['picks'],
            'actual_wins': cs['wins'],
            'actual_hit_rate': round(hr, 4),
            'total_stake': round(cs['total_stake'], 2),
            'total_return': round(cs['total_return'], 2),
            'net_profit': round(cs['total_return'] - cs['total_stake'], 2),
            'roi': round(roi, 2),
        }

    return {
        'total_seasons': len(per_season_results),
        'total_matchdays': all_md_count,
        'overall': {
            'singles': overall_s_stats,
            'parlays': overall_p_stats,
            'weighted': overall_w_stats,
        },
        'per_season': per_season_results,
        'cluster_breakdown': cluster_breakdown,
    }


def print_results(results):
    """Pretty-print the backtest results."""
    if results is None:
        print("NO RESULTS - Backtest failed.")
        return

    overall = results['overall']

    print("\n" + "=" * 72)
    print("  AGGRESSIVE CLUSTER STRATEGY BACKTEST — OVERALL RESULTS")
    print("=" * 72)
    print(f"  Seasons:         {results['total_seasons']}")
    print(f"  Matchdays:       {results['total_matchdays']}")
    print(f"  Total Singles:   {overall['singles']['total_bets']}")
    print(f"  Total Parlays:   {overall['parlays']['total_bets']}")
    print()

    for label, stats in [('Singles (flat 1u)', overall['singles']),
                          ('2-leg Parlays (1u)', overall['parlays']),
                          ('Weighted', overall['weighted'])]:
        print(f"  ┌─ {label} ─────────────────────────────────────────────")
        print(f"  │  Bets:     {stats['total_bets']}")
        print(f"  │  Wins:     {stats['wins']}")
        print(f"  │  Hit Rate: {stats['hit_rate']*100:.2f}%")
        print(f"  │  Stake:    {stats['total_stake']:.2f}u")
        print(f"  │  Return:   {stats['total_return']:.2f}u")
        print(f"  │  Profit:   {stats['net_profit']:+.2f}u")
        print(f"  │  ROI:      {stats['roi']:+.2f}%")
        if stats['avg_odds'] > 0:
            print(f"  │  Avg Odds: {stats['avg_odds']:.2f}")
        print(f"  └──────────────────────────────────────────────────────")
        print()

    # Best/Worst seasons
    if results['per_season']:
        seasons_sorted = sorted(results['per_season'],
                                 key=lambda s: s['singles']['roi'], reverse=True)
        print(f"  ┌─ TOP 5 SEASONS (Singles ROI) ─────────────────────────")
        for s in seasons_sorted[:5]:
            print(f"  │  {s['season']:16s}: HR={s['singles']['hit_rate']*100:5.1f}% "
                  f"ROI={s['singles']['roi']:+.1f}% "
                  f"(n={s['singles']['total_bets']} bets)")
        print(f"  └──────────────────────────────────────────────────────")
        print()

        print(f"  ┌─ WORST 5 SEASONS (Singles ROI) ──────────────────────")
        for s in seasons_sorted[-5:]:
            print(f"  │  {s['season']:16s}: HR={s['singles']['hit_rate']*100:5.1f}% "
                  f"ROI={s['singles']['roi']:+.1f}% "
                  f"(n={s['singles']['total_bets']} bets)")
        print(f"  └──────────────────────────────────────────────────────")
        print()

    # Cluster breakdown
    print(f"  ┌─ CLUSTER BREAKDOWN ─────────────────────────────────────")
    print(f"  │  {'CID':3s} {'Bet':5s} {'ExpHR':6s} {'Picks':6s} {'Wins':5s} {'ActHR':6s} "
          f"{'Stake':7s} {'Return':7s} {'Profit':7s} {'ROI':7s}")
    print(f"  │  {'───':3s} {'───':5s} {'──────':6s} {'──────':6s} {'────':5s} {'──────':6s} "
          f"{'───────':7s} {'───────':7s} {'───────':7s} {'───────':7s}")
    for cid in sorted(results['cluster_breakdown'].keys()):
        cb = results['cluster_breakdown'][cid]
        print(f"  │  {cb['cluster_id']:3d} {cb['recommended_bet']:5s} "
              f"{cb['expected_hit_rate']*100:5.1f}% "
              f"{cb['actual_picks']:5d}   {cb['actual_wins']:4d}  "
              f"{cb['actual_hit_rate']*100:5.1f}% "
              f"{cb['total_stake']:6.1f}u {cb['total_return']:6.1f}u "
              f"{cb['net_profit']:+.1f}u {cb['roi']:+.1f}%")
    print(f"  └──────────────────────────────────────────────────────")
    print()

    # Gold Mine Assessment
    print(f"  ┌─ GOLD MINE ASSESSMENT ─────────────────────────────────")
    gold = results['cluster_breakdown'].get(7, {})
    if gold:
        print(f"  │  Cluster 7 (GG @1.59):")
        print(f"  │    Expected HR: {gold['expected_hit_rate']*100:.1f}%")
        print(f"  │    Actual HR:   {gold['actual_hit_rate']*100:.1f}%")
        print(f"  │    ROI:         {gold['roi']:+.1f}%")
        print(f"  │    Net Profit:  {gold['net_profit']:+.1f}u")
        if gold['actual_picks'] > 0:
            print(f"  │    Verdict:     {'✅ PLAYABLE' if gold['roi'] > 0 else '❌ UNDERPERFORMS'}")
    print(f"  └──────────────────────────────────────────────────────")
    print()


# ──────────────────────────────────────────────────────────────────────
# COMMAND-LINE INTERFACE
# ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Aggressive Cluster Strategy Backtester',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--min-seasons', type=int, default=None,
                        help='Minimum season number (e.g. 5080)')
    parser.add_argument('--output', type=str, default=None,
                        help='Save results to JSON file')
    parser.add_argument('--json', action='store_true',
                        help='Print results as JSON to stdout')

    args = parser.parse_args()

    results = run_backtest(min_season_num=args.min_seasons)

    if results is None:
        sys.exit(1)

    if args.json:
        # Remove per_season details for cleaner JSON
        output = dict(results)
        output['per_season'] = [
            {k: v for k, v in s.items() if k != 'singles' and k != 'parlays' and k != 'weighted'}
            for s in results['per_season']
        ]
        print(json.dumps(output, indent=2))
    else:
        print_results(results)

    if args.output:
        os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else '.', exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
