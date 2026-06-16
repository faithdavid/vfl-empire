#!/usr/bin/env python3
"""
Pipeline Integration Bridge
============================
Bridges the fixture_intelligence engine with the odds_cluster_classifier
to produce final picks for the auto_bet_orchestrator.

Strategy:
  1. Run fixture_intelligence.py on the matchday to get ML-based picks
  2. Run odds_cluster_classifier on the same matchday to get cluster-based picks
  3. Find CONVERGENCE picks (both systems agree on the match AND the market)
  4. If no convergence, use whichever system has higher confidence
  5. Outputs final JSON ready for bet_placer

Called by orchestrator as:
    python pipeline_integration.py --season 5113 --matchday 3
    python pipeline_integration.py --season vf:season:3091977 --matchday 3 --json

Output format:
    {
        "season_id": "vf:season:3091977",
        "matchday": 3,
        "timestamp": "...",
        "picks": [
            {
                "home_team": "Team A",
                "away_team": "Team B",
                "market": "GG",
                "odds": 1.59,
                "confidence": 88,
                "source": "convergence|fixture_intelligence|cluster_classifier",
                "fi_confidence": 85,
                "cc_confidence": 88,
                "expected_value": 0.12,
                "stake_fraction": 0.25
            },
            ...
        ],
        "consensus_count": 1,
        "total_picks": 2
    }

Author: VFL Engineering Team
"""

import sqlite3
import json
import sys
import os
import subprocess
import tempfile
import math
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

# Add path for common tools
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db

BASE_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data'
SCRIPTS_DIR = '/home/ubuntu/faith-workspace/vfl-empire/scripts'
SIGNALS_DIR = os.path.join(BASE_DIR, 'signals')
OS = sys.platform

# Import cluster classifier
sys.path.insert(0, SCRIPTS_DIR)
from odds_cluster_classifier import (
    classify_match_full_odds, load_live_odds, get_best_picks_per_matchday,
    CLUSTER_RECOMMENDATIONS
)

# ──────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────
MIN_CONFIDENCE = 80       # Minimum confidence to even consider a pick (raised from 70)
MIN_EDGE_FOR_STAKE = 0.05 # 5% edge minimum to stake full amount (raised from 3%)
MAX_PICKS_PER_MATCHDAY = 1  # CHANGED: Only pick 1 best bet per matchday to avoid 1-win-1-lose pattern
STAKE_BASE = 0.25         # Fraction of bankroll per pick (for bet_placer)
STAKE_BOOST = 0.35        # Boosted fraction for high-conviction picks

# Analytics-optimized matchday windows (from prediction_analytics_report.json)
# These windows have the highest historical hit rates
OPTIMAL_MATCHDAY_WINDOWS = [
    (20, 22, 0.751, 239),   # MD20-MD22: 75.1% (239/315 samples)
    (13, 15, 0.749, 213),   # MD13-MD15: 74.9% (213/281 samples)
    (14, 16, 0.745, 224),   # MD14-MD16: 74.5% (224/298 samples)
    (13, 17, 0.743, 297),   # MD13-MD17: 74.3% (297/397 samples) — BROADEST
]
# Only bet during these windows to maximize success rate
ENFORCE_OPTIMAL_WINDOWS = False  # Set True to only bet on optimal matchdays


# ──────────────────────────────────────────────────────────────────────
# SEASON ID RESOLVER
# ──────────────────────────────────────────────────────────────────────

def resolve_season_id(season_identifier: str) -> str:
    """Resolve a season identifier to a full vf:season:XXXXXX ID.

    Accepts:
      - Full ID:  'vf:season:3091977'
      - Number:   '5113' or 5113
      - Name:     'VFLM 5113'
    """
    if not isinstance(season_identifier, str):
        season_identifier = str(season_identifier)

    # Already a full ID
    if season_identifier.startswith('vf:season:'):
        return season_identifier

    # Extract the number
    import re
    match = re.search(r'(\d+)', season_identifier)
    if not match:
        return season_identifier
    season_num = match.group(1)

    # Query the DB to find the matching season_id
    with get_db() as cursor:
        # Try matching by season_name first (e.g. 'VFLM 5113')
        cursor.execute("""
            SELECT season_id
            FROM vfl_seasons
            WHERE season_name = %s
            LIMIT 1
        """, (f'VFLM {season_num}',))
        row = cursor.fetchone()

        if row:
            return row[0]

        # Broader: match by last digits of season_id
        cursor.execute("""
            SELECT season_id
            FROM vfl_seasons
            WHERE season_id LIKE %s
            LIMIT 1
        """, (f'%:{season_num}',))
        row = cursor.fetchone()

        if row:
            return row[0]

        # Return as-is and let the caller handle the error
        return season_identifier


# ──────────────────────────────────────────────────────────────────────
# FIXTURE INTELLIGENCE INTERFACE
# ──────────────────────────────────────────────────────────────────────

def load_matchday_fixtures(season_id: str, matchday: int) -> List[Dict]:
    """Load fixture list for a season+matchday from the vfl_results_v2 table."""
    with get_db() as cursor:
        cursor.execute("""
            SELECT DISTINCT home_team, away_team
            FROM vfl_results_v2 r
            JOIN vfl_matchdays m ON r.matchday_id = m.id
            JOIN vfl_seasons s ON m.season_id = s.id
            WHERE s.season_id = %s AND m.matchday_number = %s
            ORDER BY home_team
        """, (season_id, matchday))
        return [{'home_team': r[0], 'away_team': r[1]} for r in cursor.fetchall()]


def run_fixture_intelligence(fixtures: List[Dict]) -> Dict:
    """Run fixture_intelligence.py on a list of fixtures via --batch.

    Returns parsed JSON output as a list of result dicts keyed by
    fixture tuple (home, away).
    """
    if not fixtures:
        return {}

    # Write fixtures to temp JSON file as (home, away) tuples
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump([(fx['home_team'], fx['away_team']) for fx in fixtures], f)
        temp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable,
             os.path.join(SCRIPTS_DIR, 'fixture_intelligence.py'),
             '--batch', temp_path, '--json'],
            capture_output=True, text=True,
            cwd=SCRIPTS_DIR,
            timeout=120,
        )

        if result.returncode != 0:
            print(f"WARNING: fixture_intelligence.py returned {result.returncode}",
                  file=sys.stderr)
            print(f"STDERR: {result.stderr[:500]}", file=sys.stderr)
            return {}

        try:
            fi_results = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"WARNING: Could not parse fixture_intelligence JSON: {e}",
                  file=sys.stderr)
            print(f"RAW: {result.stdout[:300]}", file=sys.stderr)
            return {}

        # Index by (home, away) tuple
        indexed = {}
        for r in fi_results:
            if 'fixture' in r:
                key = (r['fixture']['home_team'], r['fixture']['away_team'])
                indexed[key] = r
            elif 'error' in r:
                # Fixture intelligence returns error objects for invalid fixtures
                pass
        return indexed

    except subprocess.TimeoutExpired:
        print("WARNING: fixture_intelligence.py timed out after 120s", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"WARNING: Error running fixture_intelligence: {e}", file=sys.stderr)
        return {}
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────────
# CLUSTER CLASSIFIER INTERFACE
# ──────────────────────────────────────────────────────────────────────

def run_cluster_classifier(season_id: str, matchday: int) -> Dict:
    """Run cluster classifier on a matchday, returning picks indexed by fixture.

    Returns { (home, away): pick_dict }.
    """
    matches = load_live_odds(season_id, matchday)
    if not matches:
        return {}

    # Classify each match
    classified = {}
    for m in matches:
        if not all(m.get(k) is not None and m[k] > 1.0 for k in ['o15', 'o25', 'gg', 'u35']):
            continue

        cls = classify_match_full_odds(m)
        if cls['cluster_id'] == -1:
            continue

        key = (m['home_team'], m['away_team'])
        classified[key] = {
            'home_team': m['home_team'],
            'away_team': m['away_team'],
            'market': cls['rec_bet'],
            'odds': cls['avg_odds'],
            'hit_rate': cls['hit_rate'],
            'confidence': cls['confidence'],
            'edge': cls['hit_rate'] - (1.0 / cls['avg_odds']) if cls['avg_odds'] > 0 else 0,
            'cluster_id': cls['cluster_id'],
            'distance': cls['distance'],
            'label': cls['label'],
            'source': 'cluster_classifier',
        }

    return classified


# ──────────────────────────────────────────────────────────────────────
# CONSENSUS & PICK MERGING
# ──────────────────────────────────────────────────────────────────────

def normalize_market(market: str) -> str:
    """Normalize market names between systems."""
    mapping = {
        'over 1.5': 'O1.5', 'Over 1.5': 'O1.5',
        'over 2.5': 'O2.5', 'Over 2.5': 'O2.5',
        'under 2.5': 'U2.5', 'Under 2.5': 'U2.5',
        'under 3.5': 'U3.5', 'Under 3.5': 'U3.5',
        'GG': 'GG', 'gg': 'GG', 'Goal-Goal': 'GG',
        'NG': 'NG', 'ng': 'NG', 'No Goal': 'NG',
        'O1.5': 'O1.5', 'O2.5': 'O2.5',
        'U2.5': 'U2.5', 'U3.5': 'U3.5',
    }
    return mapping.get(market, market)


def compute_ev(hit_rate: float, odds: float) -> float:
    """Compute expected value: (hit_rate * odds) - 1"""
    if odds <= 0:
        return 0.0
    return round((hit_rate * odds) - 1.0, 4)


def merge_picks(fi_picks: Dict, cc_picks: Dict, fixtures: List[Dict]) -> Dict:
    """Merge fixture_intelligence and cluster_classifier picks.

    Strategy:
      1. Find all fixtures that have valid picks from either system
      2. For each fixture:
         a. If both systems agree on market → CONVERGENCE (highest priority)
         b. Pick the system with higher confidence
      3. Sort by confidence descending, take top 2
      4. Assign stake fractions based on conviction level
    """
    picks_by_fixture = {}

    all_keys = set(list(fi_picks.keys()) + list(cc_picks.keys()))
    for key in all_keys:
        home, away = key
        fi = fi_picks.get(key)
        cc = cc_picks.get(key)

        entry = {
            'home_team': home,
            'away_team': away,
            'sources': [],
            'convergence': False,
        }

        best_pick = None

        if fi and cc:
            # Both systems have picks for this fixture
            fi_market = normalize_market(fi.get('recommended_market', ''))
            cc_market = cc['market']

            fi_confidence = fi.get('confidence', 0)
            cc_confidence = cc['confidence']

            fi_odds = None  # Will try to get from CC or compute
            cc_odds = cc['odds']

            # Check for convergence (same market recommendation)
            if fi_market == cc_market:
                entry['convergence'] = True
                entry['source'] = 'convergence'
                entry['fi_confidence'] = fi_confidence
                entry['cc_confidence'] = cc_confidence
                best_pick = {
                    'market': cc_market,
                    'odds': cc_odds,
                    'hit_rate': cc['hit_rate'],
                    'confidence': max(fi_confidence, cc_confidence),
                    'fi_confidence': fi_confidence,
                    'cc_confidence': cc_confidence,
                    'edge': cc['edge'],
                }
            else:
                # Divergence — pick the higher-confidence system
                if fi_confidence >= cc_confidence:
                    # Use FI pick
                    fi_hit_rate = _estimate_hit_rate_from_confidence(fi_confidence)
                    fi_edge = fi_hit_rate - (1.0 / _estimate_odds_from_market(fi_market, cc_odds))
                    best_pick = {
                        'market': fi_market,
                        'odds': _estimate_odds_from_market(fi_market, cc_odds),
                        'hit_rate': fi_hit_rate,
                        'confidence': fi_confidence,
                        'fi_confidence': fi_confidence,
                        'cc_confidence': cc_confidence,
                        'edge': fi_edge,
                    }
                    entry['source'] = 'fixture_intelligence'
                else:
                    best_pick = {
                        'market': cc_market,
                        'odds': cc_odds,
                        'hit_rate': cc['hit_rate'],
                        'confidence': cc_confidence,
                        'fi_confidence': fi_confidence,
                        'cc_confidence': cc_confidence,
                        'edge': cc['edge'],
                    }
                    entry['source'] = 'cluster_classifier'

        elif fi:
            # Only fixture intelligence has a pick
            fi_market = normalize_market(fi.get('recommended_market', ''))
            fi_confidence = fi.get('confidence', 0)
            fi_hit_rate = _estimate_hit_rate_from_confidence(fi_confidence)
            fi_edge = fi_hit_rate - (1.0 / _estimate_odds_from_market(fi_market, 1.7))
            best_pick = {
                'market': fi_market,
                'odds': _estimate_odds_from_market(fi_market, 1.7),
                'hit_rate': fi_hit_rate,
                'confidence': fi_confidence,
                'fi_confidence': fi_confidence,
                'cc_confidence': 0,
                'edge': fi_edge,
            }
            entry['source'] = 'fixture_intelligence'

        elif cc:
            # Only cluster classifier has a pick
            best_pick = {
                'market': cc['market'],
                'odds': cc['odds'],
                'hit_rate': cc['hit_rate'],
                'confidence': cc['confidence'],
                'fi_confidence': 0,
                'cc_confidence': cc['confidence'],
                'edge': cc['edge'],
            }
            entry['source'] = 'cluster_classifier'

        if best_pick is not None and best_pick['confidence'] >= MIN_CONFIDENCE:
            best_pick['expected_value'] = compute_ev(best_pick['hit_rate'], best_pick['odds'])
            best_pick['stake_fraction'] = _compute_stake_fraction(
                best_pick['edge'], best_pick['confidence']
            )
            entry['pick'] = best_pick
            picks_by_fixture[key] = entry

    # Sort by confidence descending, take top 2
    sorted_picks = sorted(
        [v for v in picks_by_fixture.values() if 'pick' in v],
        key=lambda x: x['pick']['confidence'],
        reverse=True,
    )

    top_picks = sorted_picks[:MAX_PICKS_PER_MATCHDAY]

    # Build output
    consensus_count = sum(1 for p in top_picks if p.get('convergence'))
    total_picks = len(top_picks)

    picks_output = []
    for p in top_picks:
        picks_output.append({
            'home_team': p['home_team'],
            'away_team': p['away_team'],
            'market': p['pick']['market'],
            'odds': p['pick']['odds'],
            'confidence': p['pick']['confidence'],
            'source': p['source'],
            'convergence': p.get('convergence', False),
            'fi_confidence': p['pick']['fi_confidence'],
            'cc_confidence': p['pick']['cc_confidence'],
            'expected_value': p['pick']['expected_value'],
            'edge': p['pick']['edge'],
            'stake_fraction': p['pick']['stake_fraction'],
            'hit_rate': p['pick']['hit_rate'],
        })

    return {
        'picks': picks_output,
        'consensus_count': consensus_count,
        'total_picks': total_picks,
        'source_breakdown': {
            'convergence': sum(1 for p in top_picks if p.get('convergence')),
            'fixture_intelligence': sum(1 for p in top_picks if p['source'] == 'fixture_intelligence'),
            'cluster_classifier': sum(1 for p in top_picks if p['source'] == 'cluster_classifier'),
        }
    }


def _estimate_hit_rate_from_confidence(confidence: int) -> float:
    """Convert a confidence percentage to an estimated hit rate."""
    # FI confidence maps roughly: 55%→0.60, 70%→0.72, 80%→0.80, 93%→0.88
    if confidence >= 90:
        return 0.85
    elif confidence >= 80:
        return 0.78
    elif confidence >= 70:
        return 0.72
    elif confidence >= 60:
        return 0.65
    else:
        return 0.58


def _estimate_odds_from_market(market: str, default_odds: float) -> float:
    """Get typical odds for a market type when actual odds unavailable."""
    odds_map = {
        'O1.5': 1.30, 'U1.5': 3.50,
        'O2.5': 2.00, 'U2.5': 1.70,
        'O3.5': 3.50, 'U3.5': 1.30,
        'GG': 1.80, 'NG': 1.90,
    }
    return odds_map.get(market, default_odds)


def _compute_stake_fraction(edge: float, confidence: int) -> float:
    """Compute Kelly-like stake fraction based on edge and confidence.

    Returns fraction of bankroll to stake.
    """
    if edge <= 0:
        return 0.0

    # Base from confidence
    if confidence >= 90:
        base = STAKE_BOOST
    elif confidence >= 80:
        base = STAKE_BASE
    elif confidence >= 70:
        base = 0.15
    else:
        base = 0.0

    # Adjust by edge
    edge_multiplier = min(edge * 5, 1.5)  # Scale: 3% edge→1.15x, 10% edge→1.5x
    fraction = base * edge_multiplier

    return round(min(fraction, 0.40), 3)  # Never more than 40% of bankroll


# ──────────────────────────────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────────────────────────────

def build_output(merged: Dict, season_id: str, matchday: int) -> Dict:
    """Build the final output dict ready for bet_placer."""
    return {
        'season_id': season_id,
        'matchday': matchday,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'generated_by': 'pipeline_integration_bridge',
        'version': '1.0.0',
        **merged,
        'has_picks': len(merged.get('picks', [])) > 0,
    }


def save_signals(output: Dict):
    """Save picks to signals directory for the orchestrator."""
    os.makedirs(SIGNALS_DIR, exist_ok=True)
    md = output.get('matchday', 'unknown')
    path = os.path.join(SIGNALS_DIR, f'pipeline_picks_md{md}.json')
    with open(path, 'w') as f:
        json.dump(output, f, indent=2)
    return path


# ──────────────────────────────────────────────────────────────────────
# ORCHESTRATOR OUTPUT BRIDGE
# ──────────────────────────────────────────────────────────────────────

def _market_to_orchestrator_name(market_code: str) -> str:
    """Convert internal market codes to orchestrator/bet-placer display names."""
    mapping = {
        'GG': 'BTTS Yes',
        'NG': 'BTTS No',
        'O1.5': 'Over 1.5 Goals',
        'O2.5': 'Over 2.5 Goals',
        'U1.5': 'Under 1.5 Goals',
        'U2.5': 'Under 2.5 Goals',
        'U3.5': 'Under 3.5 Goals',
    }
    return mapping.get(market_code, market_code)


def _classify_strength(hit_rate: float) -> str:
    """Classify pick strength based on historical hit rate."""
    if hit_rate >= 0.58:
        return 'STRONG'
    elif hit_rate >= 0.50:
        return 'MODERATE'
    return 'WEAK'


def _lookup_event_id(season_id: str, matchday: int,
                     home_team: str, away_team: str) -> str:
    """Look up event_id from the odds database for a given fixture."""
    conn = sqlite3.connect(ODDS_DB)
    try:
        rows = conn.execute("""
            SELECT event_id FROM event_details
            WHERE season_id = ? AND match_day = ?
              AND home_team = ? AND away_team = ?
            LIMIT 1
        """, (season_id, matchday, home_team, away_team)).fetchall()
        return rows[0][0] if rows else ''
    finally:
        conn.close()


def _lookup_season_name(season_id: str) -> str:
    """Look up the human-readable season name from the odds database."""
    conn = sqlite3.connect(ODDS_DB)
    try:
        rows = conn.execute("""
            SELECT DISTINCT season_name FROM event_details
            WHERE season_id = ?
            LIMIT 1
        """, (season_id,)).fetchall()
        return rows[0][0] if rows else season_id
    finally:
        conn.close()


def save_orchestrator_format(output: Dict, season_id: str, matchday: int,
                             all_cc_picks: Optional[Dict] = None) -> str:
    """Convert pipeline output to orchestrator-compatible format and save.

    The orchestrator (auto_bet_orchestrator.py) loads predictions from:
      BASE_DIR / "signals" / "live_test_predictions.json"

    Expected orchestrator format:
    {
      "matchdays": [{
        "season_name": "VFLM 5113",
        "season_id": "vf:season:3091977",
        "matchday": 3,
        "fixtures": [{
          "home": "Chelsea",
          "away": "Brighton",
          "event_id": "event_123",
          "prediction": {
            "primary": {
              "market": "GG",
              "odds": 1.59,
              "confidence_pct": 80,
              "strength": "STRONG"
            }
          }
        }]
      }]
    }
    """
    os.makedirs(SIGNALS_DIR, exist_ok=True)

    season_name = _lookup_season_name(season_id)
    picks = output.get('picks', [])
    # Build a lookup of picks by (home, away) for fast access
    pick_lookup = {(p.get('home_team', ''), p.get('away_team', '')): p for p in picks}

    fixtures = []
    
    # If we have all_cc_picks, iterate ALL classified fixtures
    # Otherwise, use only the top picks from the pipeline
    source_picks = all_cc_picks if all_cc_picks else {(p.get('home_team',''), p.get('away_team','')): {
        'home_team': p.get('home_team',''), 'away_team': p.get('away_team',''),
        'market': p.get('market',''), 'odds': p.get('odds',0), 'hit_rate': p.get('hit_rate',0),
        'confidence': p.get('confidence',0), 'edge': p.get('edge',0),
    } for p in picks}
    
    for key in source_picks:
        home, away = key
        # Use pipeline top pick if available, otherwise fall back to CC pick
        if (home, away) in pick_lookup:
            pick = pick_lookup[(home, away)]
        else:
            pick = source_picks[key]
        
        market_code = pick.get('market', '')
        odds = pick.get('odds', 0.0)
        hit_rate = pick.get('hit_rate', 0.0)
        # Use TRUE hit_rate as confidence_pct (honest probability)
        # Strength is based on edge vs breakeven
        if odds > 0:
            edge = hit_rate - (1.0 / odds)
        else:
            edge = 0.0
        confidence_pct = int(round(hit_rate * 100))
        if edge >= 0.03:
            strength = 'STRONG'
        elif edge >= 0.0:
            strength = 'MODERATE'
        else:
            strength = 'WEAK'
        event_id = pick.get('event_id', '') or _lookup_event_id(
            season_id, matchday, home, away
        )
        market_name = _market_to_orchestrator_name(market_code)

        fixtures.append({
            'home': home,
            'away': away,
            'event_id': event_id,
            'prediction': {
                'primary': {
                    'market': market_name,
                    'odds': odds,
                    'confidence_pct': confidence_pct,
                    'strength': strength,
                }
            }
        })

    orchestrator_data = {
        'matchdays': [{
            'season_name': season_name,
            'season_id': season_id,
            'matchday': matchday,
            'fixtures': fixtures,
        }]
    }

    path = os.path.join(SIGNALS_DIR, 'live_test_predictions.json')
    with open(path, 'w') as f:
        json.dump(orchestrator_data, f, indent=2)
    return path


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Pipeline Integration Bridge — merges FI + cluster picks',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --season 5113 --matchday 3
  %(prog)s --season vf:season:3091977 --matchday 3 --json
  %(prog)s --season 5113 --matchday 3 --no-fi  (skip fixture intelligence)
        """,
    )
    parser.add_argument('--season', required=True, help='Season ID or number')
    parser.add_argument('--matchday', required=True, type=int, help='Matchday number')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--no-fi', action='store_true', help='Skip fixture intelligence (cluster only)')
    parser.add_argument('--save', action='store_true', help='Save signals to disk')
    parser.add_argument('--save-orchestrator', action='store_true',
                        help='Save picks in orchestrator-compatible format to '
                             'signals/live_test_predictions.json')

    args = parser.parse_args()

    # Resolve season ID (handles numbers like 5113, names like 'VFLM 5113', or full IDs)
    season_id = resolve_season_id(args.season)

    matchday = args.matchday

    # Step 1: Load fixtures from DB
    fixtures = load_matchday_fixtures(season_id, matchday)
    if not fixtures:
        error = f"No fixtures found for {season_id} matchday {matchday}"
        result = {'error': error, 'season_id': season_id, 'matchday': matchday}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"ERROR: {error}")
        sys.exit(1)

    if not args.json:
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"  PIPELINE INTEGRATION BRIDGE", file=sys.stderr)
        print(f"  Season: {season_id}", file=sys.stderr)
        print(f"  Matchday: {matchday}", file=sys.stderr)
        print(f"  Fixtures: {len(fixtures)}", file=sys.stderr)
        print(f"{'=' * 60}", file=sys.stderr)

    # Step 2: Run cluster classifier
    if not args.json:
        print("\n  [1/3] Running cluster classifier...", file=sys.stderr)
    cc_picks = run_cluster_classifier(season_id, matchday)
    if not args.json:
        print(f"  → {len(cc_picks)} matches classified", file=sys.stderr)

    # Step 3: Run fixture intelligence (unless --no-fi)
    fi_picks = {}
    if not args.no_fi:
        if not args.json:
            print("  [2/3] Running fixture intelligence engine...", file=sys.stderr)
        fi_picks = run_fixture_intelligence(fixtures)
        if not args.json:
            print(f"  → {len(fi_picks)} fixtures analyzed", file=sys.stderr)

    # Step 4: Merge picks
    if not args.json:
        print("  [3/3] Merging picks (consensus + confidence)...", file=sys.stderr)
    merged = merge_picks(fi_picks, cc_picks, fixtures)
    output = build_output(merged, season_id, matchday)

    # Save signals if requested
    if args.save:
        path = save_signals(output)
        if not args.json:
            print(f"  → Signals saved to {path}", file=sys.stderr)

    # Save orchestrator-compatible predictions if requested
    if args.save_orchestrator:
        # Pass ALL cluster picks so orchestrator has full fixture list
        orch_path = save_orchestrator_format(output, season_id, matchday, all_cc_picks=cc_picks)
        if not args.json:
            print(f"  → Orchestrator predictions saved to {orch_path}", file=sys.stderr)

    # Output
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        if 'error' in output:
            print(f"\nERROR: {output['error']}")
            return

        print(f"\n  {'=' * 56}")
        print(f"  FINAL PICKS")
        print(f"  {'=' * 56}")
        for i, p in enumerate(output['picks'], 1):
            convergence_tag = "✓ CONVERGENCE" if p.get('convergence') else ""
            print(f"\n  Pick #{i}: {p['home_team']:20s} vs {p['away_team']:20s}")
            print(f"    Market:     {p['market']}")
            print(f"    Odds:       {p['odds']:.2f}")
            print(f"    Confidence: {p['confidence']}%  {convergence_tag}")
            print(f"    Source:     {p['source']}")
            print(f"    Edge:       {p['edge']*100:+.1f}%")
            print(f"    EV:         {p['expected_value']:+.3f}")
            print(f"    Stake:      {p['stake_fraction']*100:.0f}% of bankroll")
            if p.get('fi_confidence') and p.get('cc_confidence'):
                print(f"    FI: {p['fi_confidence']}% | CC: {p['cc_confidence']}%")

        print(f"\n  Convergence: {output['consensus_count']}/{output['total_picks']} picks")
        print(f"  {output['source_breakdown']}")
        print(f"  {'=' * 56}\n")

        if output['has_picks']:
            # Print a compact one-line summary for the orchestrator to parse
            summary = ' | '.join(
                f"{p['home_team'][:12]}-{p['away_team'][:12]}: {p['market']} @{p['odds']:.2f}"
                for p in output['picks']
            )
            print(f"PICKS: {summary}")


if __name__ == '__main__':
    main()
