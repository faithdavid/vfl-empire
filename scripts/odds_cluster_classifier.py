#!/usr/bin/env python3
"""
Odds Fingerprint Cluster Classifier
====================================
Classifies VFL matches by their odds fingerprint — the 4-market implied
probability vector (O1.5, O2.5, GG, U3.5) — into one of 8 pre-trained
signature clusters.

Each cluster encodes a specific "odds DNA" that predicts a recommended
bet with known historical hit-rate and average odds.

Usage:
    python odds_cluster_classifier.py --season 5113 --matchday 3
    python odds_cluster_classifier.py --o15 1.30 --o25 2.05 --gg 1.85 --u35 1.30
    python odds_cluster_classifier.py --batch fixtures.json

Author: VFL Engineering Team
"""

import json
import math
import sys
import os
from typing import Dict, List, Optional, Tuple

# Add path for common tools
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db

# ──────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data'
ODDS_DB = os.path.join(BASE_DIR, 'databases', 'vfl_odds.db')
RESULTS_DB = os.path.join(BASE_DIR, 'databases', 'vfl_results.db')
SCRIPTS_DIR = '/home/ubuntu/faith-workspace/vfl-empire/scripts'

# ──────────────────────────────────────────────────────────────────────
# CLUSTER CENTROIDS  (raw implied-probability space: 1/odds)
# Derived from 3,401 historical VFL matches using 8-means clustering
# on 7D margin-stripped probability vectors, then projected to 4D
# (O1.5, O2.5, GG, U3.5) for live classification.
# ──────────────────────────────────────────────────────────────────────

# Each centroid is [p_o15, p_o25, p_gg, p_u35] where p = 1/odds (raw)
CLUSTER_CENTROIDS = [
    [0.8547, 0.6250, 0.5263, 0.6803],  # Cluster 0: O1.5@1.17 O2.5@1.60 GG@1.90 U3.5@1.47
    [0.6993, 0.4255, 0.4505, 0.8475],  # Cluster 1: O1.5@1.43 O2.5@2.35 GG@2.22 U3.5@1.18
    [0.6711, 0.3968, 0.4673, 0.8696],  # Cluster 2: O1.5@1.49 O2.5@2.52 GG@2.14 U3.5@1.15
    [0.8000, 0.5464, 0.5882, 0.7576],  # Cluster 3: O1.5@1.25 O2.5@1.83 GG@1.70 U3.5@1.32
    [0.7576, 0.4950, 0.4237, 0.8000],  # Cluster 4: O1.5@1.32 O2.5@2.02 GG@2.36 U3.5@1.25
    [0.7353, 0.4630, 0.4902, 0.8197],  # Cluster 5: O1.5@1.36 O2.5@2.16 GG@2.04 U3.5@1.22
    [0.8333, 0.5882, 0.5747, 0.7143],  # Cluster 6: O1.5@1.20 O2.5@1.70 GG@1.74 U3.5@1.40
    [0.8475, 0.6173, 0.6289, 0.6897],  # Cluster 7: O1.5@1.18 O2.5@1.62 GG@1.59 U3.5@1.45  ← GOLD MINE
]

# Recommended bet for each cluster: {market, hit_rate, avg_odds}
# market key: 'O1.5', 'O2.5', 'U2.5', 'U3.5', 'GG', 'NG'
DEFAULT_CLUSTER_RECOMMENDATIONS = [
    {'market': 'NG',   'hit_rate': 0.531, 'avg_odds': 1.84, 'label': 'NG 53.1% @1.84'},
    {'market': 'NG',   'hit_rate': 0.590, 'avg_odds': 1.61, 'label': 'NG 59.0% @1.61'},
    {'market': 'GG',   'hit_rate': 0.491, 'avg_odds': 2.14, 'label': 'GG 49.1% @2.14'},
    {'market': 'GG',   'hit_rate': 0.585, 'avg_odds': 1.70, 'label': 'GG 58.5% @1.70'},
    {'market': 'O2.5', 'hit_rate': 0.520, 'avg_odds': 2.02, 'label': 'O2.5 52.0% @2.02'},
    {'market': 'U2.5', 'hit_rate': 0.593, 'avg_odds': 1.65, 'label': 'U2.5 59.3% @1.65'},
    {'market': 'GG',   'hit_rate': 0.585, 'avg_odds': 1.74, 'label': 'GG 58.5% @1.74'},
    {'market': 'GG',   'hit_rate': 0.616, 'avg_odds': 1.59, 'label': 'GG 61.6% @1.59  ← GOLD MINE'},
]

CLUSTER_CONFIG_PATH = os.path.join(BASE_DIR, 'signals', 'cluster_config.json')

def load_cluster_recommendations():
    if os.path.exists(CLUSTER_CONFIG_PATH):
        try:
            with open(CLUSTER_CONFIG_PATH) as f:
                data = json.load(f)
                return data.get('recommendations', DEFAULT_CLUSTER_RECOMMENDATIONS)
        except Exception as e:
            print(f"Warning: Failed to load cluster config: {e}")
    return DEFAULT_CLUSTER_RECOMMENDATIONS

CLUSTER_RECOMMENDATIONS = load_cluster_recommendations()
NUM_CLUSTERS = len(CLUSTER_CENTROIDS)

# Market key mapping for verification
MARKET_VERIFY = {
    'O1.5': lambda tg, hg, ag: 1 if tg > 1.5 else 0,
    'O2.5': lambda tg, hg, ag: 1 if tg > 2.5 else 0,
    'U2.5': lambda tg, hg, ag: 1 if tg < 2.5 else 0,
    'U3.5': lambda tg, hg, ag: 1 if tg < 3.5 else 0,
    'GG':   lambda tg, hg, ag: 1 if hg > 0 and ag > 0 else 0,
    'NG':   lambda tg, hg, ag: 1 if hg == 0 or ag == 0 else 0,
}

MARKET_ODDS_GETTER = {
    'O1.5': lambda odds: odds['o15'],
    'O2.5': lambda odds: odds['o25'],
    'U2.5': lambda odds: odds['u25'],
    'U3.5': lambda odds: odds['u35'],
    'GG':   lambda odds: odds['gg'],
    'NG':   lambda odds: odds['ng'],
}


# ──────────────────────────────────────────────────────────────────────
# CORE CLASSIFIER
# ──────────────────────────────────────────────────────────────────────

def compute_prob_vector(o15_odds: float, o25_odds: float,
                        gg_odds: float, u35_odds: float) -> List[float]:
    """Compute a 4D raw implied-probability vector from live odds.

    Uses the raw 1/odds as the fingerprint (no margin stripping needed
    because centroids are in the same space).
    """
    return [1.0 / o15_odds, 1.0 / o25_odds, 1.0 / gg_odds, 1.0 / u35_odds]


def euclidean_distance(a: List[float], b: List[float]) -> float:
    """Euclidean distance between two vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def classify_match(o15_odds: float, o25_odds: float,
                   gg_odds: float, u35_odds: float) -> Dict:
    """Classify a match by its odds fingerprint.

    Args:
        o15_odds: Over 1.5 decimal odds
        o25_odds: Over 2.5 decimal odds
        gg_odds:  Goal-Goal (Yes) decimal odds
        u35_odds: Under 3.5 decimal odds

    Returns:
        dict with:
            cluster_id: int (0-7)
            rec_bet: str (e.g. 'GG', 'NG', 'O2.5', 'U2.5')
            hit_rate: float (historical win rate for this cluster)
            avg_odds: float (average odds for the recommended bet)
            confidence: int (0-100, based on distance to centroid)
            distance: float (euclidean distance to nearest centroid)
            label: str (human-readable recommendation string)
    """
    # Validate inputs
    for val, name in [(o15_odds, 'o15_odds'), (o25_odds, 'o25_odds'),
                       (gg_odds, 'gg_odds'), (u35_odds, 'u35_odds')]:
        if val is None or val <= 1.0:
            return {
                'cluster_id': -1,
                'rec_bet': 'UNKNOWN',
                'hit_rate': 0.0,
                'avg_odds': 0.0,
                'confidence': 0,
                'distance': float('inf'),
                'label': 'Invalid odds',
                'error': f'Invalid or missing {name}: {val}'
            }

    vec = compute_prob_vector(o15_odds, o25_odds, gg_odds, u35_odds)

    # Find nearest centroid
    best_cluster = 0
    best_dist = float('inf')
    for i, centroid in enumerate(CLUSTER_CENTROIDS):
        d = euclidean_distance(vec, centroid)
        if d < best_dist:
            best_dist = d
            best_cluster = i

    rec = CLUSTER_RECOMMENDATIONS[best_cluster]

    # Compute confidence: inversely related to distance
    # Max possible distance in 4D prob space ≈ 1.4 (diagonal of unit 4-cube)
    # Normalize: 1.0 at distance=0, ~0.5 at distance=0.3, ~0 at distance=1.0+
    raw_conf = 1.0 - min(best_dist / 1.0, 1.0)
    confidence = max(30, min(99, int(round(raw_conf * 100))))

    # Also blend in historical hit rate as a secondary confidence factor
    hit_conf = int(round(rec['hit_rate'] * 100))
    confidence = max(confidence, hit_conf - 10)
    confidence = min(99, confidence)

    return {
        'cluster_id': best_cluster,
        'rec_bet': rec['market'],
        'hit_rate': rec['hit_rate'],
        'avg_odds': rec['avg_odds'],
        'confidence': confidence,
        'distance': round(best_dist, 4),
        'label': rec['label'],
        'o15_odds': o15_odds,
        'o25_odds': o25_odds,
        'gg_odds': gg_odds,
        'u35_odds': u35_odds,
        'prob_vector': [round(v, 4) for v in vec],
    }


def classify_match_full_odds(odds_dict: Dict) -> Dict:
    """Classify from a dict containing o15, o25, gg, u35 keys."""
    return classify_match(
        odds_dict['o15'], odds_dict['o25'],
        odds_dict['gg'], odds_dict['u35']
    )


# ──────────────────────────────────────────────────────────────────────
# PICK SELECTION PER MATCHDAY
# ──────────────────────────────────────────────────────────────────────

def get_best_picks_per_matchday(matches_dict: Dict[int, List[Dict]],
                                top_n: int = 2) -> Dict[int, List[Dict]]:
    """From a dict of {matchday: [match_data...]}, select top picks.

    Each match_data must have keys:
        home_team, away_team, o15, o25, gg, u35
        + optionally total_goals, home_goals, away_goals for verification

    Picks are ranked by "edge" = historical_hit_rate - (1 / avg_odds).
    Higher edge = better value.  Top 2 per matchday.

    Returns:
        {matchday: [pick_dict, ...]}
    """
    picks_by_md = {}

    for md, fixtures in sorted(matches_dict.items()):
        scored = []
        for fx in fixtures:
            result = classify_match_full_odds(fx)
            if result['cluster_id'] == -1:
                continue

            # Edge = hit_rate - breakeven_rate
            breakeven = 1.0 / result['avg_odds'] if result['avg_odds'] > 0 else 1.0
            edge = result['hit_rate'] - breakeven

            scored.append({
                'home_team': fx.get('home_team', '?'),
                'away_team': fx.get('away_team', '?'),
                'match_day': md,
                'cluster_id': result['cluster_id'],
                'rec_bet': result['rec_bet'],
                'hit_rate': result['hit_rate'],
                'avg_odds': result['avg_odds'],
                'edge': round(edge, 4),
                'confidence': result['confidence'],
                'distance': result['distance'],
                'label': result['label'],
            })

        # Sort by edge descending, then confidence descending
        scored.sort(key=lambda x: (x['edge'], x['confidence']), reverse=True)
        picks_by_md[md] = scored[:top_n]

    return picks_by_md


def load_live_odds(season_id: str, matchday: int) -> List[Dict]:
    """Load matchday data and odds from PostgreSQL (v2 schema) - latest complete snapshot."""
    with get_db() as cursor:
        cursor.execute("""
            SELECT DISTINCT ON (event_id) 
                   event_id, home_team, away_team, o15, o25, u25, u35, gg, ng,
                   (SELECT home_goals FROM vfl_results_v2 r WHERE r.event_id = o.event_id LIMIT 1),
                   (SELECT away_goals FROM vfl_results_v2 r WHERE r.event_id = o.event_id LIMIT 1),
                   (SELECT total_goals FROM vfl_results_v2 r WHERE r.event_id = o.event_id LIMIT 1)
            FROM vfl_odds_v2 o
            WHERE season_id = %s AND matchday_number = %s
            ORDER BY event_id, 
                     (o15 IS NOT NULL AND o25 IS NOT NULL AND gg IS NOT NULL AND u35 IS NOT NULL) DESC,
                     captured_at DESC
        """, (season_id, matchday))
        rows = cursor.fetchall()
        
        results = []
        for r in rows:
            results.append({
                'event_id': r[0], 'home_team': r[1], 'away_team': r[2],
                'season_id': season_id, 'match_day': matchday,
                'o15': r[3], 'o25': r[4], 'u25': r[5], 'u35': r[6], 'gg': r[7], 'ng': r[8],
                'home_goals': r[9], 'away_goals': r[10], 'total_goals': r[11]
            })
        return results




def load_full_matchday_with_results(season_id: str, matchday: int) -> List[Dict]:
    """Load odds AND actual results for a specific matchday.

    Joins vfl_odds.event_details + deep_markets with vfl_results.results.
    """
    conn_odds = sqlite3.connect(ODDS_DB)
    conn_results = sqlite3.connect(RESULTS_DB)
    conn_odds.row_factory = sqlite3.Row
    conn_results.row_factory = sqlite3.Row

    try:
        # Get events
        events = conn_odds.execute("""
            SELECT e.event_id, e.season_id, e.season_name, e.match_day,
                   e.home_team, e.away_team
            FROM event_details e
            WHERE e.season_id = ? AND e.match_day = ?
            ORDER BY e.home_team
        """, (season_id, matchday)).fetchall()

        if not events:
            return []

        event_ids = [r['event_id'] for r in events]

        # Get odds
        placeholders = ','.join('?' * len(event_ids))
        odds_rows = conn_odds.execute(f"""
            SELECT event_id, market_name, specifiers, selection_name, odds
            FROM deep_markets
            WHERE event_id IN ({placeholders})
              AND (market_name = 'Over/Under' OR market_name = 'GG/NG')
        """, event_ids).fetchall()

        # Get results
        res_rows = conn_results.execute(f"""
            SELECT event_id, home_goals, away_goals, total_goals
            FROM results
            WHERE event_id IN ({placeholders})
        """, event_ids).fetchall()
        results_map = {r['event_id']: dict(r) for r in res_rows}

        # Build event -> odds map
        event_odds = {eid: {} for eid in event_ids}
        for row in odds_rows:
            eid = row['event_id']
            odds_val = row['odds']
            if odds_val is None or odds_val <= 0:
                continue
            mkt = row['market_name']
            spec = row['specifiers']
            sel = row['selection_name']

            if mkt == 'Over/Under':
                if spec == 'total=1.5':
                    if sel == 'Over 1.5':
                        event_odds[eid]['o15'] = odds_val
                    elif sel == 'Under 1.5':
                        event_odds[eid]['u15'] = odds_val
                elif spec == 'total=2.5':
                    if sel == 'Over 2.5':
                        event_odds[eid]['o25'] = odds_val
                    elif sel == 'Under 2.5':
                        event_odds[eid]['u25'] = odds_val
                elif spec == 'total=3.5':
                    if sel == 'Over 3.5':
                        event_odds[eid]['o35'] = odds_val
                    elif sel == 'Under 3.5':
                        event_odds[eid]['u35'] = odds_val
            elif mkt == 'GG/NG':
                if sel == 'Yes':
                    event_odds[eid]['gg'] = odds_val
                elif sel == 'No':
                    event_odds[eid]['ng'] = odds_val

        # Build final result list
        results = []
        for ev in events:
            eid = ev['event_id']
            od = event_odds.get(eid, {})
            res = results_map.get(eid, {})
            match_data = {
                'event_id': eid,
                'home_team': ev['home_team'],
                'away_team': ev['away_team'],
                'season_id': ev['season_id'],
                'season_name': ev['season_name'],
                'match_day': ev['match_day'],
                'o15': od.get('o15'),
                'u15': od.get('u15'),
                'o25': od.get('o25'),
                'u25': od.get('u25'),
                'o35': od.get('o35'),
                'u35': od.get('u35'),
                'gg': od.get('gg'),
                'ng': od.get('ng'),
                'home_goals': res.get('home_goals'),
                'away_goals': res.get('away_goals'),
                'total_goals': res.get('total_goals'),
            }
            results.append(match_data)

        return results

    finally:
        conn_odds.close()
        conn_results.close()


# ──────────────────────────────────────────────────────────────────────
# CLUSTER INFO
# ──────────────────────────────────────────────────────────────────────

def get_cluster_summary() -> List[Dict]:
    """Return a human-readable summary of all 8 clusters."""
    summaries = []
    for i in range(NUM_CLUSTERS):
        centroid_odds = [round(1.0 / p, 2) if p > 0 else float('inf') for p in CLUSTER_CENTROIDS[i]]
        rec = CLUSTER_RECOMMENDATIONS[i]
        summaries.append({
            'cluster_id': i,
            'centroid_probs': [round(p, 4) for p in CLUSTER_CENTROIDS[i]],
            'centroid_odds': centroid_odds,
            'rec_bet': rec['market'],
            'hit_rate': rec['hit_rate'],
            'avg_odds': rec['avg_odds'],
            'label': rec['label'],
        })
    return summaries


def get_cluster_stats_db() -> Dict:
    """Compute cluster statistics from the database (requires results DB)."""
    conn = sqlite3.connect(ODDS_DB)
    conn_results = sqlite3.connect(RESULTS_DB)
    conn.row_factory = sqlite3.Row

    try:
        # Get all matches with results and odds
        cursor = conn.execute("""
            SELECT e.event_id, e.season_id, e.season_name, e.match_day,
                   e.home_team, e.away_team
            FROM event_details e
        """)
        all_events = cursor.fetchall()

        event_ids = [r['event_id'] for r in all_events]
        if not event_ids:
            return {}

        # Batch get odds and results
        placeholders = ','.join('?' * len(event_ids))

        odds_rows = conn.execute(f"""
            SELECT event_id, market_name, specifiers, selection_name, odds
            FROM deep_markets
            WHERE event_id IN ({placeholders})
              AND (market_name = 'Over/Under' OR market_name = 'GG/NG')
        """, event_ids).fetchall()

        res_cursor = conn_results.execute(f"""
            SELECT event_id, home_goals, away_goals, total_goals
            FROM results WHERE event_id IN ({placeholders})
        """, event_ids)
        results_map = {r['event_id']: dict(r) for r in res_cursor.fetchall()}

        # Assign clusters
        cluster_counts = {i: 0 for i in range(NUM_CLUSTERS)}
        cluster_wins = {i: {m: 0 for m in ['O1.5', 'O2.5', 'U2.5', 'U3.5', 'GG', 'NG']}
                        for i in range(NUM_CLUSTERS)}
        cluster_totals = {i: {m: 0 for m in ['O1.5', 'O2.5', 'U2.5', 'U3.5', 'GG', 'NG']}
                          for i in range(NUM_CLUSTERS)}

        # Build event odds maps
        event_odds_map = {}
        for row in odds_rows:
            eid = row['event_id']
            if eid not in event_odds_map:
                event_odds_map[eid] = {}
            odds_val = row['odds']
            if odds_val is None or odds_val <= 0:
                continue
            mkt = row['market_name']
            spec = row['specifiers']
            sel = row['selection_name']
            if mkt == 'Over/Under':
                key = f"{spec.split('=')[1]}_{sel.split()[-1].lower()}"
                event_odds_map[eid][f"{sel.split()[-1].lower()}_{spec.split('=')[1]}".replace('.', '_')] = odds_val
                if spec == 'total=1.5' and sel == 'Over 1.5':
                    event_odds_map[eid]['o15'] = odds_val
                elif spec == 'total=1.5' and sel == 'Under 1.5':
                    event_odds_map[eid]['u15'] = odds_val
                elif spec == 'total=2.5' and sel == 'Over 2.5':
                    event_odds_map[eid]['o25'] = odds_val
                elif spec == 'total=2.5' and sel == 'Under 2.5':
                    event_odds_map[eid]['u25'] = odds_val
                elif spec == 'total=3.5' and sel == 'Over 3.5':
                    event_odds_map[eid]['o35'] = odds_val
                elif spec == 'total=3.5' and sel == 'Under 3.5':
                    event_odds_map[eid]['u35'] = odds_val
            elif mkt == 'GG/NG':
                if sel == 'Yes':
                    event_odds_map[eid]['gg'] = odds_val
                elif sel == 'No':
                    event_odds_map[eid]['ng'] = odds_val

        classified_count = 0
        for ev in all_events:
            eid = ev['event_id']
            od = event_odds_map.get(eid, {})
            res = results_map.get(eid)
            if res is None:
                continue
            if not all(k in od for k in ['o15', 'o25', 'gg', 'u35']):
                continue
            if any(od[k] is None or od[k] <= 1.0 for k in ['o15', 'o25', 'gg', 'u35']):
                continue

            result = classify_match_full_odds(od)
            if result['cluster_id'] == -1:
                continue

            cid = result['cluster_id']
            cluster_counts[cid] = cluster_counts.get(cid, 0) + 1
            classified_count += 1

            tg = res['total_goals']
            hg = res['home_goals']
            ag = res['away_goals']

            for market, verify_fn in MARKET_VERIFY.items():
                if verify_fn(tg, hg, ag):
                    cluster_wins[cid][market] += 1
                cluster_totals[cid][market] += 1

        # Build summary
        summary = {}
        for cid in range(NUM_CLUSTERS):
            n = cluster_counts.get(cid, 0)
            if n == 0:
                continue
            rates = {}
            for m in ['O1.5', 'O2.5', 'U2.5', 'U3.5', 'GG', 'NG']:
                t = cluster_totals[cid][m]
                if t > 0:
                    rates[m] = round(cluster_wins[cid][m] / t, 4)
                else:
                    rates[m] = 0.0
            summary[cid] = {
                'count': n,
                'rates': rates,
            }

        return {
            'total_classified': classified_count,
            'cluster_counts': cluster_counts,
            'clusters': summary,
        }

    finally:
        conn.close()
        conn_results.close()


# ──────────────────────────────────────────────────────────────────────
# SEASON ID RESOLVER
# ──────────────────────────────────────────────────────────────────────

def resolve_season_id(season_identifier: str) -> str:
    """Resolve a season identifier to a full vf:season:XXXXXX ID."""
    if not isinstance(season_identifier, str):
        season_identifier = str(season_identifier)
    if season_identifier.startswith('vf:season:'):
        return season_identifier
    import re
    match = re.search(r'(\d+)', season_identifier)
    if not match:
        return season_identifier
    season_num = match.group(1)
    
    with get_db() as cursor:
        cursor.execute("SELECT season_id FROM vfl_seasons WHERE season_name = %s LIMIT 1", (f'VFLM {season_num}',))
        row = cursor.fetchone()
        if row: return row[0]
        
        cursor.execute("SELECT season_id FROM vfl_seasons WHERE season_id LIKE %s LIMIT 1", (f'%:{season_num}',))
        row = cursor.fetchone()
        if row: return row[0]
        
    return season_identifier


# ──────────────────────────────────────────────────────────────────────
# COMMAND-LINE INTERFACE
# ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='VFL Odds Fingerprint Cluster Classifier',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--o15', type=float, help='Over 1.5 odds')
    group.add_argument('--season', type=str, help='Season ID (e.g. "vf:season:3091977" or "5113")')
    parser.add_argument('--matchday', type=int, help='Matchday number')
    parser.add_argument('--o25', type=float, help='Over 2.5 odds')
    parser.add_argument('--gg', type=float, help='GG odds')
    parser.add_argument('--u35', type=float, help='Under 3.5 odds')
    parser.add_argument('--batch', type=str, help='JSON file with fixture list')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--list-clusters', action='store_true', help='List cluster info')

    args = parser.parse_args()

    if args.list_clusters:
        summaries = get_cluster_summary()
        if args.json:
            print(json.dumps(summaries, indent=2))
        else:
            print("\n=== ODDS FINGERPRINT CLUSTERS ===")
            for s in summaries:
                print(f"\nCluster {s['cluster_id']}:")
                print(f"  Centroid (probs): {s['centroid_probs']}")
                print(f"  Centroid (odds):  {s['centroid_odds']}")
                print(f"  Recommended:      {s['label']}")
        return

    if args.o15 is not None:
        # Single match classification
        if any(x is None for x in [args.o25, args.gg, args.u35]):
            parser.error('--o15 requires --o25, --gg, --u35')
        result = classify_match(args.o15, args.o25, args.gg, args.u35)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\n=== CLASSIFICATION RESULT ===")
            print(f"  Cluster:    {result['cluster_id']}")
            print(f"  Odds:       O1.5={args.o15} O2.5={args.o25} GG={args.gg} U3.5={args.u35}")
            print(f"  Prob Vec:   {result['prob_vector']}")
            print(f"  Rec Bet:    {result['rec_bet']}")
            print(f"  Hit Rate:   {result['hit_rate']*100:.1f}%")
            print(f"  Avg Odds:   {result['avg_odds']:.2f}")
            print(f"  Confidence: {result['confidence']}%")
            print(f"  Distance:   {result['distance']}")
        return

    if args.season and args.matchday:
        # Load full matchday with results
        season_id = resolve_season_id(args.season)

        matches = load_live_odds(season_id, args.matchday)
        if not matches:
            print(json.dumps({'error': f'No matches found for {season_id} matchday {args.matchday}'}))
            sys.exit(1)

        results = []
        for m in matches:
            if all(m.get(k) is not None and m[k] > 1.0 for k in ['o15', 'o25', 'gg', 'u35']):
                cls = classify_match_full_odds(m)
                cls['home_team'] = m['home_team']
                cls['away_team'] = m['away_team']
                cls['event_id'] = m['event_id']
                results.append(cls)
            else:
                results.append({
                    'home_team': m['home_team'],
                    'away_team': m['away_team'],
                    'event_id': m.get('event_id'),
                    'error': 'Missing or invalid odds',
                    'cluster_id': -1,
                })

        # Compute best picks
        md_dict = {args.matchday: matches}
        picks = get_best_picks_per_matchday(md_dict, top_n=2)
        picks_output = {}
        if picks and args.matchday in picks:
            picks_output[str(args.matchday)] = picks[args.matchday]

        if args.json:
            output = {
                'season_id': season_id,
                'matchday': args.matchday,
                'classifications': results,
                'picks': picks_output,
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"\n=== MATCHDAY {args.matchday} CLASSIFICATION ({season_id}) ===")
            for r in results:
                if r.get('cluster_id') >= 0:
                    print(f"  {r['home_team']:20s} vs {r['away_team']:20s} → "
                          f"Cluster {r['cluster_id']}: {r['rec_bet']:5s} "
                          f"(HR:{r['hit_rate']*100:.0f}% Odds:{r['avg_odds']:.2f} Conf:{r['confidence']}%)")
                else:
                    print(f"  {r.get('home_team','?'):20s} vs {r.get('away_team','?'):20s} → "
                          f"{r.get('error','ERROR')}")

            # Also show best picks
            if picks and args.matchday in picks:
                print(f"\n=== TOP 2 PICKS ===")
                for p in picks[args.matchday]:
                    print(f"  {p['home_team']:20s} vs {p['away_team']:20s} → "
                          f"BET {p['rec_bet']:5s} @{p['avg_odds']:.2f} "
                          f"(Edge:{p['edge']*100:+.1f}% Conf:{p['confidence']}%)")


if __name__ == '__main__':
    main()
