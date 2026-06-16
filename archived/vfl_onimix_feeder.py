#!/usr/bin/env python3
"""
vfl_onimix_feeder.py — Onimix VFL Engine Integration Feeder
==========================================================
Runs the Onimix engine, enriches live_test_predictions.json with
Onimix signals (Section A score, multi-market edges, verdicts).

Designed to be run from cron via vfl_onimix_cron.sh.
Prints a Discord-friendly summary to stdout.

Usage:
    python3 vfl_onimix_feeder.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# Ensure the scripts directory is on the path so we can import the engine
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from vfl_onimix_engine import (
    sec_a,
    multi_market_edge_analysis,
    fetch_event_list,
    fetch_event_detail,
    discover_all,
    _load_state,
    analyze,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PREDICTIONS_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/signals/live_test_predictions.json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('vfl_onimix_feeder')

# Suppress noisy engine loggers
for logname in ('vfl_onimix_engine', 'vfl_onimix_feeder'):
    logging.getLogger(logname).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Normalize a team name for fuzzy matching."""
    return (
        name.strip()
        .lower()
        .replace(' ', '')
        .replace('-', '')
        .replace("'", '')
        .replace('.', '')
    )


def _strip_prefix(eid: str) -> str:
    """Strip the 'vf:match:' prefix from a fixture event_id."""
    return eid.replace('vf:match:', '').strip()


def _match_event(
    fixture: Dict[str, Any],
    msport_events_by_cat: Dict[str, List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Match a prediction fixture to an MSport event by event_id or team names."""
    fixture_eid = _strip_prefix(fixture.get('event_id', ''))
    home_raw = fixture.get('home', '')
    away_raw = fixture.get('away', '')
    home_norm = _normalize_name(home_raw)
    away_norm = _normalize_name(away_raw)

    for _cat, events in msport_events_by_cat.items():
        for ev in events:
            ev_id = str(ev.get('eventId', ''))

            # Direct event_id match
            if fixture_eid and ev_id == fixture_eid:
                return ev

            ev_home = _normalize_name(ev.get('homeTeam', ''))
            ev_away = _normalize_name(ev.get('awayTeam', ''))

            # Exact team-name match
            if home_norm == ev_home and away_norm == ev_away:
                return ev

            # Reversed (occasionally MSport swaps home/away)
            if home_norm == ev_away and away_norm == ev_home:
                return ev

            # Partial — check if both names appear somewhere in the event
            if (home_norm and away_norm
                    and home_norm in ev_home and away_norm in ev_away):
                return ev
            if (home_norm and away_norm
                    and home_norm in ev_away and away_norm in ev_home):
                return ev

    return None


def _build_onimix_section(
    event: Dict[str, Any],
    blacklist: Dict[str, Any],
    results_history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the onimix enrichment dict for a single matched MSport event."""
    section: Dict[str, Any] = {}

    # ── Section A (always available) ──────────────────────────────────
    try:
        sa = sec_a(event)
        section['section_a'] = {
            'sc': sa.get('sc', 0),
            'mx': sa.get('mx', 0),
            'pct': sa.get('pct', 0),
            'ou15_odds': sa.get('ou15_odds', 0.0),
            'ou15_oid': sa.get('ou15_oid', ''),
            'sweet': sa.get('sweet', False),
            'fp11': sa.get('fp11', False),
            'conf': sa.get('conf', 'LOW'),
        }
    except Exception as exc:
        logger.warning('sec_a() failed for %s: %s',
                       event.get('eventId', '?'), exc)
        section['section_a'] = None

    # ── Multi-market edges ───────────────────────────────────────────
    try:
        edge_data = multi_market_edge_analysis(event)
        section['edges'] = edge_data.get('edges', {})
        section['fair_odds'] = edge_data.get('fair', {})
        if edge_data.get('available'):
            section['market_odds'] = edge_data.get('market_odds', {})
    except Exception as exc:
        logger.warning('multi_market_edge_analysis() failed for %s: %s',
                       event.get('eventId', '?'), exc)
        section['edges'] = {}
        section['fair_odds'] = {}

    # ── Full analyze (Section A + B + verdict) ───────────────────────
    try:
        analysis = analyze(event, blacklist, results_history)
        section['verdict'] = analysis.get('verdict', 'SKIP')
        section['combined_score'] = analysis.get('combined', 0)
        section['max_score'] = analysis.get('cmax', 0)
        section['confidence_pct'] = analysis.get('cpct', 0)
        section['has_section_b'] = analysis.get('has_b', False)

        if analysis.get('b'):
            section['section_b'] = {
                'sc': analysis['b'].get('sc', 0),
                'conf': analysis['b'].get('conf', 'N/A'),
                'reasons': analysis['b'].get('reasons', []),
            }
        else:
            section['section_b'] = None
    except Exception as exc:
        logger.warning('analyze() failed for %s: %s',
                       event.get('eventId', '?'), exc)
        # Fallback: verdict from Section A alone
        sa_fallback = section.get('section_a')
        if sa_fallback is not None:
            pct = sa_fallback['pct']
            if pct >= 75:
                section['verdict'] = 'LOCK'
            elif pct >= 55:
                section['verdict'] = 'PICK'
            elif pct >= 40:
                section['verdict'] = 'CONSIDER'
            else:
                section['verdict'] = 'SKIP'
            section['combined_score'] = sa_fallback['sc']
            section['max_score'] = sa_fallback['mx']
            section['confidence_pct'] = pct
        else:
            section['verdict'] = 'SKIP'
            section['confidence_pct'] = 0
        section['has_section_b'] = False
        section['section_b'] = None

    return section


def _build_matchday_summary(fixtures: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate onimix data across all fixtures in a matchday."""
    locks = picks = considers = skips = 0
    top: List[Dict[str, Any]] = []

    for fix in fixtures:
        onimix = fix.get('prediction', {}).get('onimix', {})
        verdict = onimix.get('verdict', '')
        if not verdict:
            continue

        if verdict == 'LOCK':
            locks += 1
        elif verdict == 'PICK':
            picks += 1
        elif verdict == 'CONSIDER':
            considers += 1
        elif verdict == 'SKIP':
            skips += 1

        sa = onimix.get('section_a')
        if sa and verdict in ('LOCK', 'PICK', 'CONSIDER'):
            top.append({
                'match': f"{fix.get('home', '?')} vs {fix.get('away', '?')}",
                'verdict': verdict,
                'sa_score': f"{sa.get('sc', 0)}/{sa.get('mx', 13)}",
                'confidence_pct': onimix.get('confidence_pct', 0),
            })

    _vr = {'LOCK': 0, 'PICK': 1, 'CONSIDER': 2}
    top.sort(key=lambda x: (_vr.get(x['verdict'], 99), -x['confidence_pct']))

    return {
        'active_fixtures': locks + picks + considers,
        'locks': locks,
        'picks': picks,
        'considers': considers,
        'skips': skips,
        'top_fixtures': top[:5],
    }


def _print_summary(data: Dict[str, Any]) -> None:
    """Print a Discord-friendly summary line to stdout."""
    matchdays = data.get('matchdays', [])
    current = data.get('current_matchday', {})
    season = current.get('season', 'VFLM ?')
    md_num = current.get('matchday', '?')

    total_locks = total_picks = total_considers = total_skips = 0
    all_top: List[Dict[str, Any]] = []

    for md in matchdays:
        sm = md.get('onmixin_summary', {})
        if not sm:
            continue
        # Use first matchday's metadata if current_matchday is empty
        if season == 'VFLM ?':
            season = md.get('season_name', season)
        if md_num == '?':
            md_num = md.get('matchday', md_num)
        total_locks += sm.get('locks', 0)
        total_picks += sm.get('picks', 0)
        total_considers += sm.get('considers', 0)
        total_skips += sm.get('skips', 0)
        all_top.extend(sm.get('top_fixtures', []))

    _vr = {'LOCK': 0, 'PICK': 1, 'CONSIDER': 2}
    all_top.sort(key=lambda x: (_vr.get(x['verdict'], 99), -x.get('confidence_pct', 0)))

    total_active = total_locks + total_picks + total_considers

    print(f'🔥 Onimix VFL Engine Scan')
    print(f'Season: {season} MD{md_num}')
    print(f'LOCK: {total_locks} | PICK: {total_picks} | '
          f'CONSIDER: {total_considers} | SKIP: {total_skips}')

    if all_top:
        t = all_top[0]
        print(f'Top: {t["match"]} ({t["verdict"]}, SA {t["sa_score"]})')
        for entry in all_top[1:3]:
            print(f'  • {entry["match"]} → {entry["verdict"]} '
                  f'(SA {entry["sa_score"]}, {entry["confidence_pct"]}%)')

    print('--- Onimix Feeder Complete ---')


def _create_skeleton() -> Dict[str, Any]:
    """Return a minimal skeleton data structure when no predictions exist."""
    return {
        'matchdays': [],
        'current_matchday': {},
        'regime': 'STANDARD',
    }


def _create_from_msport_events(
    msport_events: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    Create a full live_test_predictions.json from scratch using MSport events.
    Used when the file does not exist yet.
    """
    matchdays: List[Dict[str, Any]] = []
    season_name = 'VFLM ?'
    season_id = ''
    matchday = 1

    # Collect all events to determine season info
    all_events: List[Dict[str, Any]] = []
    for cat, events in msport_events.items():
        all_events.extend(events)

    if not all_events:
        return _create_skeleton()

    # Attempt to extract season / matchday from first event's tournament info
    first = all_events[0]
    tournament = first.get('tournament', {}) or {}
    season_name = tournament.get('name', 'VFLM ?') if isinstance(tournament, dict) else 'VFLM ?'
    season_id = tournament.get('id', '') if isinstance(tournament, dict) else ''

    # Build fixture list from events that have markets
    fixtures: List[Dict[str, Any]] = []
    for ev in all_events:
        if not ev.get('homeTeam') or not ev.get('awayTeam'):
            continue
        ev_id = str(ev.get('eventId', ''))
        fixture: Dict[str, Any] = {
            'home': ev.get('homeTeam', '?'),
            'away': ev.get('awayTeam', '?'),
            'event_id': f'vf:match:{ev_id}' if ev_id else '',
            'prediction': {
                'primary': {
                    'market': 'Over 1.5 Goals',
                    'odds': 1.0,
                    'confidence_pct': 0,
                    'strength': 'PENDING',
                },
            },
        }

        # Try to extract starting odds from event markets for a reasonable primary
        markets = ev.get('markets', [])
        for m in markets:
            if m.get('id') == 18:
                for o in m.get('outcomes', []):
                    desc = o.get('description', o.get('desc', ''))
                    od = float(o.get('odds', 0))
                    if desc.startswith('Over 1.5') and od > 0:
                        fixture['prediction']['primary']['odds'] = od
                        if od <= 1.60:
                            fixture['prediction']['primary']['strength'] = 'STRONG'
                            fixture['prediction']['primary']['confidence_pct'] = 85
                        elif od <= 1.80:
                            fixture['prediction']['primary']['strength'] = 'MODERATE'
                            fixture['prediction']['primary']['confidence_pct'] = 60
                        break

        # Also store raw odds for downstream
        fixture['odds'] = {}
        for m in markets:
            if m.get('id') == 18:
                for o in m.get('outcomes', []):
                    desc = o.get('description', o.get('desc', ''))
                    od = float(o.get('odds', 0))
                    if desc.startswith('Over 1.5'):
                        fixture['odds']['over_1.5'] = od
                    elif desc.startswith('Over 2.5'):
                        fixture['odds']['over_2.5'] = od
            elif m.get('id') == 29:
                for o in m.get('outcomes', []):
                    desc = o.get('description', o.get('desc', ''))
                    od = float(o.get('odds', 0))
                    if desc == 'Yes':
                        fixture['odds']['gg'] = od

        fixtures.append(fixture)

    matchdays.append({
        'season_name': season_name,
        'season_id': season_id,
        'matchday': matchday,
        'fixtures': fixtures,
    })

    return {
        'matchdays': matchdays,
        'current_matchday': {
            'season': season_name,
            'matchday': matchday,
        },
        'regime': 'STANDARD',
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    logger.info('Onimix Feeder starting')

    # ── Step 1: Discover MSport events ────────────────────────────────
    logger.info('Discovering MSport events via Onimix engine...')
    msport_events = discover_all()
    total_msport = sum(len(v) for v in msport_events.values())
    logger.info('Discovered %d events across %d categories',
                total_msport, len(msport_events))

    if total_msport == 0:
        logger.warning('No MSport events found. Skipping enrichment.')
        print('⚠️ Onimix Feeder: No MSport events discovered')
        print('--- Onimix Feeder Complete ---')
        return 1

    # ── Step 2: Load state for blacklist & results history ────────────
    state = _load_state()
    blacklist = state.get('blacklist', {})
    results_history = state.get('results', [])
    logger.info('Loaded state: %d blacklist entries, %d results',
                len(blacklist), len(results_history))

    # ── Step 3: Load or create predictions ────────────────────────────
    if os.path.exists(PREDICTIONS_PATH):
        try:
            with open(PREDICTIONS_PATH, 'r') as f:
                data = json.load(f)
            logger.info('Loaded existing predictions from %s', PREDICTIONS_PATH)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning('Failed to load %s: %s. Creating from scratch.',
                           PREDICTIONS_PATH, exc)
            data = _create_from_msport_events(msport_events)
    else:
        logger.info('No existing predictions file found. Creating from MSport events.')
        data = _create_from_msport_events(msport_events)

    # ── Step 4: Enrich each fixture ───────────────────────────────────
    enriched_count = 0
    matched_count = 0
    total_fixtures = 0

    for md in data.get('matchdays', []):
        fixtures = md.get('fixtures', [])
        total_fixtures += len(fixtures)
        for fix in fixtures:
            event = _match_event(fix, msport_events)
            if event is not None:
                matched_count += 1
                onimix = _build_onimix_section(event, blacklist, results_history)
                if 'prediction' not in fix:
                    fix['prediction'] = {}
                fix['prediction']['onimix'] = onimix
                enriched_count += 1
                logger.debug('Enriched: %s vs %s → %s (%.0f%%)',
                             fix.get('home', '?'), fix.get('away', '?'),
                             onimix.get('verdict', '?'),
                             onimix.get('confidence_pct', 0))

        # Build matchday-level summary
        md['onmixin_summary'] = _build_matchday_summary(fixtures)

    # If we had no existing fixtures but got MSport events, run enrichment
    # on any newly created fixtures that haven't been processed yet
    if total_fixtures == 0 and matched_count == 0:
        for md in data.get('matchdays', []):
            for fix in md.get('fixtures', []):
                if 'onimix' not in fix.get('prediction', {}):
                    event = _match_event(fix, msport_events)
                    if event is not None:
                        matched_count += 1
                        onimix = _build_onimix_section(event, blacklist, results_history)
                        if 'prediction' not in fix:
                            fix['prediction'] = {}
                        fix['prediction']['onimix'] = onimix
                        enriched_count += 1
            md['onmixin_summary'] = _build_matchday_summary(md.get('fixtures', []))

    logger.info('Matched %d / %d fixtures, enriched %d',
                matched_count, total_fixtures, enriched_count)

    # ── Step 5: Write back ────────────────────────────────────────────
    os.makedirs(os.path.dirname(PREDICTIONS_PATH), exist_ok=True)
    with open(PREDICTIONS_PATH, 'w') as f:
        json.dump(data, f, indent=2)
    logger.info('Written enriched predictions to %s', PREDICTIONS_PATH)

    # ── Step 6: Print summary to stdout (→ Discord) ──────────────────
    _print_summary(data)

    return 0


if __name__ == '__main__':
    sys.exit(main())
