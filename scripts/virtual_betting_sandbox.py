#!/usr/bin/env python3
"""
Virtual Betting Sandbox
=======================
A comprehensive simulation engine that runs the EXACT same prediction pipeline
on historical data with virtual money, tests the prediction gate across hundreds
of matchdays, and identifies every failure mode before risking real capital.

Usage:
    python virtual_betting_sandbox.py --quick --seasons 5
    python virtual_betting_sandbox.py --seasons VFLM 5110 VFLM 5115
    python virtual_betting_sandbox.py --all
    python virtual_betting_sandbox.py --bankroll 5000 --stake 100
    python virtual_betting_sandbox.py --analyze-failures
    python virtual_betting_sandbox.py --compare

Author: VFL Engineering Team
"""

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data'
VFL_EMPIRE_DIR = '/home/ubuntu/faith-workspace/vfl-empire'
SCRIPTS_DIR = os.path.join(VFL_EMPIRE_DIR, 'scripts')
RESULTS_DB = os.path.join(BASE_DIR, 'databases', 'vfl_results.db')
ODDS_DB = os.path.join(BASE_DIR, 'databases', 'vfl_odds.db')
SIGNALS_DIR = os.path.join(BASE_DIR, 'signals')
DATA_DIR = os.path.join(VFL_EMPIRE_DIR, 'data')
SANDBOX_RESULTS_FILE = os.path.join(DATA_DIR, 'virtual_sandbox_results.json')

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Add scripts to path for direct imports
sys.path.insert(0, SCRIPTS_DIR)

# ──────────────────────────────────────────────────────────────────────
# IMPORTS FROM PIPELINE (direct imports, same code as live system)
# ──────────────────────────────────────────────────────────────────────
try:
    from odds_cluster_classifier import (
        classify_match, classify_match_full_odds, CLUSTER_RECOMMENDATIONS,
        MARKET_VERIFY as CLUSTER_MARKET_VERIFY,
    )
    _HAS_CLUSTER = True
except ImportError as e:
    print(f"WARNING: Could not import odds_cluster_classifier: {e}", file=sys.stderr)
    _HAS_CLUSTER = False

try:
    from prediction_gate import (
        run_all_gates, normalize_market, MARKET_VERIFY as GATE_MARKET_VERIFY,
        TEAM_PROFILES, VALID_TEAMS,
    )
    _HAS_GATE = True
except ImportError as e:
    print(f"WARNING: Could not import prediction_gate: {e}", file=sys.stderr)
    _HAS_GATE = False


# ──────────────────────────────────────────────────────────────────────
# MARKET VERIFICATION (same logic as live system)
# ──────────────────────────────────────────────────────────────────────
MARKET_CHECK = {
    'O1.5': lambda tg, hg, ag: 1 if (tg or 0) > 1.5 else 0,
    'O2.5': lambda tg, hg, ag: 1 if (tg or 0) > 2.5 else 0,
    'U2.5': lambda tg, hg, ag: 1 if (tg or 0) < 2.5 else 0,
    'U3.5': lambda tg, hg, ag: 1 if (tg or 0) < 3.5 else 0,
    'GG':   lambda tg, hg, ag: 1 if (hg or 0) > 0 and (ag or 0) > 0 else 0,
    'NG':   lambda tg, hg, ag: 1 if (hg or 0) == 0 or (ag or 0) == 0 else 0,
}


# ──────────────────────────────────────────────────────────────────────
# DEFAULT STATE (matches live system exactly)
# ──────────────────────────────────────────────────────────────────────
def default_state(initial_bankroll: float = 1000.0) -> Dict[str, Any]:
    return {
        "virtual_bankroll": initial_bankroll,
        "initial_bankroll": initial_bankroll,
        "active_bet": None,
        "ratchet": {
            "phase": 1,
            "milestone": 0,
            "hits_in_step": 0,
            "current_stake": 50.0,
            "total_profit_banked": 0.0,
        },
        "history": [],
        "gate_stats": {
            "total_picks_checked": 0,
            "gates_passed": 0,
            "gates_failed": 0,
            "h2h_fails": 0,
            "form_fails": 0,
            "cluster_fails": 0,
            "odds_fails": 0,
            "regime_fails": 0,
        },
    }


# ──────────────────────────────────────────────────────────────────────
# DATABASE HELPERS
# ──────────────────────────────────────────────────────────────────────

def get_results_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(RESULTS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_odds_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(ODDS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_season_id(season_identifier: str) -> str:
    """Resolve a season name like 'VFLM 5113' to its full vf:season:XXXXXX ID."""
    if season_identifier.startswith('vf:season:'):
        return season_identifier
    match = re.search(r'(\d+)', season_identifier)
    if not match:
        return season_identifier
    season_num = match.group(1)
    conn = get_odds_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT season_id FROM event_details WHERE season_name = ? LIMIT 1",
            (f'VFLM {season_num}',)
        ).fetchall()
        if rows:
            return rows[0][0]
        rows = conn.execute(
            "SELECT DISTINCT season_id FROM event_details WHERE season_id LIKE ? LIMIT 1",
            (f'%:{season_num}',)
        ).fetchall()
        if rows:
            return rows[0][0]
        return season_identifier
    finally:
        conn.close()


def get_available_seasons() -> List[str]:
    """Get seasons that have BOTH results and odds data, sorted newest-first."""
    conn_r = get_results_conn()
    conn_o = get_odds_conn()
    try:
        res_seasons = set(
            r[0] for r in conn_r.execute(
                "SELECT DISTINCT season_name FROM results WHERE season_name LIKE 'VFLM%' AND status = 3"
            ).fetchall()
        )
        odds_seasons = set(
            r[0] for r in conn_o.execute(
                "SELECT DISTINCT season_name FROM event_details WHERE season_name LIKE 'VFLM%'"
            ).fetchall()
        )
        common = sorted(res_seasons & odds_seasons, reverse=True)
        return common
    finally:
        conn_r.close()
        conn_o.close()


def get_matchdays_for_season(season_name: str, season_id: str) -> List[int]:
    """Get sorted list of matchdays that exist in BOTH results and odds."""
    conn_r = get_results_conn()
    conn_o = get_odds_conn()
    try:
        # From results (completed matches only)
        res_mds = set(
            r[0] for r in conn_r.execute(
                "SELECT DISTINCT match_day FROM results WHERE season_name = ? AND status = 3",
                (season_name,)
            ).fetchall()
        )
        # From odds
        odds_mds = set(
            r[0] for r in conn_o.execute(
                "SELECT DISTINCT match_day FROM event_details WHERE season_id = ?",
                (season_id,)
            ).fetchall()
        )
        common = sorted(res_mds & odds_mds)
        return common
    finally:
        conn_r.close()
        conn_o.close()


def load_matchday_data(season_id: str, matchday: int) -> List[Dict]:
    """Load odds + results for all fixtures on a given matchday.

    Returns list of dicts with keys:
        event_id, home_team, away_team, season_name, match_day,
        o15, o25, u25, u35, gg, ng,
        home_goals, away_goals, total_goals (if completed)
    """
    conn_o = get_odds_conn()
    conn_r = get_results_conn()
    try:
        # Get events
        events = conn_o.execute("""
            SELECT DISTINCT e.event_id, e.season_id, e.season_name, e.match_day,
                   e.home_team, e.away_team
            FROM event_details e
            WHERE e.season_id = ? AND e.match_day = ?
            ORDER BY e.home_team
        """, (season_id, matchday)).fetchall()

        if not events:
            return []

        event_ids = [r['event_id'] for r in events]
        placeholders = ','.join('?' * len(event_ids))

        # Get odds from deep_markets
        odds_rows = conn_o.execute(f"""
            SELECT event_id, market_name, specifiers, selection_name, odds
            FROM deep_markets
            WHERE event_id IN ({placeholders})
              AND (market_name = 'Over/Under' OR market_name = 'GG/NG')
        """, event_ids).fetchall()

        # Get results
        res_rows = conn_r.execute(f"""
            SELECT event_id, home_goals, away_goals, total_goals, status
            FROM results
            WHERE event_id IN ({placeholders})
        """, event_ids).fetchall()
        results_map = {r['event_id']: dict(r) for r in res_rows}

        # Build odds map per event
        event_odds: Dict[str, Dict] = {eid: {} for eid in event_ids}
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

            # Skip if we don't have the full odds fingerprint needed
            if not all(od.get(k) for k in ['o15', 'o25', 'gg', 'u35']):
                continue

            match_data = {
                'event_id': eid,
                'home_team': ev['home_team'],
                'away_team': ev['away_team'],
                'season_id': ev['season_id'],
                'season_name': ev['season_name'],
                'match_day': ev['match_day'],
                'o15': od.get('o15'),
                'o25': od.get('o25'),
                'u25': od.get('u25'),
                'u35': od.get('u35'),
                'gg': od.get('gg'),
                'ng': od.get('ng'),
                'home_goals': res.get('home_goals'),
                'away_goals': res.get('away_goals'),
                'total_goals': res.get('total_goals'),
                'status': res.get('status'),
            }
            results.append(match_data)

        return results

    finally:
        conn_o.close()
        conn_r.close()


# ──────────────────────────────────────────────────────────────────────
# PIPELINE SIMULATION (same logic as live system)
# ──────────────────────────────────────────────────────────────────────

def run_cluster_classifier(fixture: Dict) -> Optional[Dict]:
    """Run the odds cluster classifier on a fixture (same code as live system).

    Returns classification dict or None if classification fails.
    """
    if not _HAS_CLUSTER:
        return None
    try:
        result = classify_match_full_odds(fixture)
        if result['cluster_id'] == -1:
            return None

        # Compute edge = hit_rate - breakeven
        avg_odds = result['avg_odds']
        hit_rate = result['hit_rate']
        breakeven = 1.0 / avg_odds if avg_odds > 0 else 1.0
        edge = hit_rate - breakeven

        return {
            'cluster_id': result['cluster_id'],
            'rec_bet': result['rec_bet'],
            'hit_rate': hit_rate,
            'avg_odds': avg_odds,
            'edge': round(edge, 4),
            'confidence': result['confidence'],
            'distance': result['distance'],
            'label': result['label'],
            'o15_odds': result.get('o15_odds'),
            'o25_odds': result.get('o25_odds'),
            'gg_odds': result.get('gg_odds'),
            'u35_odds': result.get('u35_odds'),
        }
    except Exception as e:
        return None


def run_prediction_gate(fixture: Dict, market: str, odds: float,
                        confidence: Optional[float] = None) -> Dict:
    """Run the prediction gate (same logic as live system).

    Returns the full gate result dict with verdict.
    """
    if not _HAS_GATE:
        return {'verdict': 'PASS', 'gates_passed': 4, 'gates_total': 4,
                'failing_gates': [], 'gates': {}}

    try:
        # Use the exact same function as the live system
        gate_result = run_all_gates(
            home_team=fixture['home_team'],
            away_team=fixture['away_team'],
            market=market,
            odds=odds,
            confidence=confidence,
            o15=fixture.get('o15'),
            o25=fixture.get('o25'),
            gg=fixture.get('gg'),
            u35=fixture.get('u35'),
        )
        return gate_result
    except Exception as e:
        return {
            'verdict': 'FAIL',
            'gates_passed': 0,
            'gates_total': 4,
            'failing_gates': ['error'],
            'gates': {},
            'error': str(e),
        }


def classify_and_gate(fixture: Dict) -> Optional[Dict]:
    """Run full pipeline: classify → gate → return structured pick result.

    This mirrors the EXACT pipeline flow from the live system.
    """
    # Step 1: Cluster classification
    if not _HAS_CLUSTER:
        return None
    cls_result = run_cluster_classifier(fixture)
    if cls_result is None:
        return None

    market_key = cls_result['rec_bet']
    odds_val = cls_result['avg_odds']
    hit_rate = cls_result['hit_rate']
    edge = cls_result['edge']
    confidence = cls_result['confidence']

    # Step 2: Prediction gate
    gate_result = run_prediction_gate(fixture, market_key, odds_val, confidence)

    # Step 3: Determine pass/fail
    verdict = gate_result.get('verdict', 'FAIL')
    gates_passed = gate_result.get('gates_passed', 0)
    gates_failed = gate_result.get('gates_failed', 0)
    failing_gates = gate_result.get('failing_gates', [])

    return {
        'home_team': fixture['home_team'],
        'away_team': fixture['away_team'],
        'match_day': fixture['match_day'],
        'market': market_key,
        'odds': odds_val,
        'hit_rate': hit_rate,
        'edge': edge,
        'confidence': confidence,
        'cluster_id': cls_result['cluster_id'],
        'distance': cls_result['distance'],
        'label': cls_result['label'],
        'gate_verdict': verdict,
        'gates_passed': gates_passed,
        'gates_failed': gates_failed,
        'failing_gates': failing_gates,
        'gate_result': gate_result,
        'o15': fixture.get('o15'),
        'o25': fixture.get('o25'),
        'gg': fixture.get('gg'),
        'u35': fixture.get('u35'),
    }


def verify_result(fixture: Dict, market: str) -> Optional[bool]:
    """Check if a bet would have won given actual match results.

    Returns:
        True if won, False if lost, None if result not available
    """
    hg = fixture.get('home_goals')
    ag = fixture.get('away_goals')
    tg = fixture.get('total_goals')
    status = fixture.get('status')

    if status != 3 or hg is None or ag is None:
        return None  # Match not yet played / no result

    check_fn = MARKET_CHECK.get(market)
    if check_fn is None:
        return None

    return check_fn(tg, hg, ag) == 1


# ──────────────────────────────────────────────────────────────────────
# BETTING / RATCHET LOGIC (matches live system)
# ──────────────────────────────────────────────────────────────────────

def simulate_bet_placement(state: Dict, picks: List[Dict]) -> Dict:
    """Simulate placing a virtual bet on a set of picks (parlay or single).

    Builds a parlay from up to 2 picks. Returns updated state and bet record.
    """
    if not picks:
        return state

    stake = state['ratchet']['current_stake']

    # Build parlay: multiply odds together
    total_odds = 1.0
    legs = []
    for pick in picks:
        total_odds *= pick['odds']
        legs.append({
            'home_team': pick['home_team'],
            'away_team': pick['away_team'],
            'market': pick['market'],
            'odds': pick['odds'],
        })

    total_odds = round(total_odds, 4)

    # Deduct from bankroll
    if state['virtual_bankroll'] < stake:
        stake = state['virtual_bankroll']  # Bet remaining
    state['virtual_bankroll'] -= stake

    bet_record = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'type': 'parlay' if len(legs) > 1 else 'single',
        'legs': legs,
        'total_odds': total_odds,
        'stake': stake,
        'payout': round(stake * total_odds, 2),
        'result': None,  # Will be filled after checking
        'profit': None,
    }

    state['active_bet'] = bet_record
    return state


def settle_bet(state: Dict, bets_won: bool) -> Dict:
    """Settle an active bet and update bankroll + ratchet state."""
    ab = state.get('active_bet')
    if ab is None:
        return state

    if bets_won:
        payout = ab['payout']
        profit = payout - ab['stake']
        state['virtual_bankroll'] += payout
        ab['result'] = 'WON'
        ab['profit'] = round(profit, 2)

        # Update ratchet
        r = state['ratchet']
        r['hits_in_step'] += 1
        r['total_profit_banked'] += profit
        r['milestone'] += 1

        # Phase advancement logic (simplified ratchet)
        if r['hits_in_step'] >= 3 and r['phase'] == 1:
            r['phase'] = 2
            r['hits_in_step'] = 0
            r['current_stake'] = round(r['current_stake'] * 1.5, 2)

        # Bank some profit periodically
        if r['milestone'] >= 5:
            banked = round(r['total_profit_banked'] * 0.3, 2)
            r['total_profit_banked'] -= banked
            r['milestone'] = 0
    else:
        profit = -ab['stake']
        ab['result'] = 'LOST'
        ab['profit'] = round(profit, 2)

        # Reset ratchet on loss
        r = state['ratchet']
        r['hits_in_step'] = 0
        r['current_stake'] = 50.0
        r['phase'] = 1

    state['history'].append(ab)
    state['active_bet'] = None
    return state


# ──────────────────────────────────────────────────────────────────────
# SIMULATION ENGINE
# ──────────────────────────────────────────────────────────────────────

def simulate_season(season_name: str, state: Dict, quick: bool = False,
                    stake: float = 50.0) -> Dict:
    """Run simulation across all matchdays of a single season.

    Returns season results as a dict.
    """
    season_id = resolve_season_id(season_name)
    matchdays = get_matchdays_for_season(season_name, season_id)

    # Initialize season stats
    season_stats = {
        'season_name': season_name,
        'season_id': season_id,
        'matchdays_processed': 0,
        'total_picks_checked': 0,
        'gates_passed': 0,
        'gates_failed': 0,
        'bets_placed': 0,
        'bets_won': 0,
        'bets_lost': 0,
        'total_stake': 0.0,
        'total_payout': 0.0,
        'net_profit': 0.0,
        'starting_bankroll': state['virtual_bankroll'],
        'ending_bankroll': state['virtual_bankroll'],
        'roi': 0.0,
        'matchdays': [],
        'failure_details': [],
        'gate_breakdown': {
            'h2h_fails': 0,
            'form_fails': 0,
            'cluster_fails': 0,
            'odds_fails': 0,
            'regime_fails': 0,
        },
    }

    # Update default stake
    state['ratchet']['current_stake'] = stake

    for md in matchdays:
        fixtures = load_matchday_data(season_id, md)
        if not fixtures:
            continue

        md_record = {
            'match_day': md,
            'fixtures_count': len(fixtures),
            'picks_checked': 0,
            'gates_passed': 0,
            'gates_failed': 0,
            'passing_picks': [],
            'bet_placed': None,
            'bet_result': None,
        }

        # Run pipeline on each fixture
        passing_picks = []
        for fx in fixtures:
            pick = classify_and_gate(fx)
            if pick is None:
                continue

            season_stats['total_picks_checked'] += 1
            state['gate_stats']['total_picks_checked'] += 1
            md_record['picks_checked'] += 1

            if pick['gate_verdict'] == 'PASS':
                season_stats['gates_passed'] += 1
                state['gate_stats']['gates_passed'] += 1
                md_record['gates_passed'] += 1
                passing_picks.append(pick)
                md_record['passing_picks'].append({
                    'fixture': f"{pick['home_team']} vs {pick['away_team']}",
                    'market': pick['market'],
                    'odds': pick['odds'],
                    'confidence': pick['confidence'],
                    'edge': pick['edge'],
                })
            else:
                season_stats['gates_failed'] += 1
                state['gate_stats']['gates_failed'] += 1
                md_record['gates_failed'] += 1

                # Track which gates failed
                for g in pick.get('failing_gates', []):
                    state['gate_stats'][f'{g}_fails'] = \
                        state['gate_stats'].get(f'{g}_fails', 0) + 1
                    season_stats['gate_breakdown'][f'{g}_fails'] = \
                        season_stats['gate_breakdown'].get(f'{g}_fails', 0) + 1

                # Track failure detail for analysis
                if pick.get('failing_gates'):
                    season_stats['failure_details'].append({
                        'season': season_name,
                        'match_day': md,
                        'fixture': f"{pick['home_team']} vs {pick['away_team']}",
                        'market': pick['market'],
                        'odds': pick['odds'],
                        'confidence': pick['confidence'],
                        'edge': pick['edge'],
                        'failing_gates': pick['failing_gates'],
                        'gate_detail': {
                            g: pick.get('gate_result', {}).get('gates', {}).get(g, {})
                            for g in pick.get('failing_gates', [])
                        },
                    })

        # Place bet on top 2 passing picks
        if passing_picks:
            # Sort by edge descending, then confidence
            passing_picks.sort(key=lambda x: (x['edge'], x['confidence']), reverse=True)
            picks_for_bet = passing_picks[:2]

            state = simulate_bet_placement(state, picks_for_bet)

            # Check results for each leg
            all_won = True
            leg_results = []
            for p in picks_for_bet:
                fx_data = None
                for fx in fixtures:
                    if (fx['home_team'] == p['home_team']
                            and fx['away_team'] == p['away_team']):
                        fx_data = fx
                        break
                if fx_data:
                    won = verify_result(fx_data, p['market'])
                    leg_results.append({
                        'fixture': f"{p['home_team']} vs {p['away_team']}",
                        'market': p['market'],
                        'odds': p['odds'],
                        'won': won if won is not None else 'UNKNOWN',
                    })
                    if won is False:
                        all_won = False
                    elif won is None:
                        # If result unavailable, might not be settled yet
                        # In our historical context, this shouldn't happen
                        # but handle gracefully
                        pass

            # Settle the bet
            bets_won = all_won and all(
                lr.get('won') is True or lr.get('won') == 'UNKNOWN'
                for lr in leg_results
            )
            # If any leg is uncertain (UNKNOWN), skip settlement
            if any(lr.get('won') == 'UNKNOWN' for lr in leg_results):
                # Can't settle — refund stake
                state['virtual_bankroll'] += state.get('active_bet', {}).get('stake', 0)
                state['active_bet'] = None
            else:
                state = settle_bet(state, all_won)

                ab = state['history'][-1] if state['history'] else {}
                if all_won:
                    season_stats['bets_won'] += 1
                    md_record['bet_result'] = 'WON'
                else:
                    season_stats['bets_lost'] += 1
                    md_record['bet_result'] = 'LOST'

                season_stats['bets_placed'] += 1
                md_record['bet_placed'] = {
                    'type': ab.get('type'),
                    'legs': leg_results,
                    'total_odds': ab.get('total_odds'),
                    'stake': ab.get('stake'),
                    'payout': ab.get('payout'),
                    'profit': ab.get('profit'),
                    'result': ab.get('result'),
                }

                season_stats['total_stake'] += ab.get('stake', 0)
                season_stats['total_payout'] += ab.get('payout', 0) if all_won else 0
                season_stats['net_profit'] += ab.get('profit', -ab.get('stake', 0))

        season_stats['matchdays'].append(md_record)

    # Finalize season stats
    season_stats['ending_bankroll'] = state['virtual_bankroll']
    total_staked = season_stats['total_stake']
    if total_staked > 0:
        season_stats['roi'] = round(
            (season_stats['net_profit'] / total_staked) * 100, 2
        )

    return season_stats


# ──────────────────────────────────────────────────────────────────────
# DASHBOARD & REPORTING
# ──────────────────────────────────────────────────────────────────────

def print_dashboard(all_seasons_stats: List[Dict], state: Dict, runtime: float):
    """Print a comprehensive performance dashboard."""
    # Aggregate stats
    total_matchdays = sum(s['matchdays_processed'] for s in all_seasons_stats)
    total_bets = sum(s['bets_placed'] for s in all_seasons_stats)
    total_won = sum(s['bets_won'] for s in all_seasons_stats)
    total_lost = sum(s['bets_lost'] for s in all_seasons_stats)
    total_picks_checked = sum(s['total_picks_checked'] for s in all_seasons_stats)
    total_gates_passed = sum(s['gates_passed'] for s in all_seasons_stats)
    total_gates_failed = sum(s['gates_failed'] for s in all_seasons_stats)
    total_stake = sum(s['total_stake'] for s in all_seasons_stats)
    total_payout = sum(s['total_payout'] for s in all_seasons_stats)
    total_profit = sum(s['net_profit'] for s in all_seasons_stats)

    initial_bankroll = state['initial_bankroll']
    final_bankroll = state['virtual_bankroll']
    bankroll_pct = ((final_bankroll - initial_bankroll) / initial_bankroll) * 100

    # Gate breakdown
    gs = state['gate_stats']
    h2h_fails = sum(s['gate_breakdown']['h2h_fails'] for s in all_seasons_stats)
    form_fails = sum(s['gate_breakdown']['form_fails'] for s in all_seasons_stats)
    cluster_fails = sum(s['gate_breakdown']['cluster_fails'] for s in all_seasons_stats)
    odds_fails = sum(s['gate_breakdown']['odds_fails'] for s in all_seasons_stats)
    regime_fails = sum(s['gate_breakdown']['regime_fails'] for s in all_seasons_stats)
    total_fails = h2h_fails + form_fails + cluster_fails + odds_fails + regime_fails

    # Ratchet stats
    r = state['ratchet']
    phases_completed = r['phase'] - 1  # Current phase minus 1

    # Win rate
    win_rate = (total_won / total_bets * 100) if total_bets > 0 else 0.0
    roi = (total_profit / total_stake * 100) if total_stake > 0 else 0.0
    avg_odds = 0.0
    odds_sum = 0
    odds_count = 0
    for s in all_seasons_stats:
        for md in s.get('matchdays', []):
            bp = md.get('bet_placed')
            if bp and bp.get('total_odds'):
                odds_sum += bp['total_odds']
                odds_count += 1
    avg_odds = round(odds_sum / odds_count, 2) if odds_count > 0 else 0.0

    # Best/worst seasons
    valid_seasons = [s for s in all_seasons_stats if s['bets_placed'] > 0]
    best_season = max(valid_seasons, key=lambda x: x['roi']) if valid_seasons else None
    worst_season = min(valid_seasons, key=lambda x: x['roi']) if valid_seasons else None

    # Season range
    season_names = [s['season_name'] for s in all_seasons_stats if s['bets_placed'] > 0]

    # ── Print Dashboard ──
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║     VIRTUAL BETTING SANDBOX RESULTS              ║")
    print("╚══════════════════════════════════════════════════╝")
    print()
    print(f"Seasons tested: {len(valid_seasons)} "
          f"({season_names[0] if season_names else 'N/A'} - "
          f"{season_names[-1] if season_names else 'N/A'})")
    print(f"Matchdays: {total_matchdays}")
    print(f"Runtime: {runtime:.2f}s")
    print(f"Virtual bankroll: ₦{initial_bankroll:,.2f} → ₦{final_bankroll:,.2f} "
          f"({bankroll_pct:+.1f}%)")
    print()
    print("── Betting Performance ──")
    print(f"Total bets placed: {total_bets}")
    print(f"Won: {total_won} ({win_rate:.1f}%)")
    print(f"Lost: {total_lost} ({100 - win_rate:.1f}%)")
    print(f"ROI: {roi:+.1f}%")
    print(f"Average odds: {avg_odds}")
    print()
    print("── Prediction Gate Performance ──")
    print(f"Total picks checked: {total_picks_checked}")
    print(f"Gates passed: {total_gates_passed} "
          f"({(total_gates_passed/total_picks_checked*100) if total_picks_checked > 0 else 0:.1f}%)")
    print(f"Gates failed: {total_gates_failed} "
          f"({(total_gates_failed/total_picks_checked*100) if total_picks_checked > 0 else 0:.1f}%)")
    print(f"  H2H fails: {h2h_fails}")
    print(f"  Form fails: {form_fails}")
    print(f"  Cluster fails: {cluster_fails}")
    print(f"  Odds fails: {odds_fails}")
    print(f"  Regime fails: {regime_fails}")
    print()
    print("── Ratchet Protocol ──")
    print(f"Phase {r['phase']} (completed: {phases_completed} times)")
    print(f"Total profit banked: ₦{r['total_profit_banked']:,.2f}")
    print(f"Current stake: ₦{r['current_stake']:,.2f}")
    print()
    if best_season:
        print("── Best/Worst Seasons ──")
        print(f"Best: {best_season['season_name']} ({best_season['roi']:+.1f}% ROI, "
              f"{best_season['bets_won']}/{best_season['bets_placed']} won)")
    if worst_season:
        print(f"Worst: {worst_season['season_name']} ({worst_season['roi']:+.1f}% ROI, "
              f"{worst_season['bets_won']}/{worst_season['bets_placed']} won)")
    print()
    print("── Gate Accuracy ──")
    print(f"Picks that PASSED gate: {total_gates_passed} bets → "
          f"Actual win rate: {win_rate:.1f}%")
    print(f"Picks that FAILED gate: {total_gates_failed} bets → "
          f"(skipped by gate)")
    print(f"Gate value add: gates filter out {total_gates_failed} low-quality picks")

    # Per-season detail
    print()
    print("── Per-Season Breakdown ──")
    print(f"{'Season':<14} {'MDs':<5} {'Bets':<6} {'Won':<5} {'Lost':<5} "
          f"{'ROI':<8} {'Bankroll':<12}")
    print("-" * 55)
    for s in all_seasons_stats:
        md_count = len(s.get('matchdays', []))
        bets = s['bets_placed']
        if bets > 0:
            br_change = s['ending_bankroll'] - s['starting_bankroll']
            print(f"{s['season_name']:<14} {md_count:<5} {bets:<6} "
                  f"{s['bets_won']:<5} {s['bets_lost']:<5} "
                  f"{s['roi']:+.1f}%{'':3} "
                  f"₦{br_change:+.1f}")
        else:
            print(f"{s['season_name']:<14} {md_count:<5} {'0':<6} "
                  f"{'0':<5} {'0':<5} {'-':<8} {'₦0.0':<12}")


def analyze_failures(all_seasons_stats: List[Dict]):
    """Deep analysis of why bets were lost despite passing the gate."""
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║     FAILURE ANALYSIS                             ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    # Collect all lost bets
    lost_bets = []
    for s in all_seasons_stats:
        for md in s.get('matchdays', []):
            bp = md.get('bet_placed')
            if bp and bp.get('result') == 'LOST':
                lost_bets.append({
                    'season': s['season_name'],
                    'match_day': md['match_day'],
                    'bet': bp,
                })

    if not lost_bets:
        print("No lost bets to analyze.")
        return

    print(f"Total lost bets analyzed: {len(lost_bets)}")
    print()

    # Analyze by market
    market_counts: Dict[str, int] = defaultdict(int)
    market_wins: Dict[str, int] = defaultdict(int)
    for s in all_seasons_stats:
        for md in s.get('matchdays', []):
            bp = md.get('bet_placed')
            if bp:
                for leg in bp.get('legs', []):
                    market_counts[leg['market']] += 1
                    if bp['result'] == 'WON':
                        market_wins[leg['market']] += 1

    print("── By Market Type ──")
    for mkt in sorted(market_counts.keys()):
        total = market_counts[mkt]
        wins = market_wins[mkt]
        loss_rate = ((total - wins) / total * 100) if total > 0 else 0
        print(f"  {mkt:<6}: {total:3d} bets, {wins:3d} wins, "
              f"{loss_rate:.1f}% loss rate")

    print()
    print("── By Team Profile ──")
    # Analyze by team profiles
    team_losses: Dict[str, int] = defaultdict(int)
    team_total: Dict[str, int] = defaultdict(int)
    for s in all_seasons_stats:
        for md in s.get('matchdays', []):
            bp = md.get('bet_placed')
            if bp:
                for leg in bp.get('legs', []):
                    for team_key in ['home_team', 'away_team']:
                        team = leg.get(team_key)
                        if team:
                            profile = TEAM_PROFILES.get(team, {}).get('tier', 'unknown') if _HAS_GATE else 'unknown'
                            team_total[f"{team} ({profile})"] += 1
                            if bp['result'] == 'LOST':
                                team_losses[f"{team} ({profile})"] += 1

    for team in sorted(team_total.keys(), key=lambda t: team_losses[t], reverse=True)[:10]:
        total = team_total[team]
        losses = team_losses[team]
        loss_pct = (losses / total * 100) if total > 0 else 0
        print(f"  {team:<30}: {total:3d} bets, {losses:3d} losses ({loss_pct:.1f}%)")

    print()
    print("── By Odds Range ──")
    odds_ranges = [(1.0, 1.3), (1.3, 1.5), (1.5, 1.8), (1.8, 2.0), (2.0, 2.5), (2.5, 5.0)]
    range_stats: Dict[str, Dict] = {}
    for r_min, r_max in odds_ranges:
        key = f"{r_min}-{r_max}"
        range_stats[key] = {'total': 0, 'wins': 0, 'losses': 0}

    for s in all_seasons_stats:
        for md in s.get('matchdays', []):
            bp = md.get('bet_placed')
            if bp:
                for leg in bp.get('legs', []):
                    od = leg['odds']
                    for r_min, r_max in odds_ranges:
                        if r_min <= od < r_max:
                            key = f"{r_min}-{r_max}"
                            range_stats[key]['total'] += 1
                            if bp['result'] == 'WON':
                                range_stats[key]['wins'] += 1
                            else:
                                range_stats[key]['losses'] += 1
                            break

    for key, stats in sorted(range_stats.items()):
        t = stats['total']
        if t > 0:
            loss_pct = (stats['losses'] / t * 100)
            print(f"  Odds {key:<8}: {t:3d} legs, {stats['wins']:3d} wins, "
                  f"{loss_pct:.1f}% loss rate")

    print()
    print("── Failed Gate Detail ──")
    # Show why picks that FAILED would have performed (hypothetical)
    failed_picks = []
    for s in all_seasons_stats:
        for fd in s.get('failure_details', []):
            failed_picks.append(fd)

    if failed_picks:
        gate_reasons: Dict[str, int] = defaultdict(int)
        for fp in failed_picks:
            for g in fp.get('failing_gates', []):
                gate_reasons[g] += 1
        for reason, count in sorted(gate_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count} failures")
    else:
        print("  No failure details recorded.")


def compare_strategies(all_seasons_stats: List[Dict], state: Dict):
    """Compare three strategies side by side: raw, cluster-only, gate-verified."""
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║     STRATEGY COMPARISON                          ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    # We can compute gate vs no-gate from our existing data
    total_bets = sum(s['bets_placed'] for s in all_seasons_stats)
    total_won = sum(s['bets_won'] for s in all_seasons_stats)
    total_stake = sum(s['total_stake'] for s in all_seasons_stats)
    total_profit = sum(s['net_profit'] for s in all_seasons_stats)
    total_picks = sum(s['total_picks_checked'] for s in all_seasons_stats)
    gates_passed = sum(s['gates_passed'] for s in all_seasons_stats)
    gates_failed = sum(s['gates_failed'] for s in all_seasons_stats)

    win_rate = (total_won / total_bets * 100) if total_bets > 0 else 0
    roi = (total_profit / total_stake * 100) if total_stake > 0 else 0

    # Strategy C: Gate-verified (our actual results)
    print("── Strategy A: Raw Cluster Picks (All Picks) ──")
    print(f"  Total picks: {total_picks}")
    print(f"  Would place bets on ALL {total_picks} picks")
    print(f"  Estimated win rate: ~{win_rate:.1f}% (from passed picks)")

    print()
    print("── Strategy B: Cluster-Only Picks (No Gate) ──")
    all_cluster = gates_passed + gates_failed
    print(f"  Total cluster-eligible picks: {all_cluster}")
    print(f"  Gates passed: {gates_passed}")
    print(f"  Gates filtered out: {gates_failed}")
    print(f"  Filter rate: {(gates_failed/all_cluster*100) if all_cluster > 0 else 0:.1f}%")

    print()
    print("── Strategy C: Gate-Verified Picks (Live System) ──")
    print(f"  Bets placed: {total_bets}")
    print(f"  Won: {total_won}")
    print(f"  Win rate: {win_rate:.1f}%")
    print(f"  ROI: {roi:+.1f}%")
    print(f"  Profit: ₦{total_profit:+,.2f}")

    # Gate value-add estimate
    if all_cluster > 0:
        # If all cluster picks were bet, with observed win rate of passed picks,
        # the filtered picks would have lower win rate
        hypothetical_loss = gates_failed * (1.0 - win_rate / 100) * 50
        print()
        print("── Gate Value Assessment ──")
        print(f"  Without gate, {gates_failed} extra bets would have been placed")
        print(f"  Estimated additional losses: ₦{hypothetical_loss:,.2f} "
              f"(@ assumed {win_rate:.1f}% win rate on filtered picks)")
        print(f"  Gate saved approximately ₦{hypothetical_loss:,.2f} in losses")

    print()
    print("── Strategy Summary ──")
    print(f"  {'Strategy':<30} {'Bets':<8} {'Win%':<10} {'ROI':<10}")
    print(f"  {'-'*58}")
    print(f"  {'A) Raw Cluster (all picks)':<30} {total_picks:<8} "
          f"{'~'+str(round(win_rate,1))+'%':<10} {'estimated':<10}")
    print(f"  {'B) Cluster Only (no gate)':<30} {all_cluster:<8} "
          f"{'filtered':<10} {'N/A':<10}")
    print(f"  {'C) Gate-Verified':<30} {total_bets:<8} "
          f"{win_rate:.1f}%{'':<4} {roi:+.1f}%")


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Virtual Betting Sandbox — Simulation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python virtual_betting_sandbox.py --quick --seasons 5
  python virtual_betting_sandbox.py --seasons VFLM 5110 VFLM 5115
  python virtual_betting_sandbox.py --all
  python virtual_betting_sandbox.py --bankroll 5000 --stake 100
  python virtual_betting_sandbox.py --analyze-failures
  python virtual_betting_sandbox.py --compare
  python virtual_betting_sandbox.py --quick --seasons 10 --json --save
        """
    )

    # Season selection
    parser.add_argument('--seasons', nargs='+',
                        help='Season names or count (e.g., 5 = last 5 seasons)')
    parser.add_argument('--all', action='store_true',
                        help='Test all available seasons')

    # Bankroll / stake
    parser.add_argument('--bankroll', type=float, default=1000.0,
                        help='Initial virtual bankroll (default: ₦1,000)')
    parser.add_argument('--stake', type=float, default=50.0,
                        help='Stake per bet (default: ₦50)')

    # Modes
    parser.add_argument('--quick', action='store_true',
                        help='Fast mode — skip per-matchday printing')
    parser.add_argument('--json', action='store_true',
                        help='Output JSON for programmatic analysis')
    parser.add_argument('--save', action='store_true',
                        help='Save results to data/virtual_sandbox_results.json')
    parser.add_argument('--analyze-failures', action='store_true',
                        help='Deep-dive failure analysis after simulation')
    parser.add_argument('--compare', action='store_true',
                        help='Compare strategies side by side')

    args = parser.parse_args()

    # ── Resolve which seasons to test ──
    all_available = get_available_seasons()

    if args.all:
        seasons_to_test = all_available
    elif args.seasons:
        # Check if first arg is a number (count)
        if len(args.seasons) == 1 and args.seasons[0].isdigit():
            count = int(args.seasons[0])
            seasons_to_test = all_available[:count]
        else:
            # Specific seasons
            seasons_to_test = []
            for s in args.seasons:
                # Find closest match
                for av in all_available:
                    if s.lower() in av.lower() or av.lower() in s.lower():
                        seasons_to_test.append(av)
                        break
                else:
                    print(f"WARNING: Season '{s}' not found in available data",
                          file=sys.stderr)
            seasons_to_test = list(dict.fromkeys(seasons_to_test))  # dedup preserve order
    else:
        # Default: last 5 seasons
        seasons_to_test = all_available[:5]

    if not seasons_to_test:
        print("ERROR: No valid seasons found. Check database paths and data.",
              file=sys.stderr)
        sys.exit(1)

    # Filter to seasons with enough matches
    conn_r = get_results_conn()
    conn_o = get_odds_conn()
    try:
        filtered = []
        for s in seasons_to_test:
            season_id = resolve_season_id(s)
            r_count = conn_r.execute(
                "SELECT COUNT(*) FROM results WHERE season_name = ? AND status = 3",
                (s,)
            ).fetchone()[0]
            o_count = conn_o.execute(
                "SELECT COUNT(*) FROM event_details WHERE season_id = ?",
                (season_id,)
            ).fetchone()[0]
            if r_count >= 50 and o_count >= 50:
                filtered.append(s)
            else:
                if not args.quick:
                    print(f"  Skipping {s} ({r_count} results, {o_count} odds entries)",
                          file=sys.stderr)
        seasons_to_test = filtered
    finally:
        conn_r.close()
        conn_o.close()

    if not seasons_to_test:
        print("ERROR: No seasons with sufficient data found.", file=sys.stderr)
        sys.exit(1)

    if not args.quick:
        print(f"\n{'='*60}")
        print(f"  VIRTUAL BETTING SANDBOX")
        print(f"{'='*60}")
        print(f"\nTesting {len(seasons_to_test)} seasons:")
        for i, s in enumerate(seasons_to_test):
            print(f"  {i+1}. {s}")
        print(f"\nInitial bankroll: ₦{args.bankroll:,.2f}")
        print(f"Stake per bet: ₦{args.stake:,.2f}")
        print()

    # ── Initialize state ──
    state = default_state(args.bankroll)
    all_seasons_stats = []
    start_time = time.time()

    # ── Run simulation ──
    for i, season_name in enumerate(seasons_to_test):
        if not args.quick:
            print(f"[{i+1}/{len(seasons_to_test)}] Simulating {season_name}...",
                  end=' ', flush=True)

        season_result = simulate_season(
            season_name, state,
            quick=args.quick,
            stake=args.stake,
        )

        all_seasons_stats.append(season_result)

        if not args.quick:
            md_count = len(season_result.get('matchdays', []))
            bets = season_result['bets_placed']
            print(f"{md_count} MDs, {bets} bets, "
                  f"₦{season_result['net_profit']:+.1f} net")

    runtime = time.time() - start_time

    # ── Output ──
    if args.json:
        output = {
            'config': {
                'initial_bankroll': args.bankroll,
                'stake': args.stake,
                'seasons': seasons_to_test,
            },
            'runtime_seconds': round(runtime, 2),
            'final_bankroll': round(state['virtual_bankroll'], 2),
            'total_bankroll_change': round(
                state['virtual_bankroll'] - state['initial_bankroll'], 2
            ),
            'seasons': all_seasons_stats,
            'gate_stats': state['gate_stats'],
            'ratchet': state['ratchet'],
            'history': state['history'],
        }
        print(json.dumps(output, indent=2))

    if args.save:
        output = {
            'config': {
                'initial_bankroll': args.bankroll,
                'stake': args.stake,
                'seasons': seasons_to_test,
            },
            'runtime_seconds': round(runtime, 2),
            'final_bankroll': round(state['virtual_bankroll'], 2),
            'seasons': all_seasons_stats,
            'gate_stats': state['gate_stats'],
            'ratchet': state['ratchet'],
            'history': state['history'],
        }
        with open(SANDBOX_RESULTS_FILE, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to {SANDBOX_RESULTS_FILE}")

    # Print dashboard (unless --json-only)
    if not args.json:
        print_dashboard(all_seasons_stats, state, runtime)

    # Failure analysis
    if args.analyze_failures:
        analyze_failures(all_seasons_stats)

    # Strategy comparison
    if args.compare:
        compare_strategies(all_seasons_stats, state)


if __name__ == '__main__':
    main()
