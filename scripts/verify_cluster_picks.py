#!/usr/bin/env python3
"""
Post-Matchday Verification Script
==================================
Checks pipeline picks against actual results, updates cluster statistics,
and outputs verification reports.

Loads picks from:
  1. --season <N> --matchday <M> → signals/pipeline_picks_md<M>.json
  2. --picks-file <path>
  3. --latest (most recent pipeline_picks_md*.json)

Market resolution covers all variant naming conventions used across
the VFL pipeline and orchestrator.

Usage:
    python verify_cluster_picks.py --season 5113 --matchday 5
    python verify_cluster_picks.py --picks-file /tmp/picks.json
    python verify_cluster_picks.py --latest
    python verify_cluster_picks.py --season 5113 --matchday 5 --update-clusters
    python verify_cluster_picks.py --season 5113 --matchday 5 --cron

Output formats:
  - Human-readable (default):   Verification report with unicode borders
  - Cron/JSON (--cron):         JSON only to stdout, logs to stderr

Author: VFL Engineering Team
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data'
VFL_EMPIRE_DIR = '/home/ubuntu/faith-workspace/vfl-empire'
SCRIPTS_DIR = os.path.join(VFL_EMPIRE_DIR, 'scripts')
SIGNALS_DIR = os.path.join(BASE_DIR, 'signals')
LIVE_PREDICTIONS_PATH = os.path.join(SIGNALS_DIR, 'predictions_latest.json')
RESULTS_DB_PATH = os.path.join(BASE_DIR, 'databases', 'vfl_results.db')
ODDS_DB_PATH = os.path.join(BASE_DIR, 'databases', 'vfl_odds.db')
CLUSTER_RECOMMENDATIONS_PATH = os.path.join(SCRIPTS_DIR, 'odds_cluster_classifier.py')

# Verification state file
VERIFICATION_STATE_DIR = os.path.join(VFL_EMPIRE_DIR, 'data')
VERIFICATION_STATE_PATH = os.path.join(VERIFICATION_STATE_DIR, 'cluster_verification.json')

# Default stake per pick for ROI calculation
DEFAULT_STAKE = 1.0  # 1 unit per pick

# ──────────────────────────────────────────────────────────────────────
# MARKET RESOLUTION
# ──────────────────────────────────────────────────────────────────────

def resolve_market(market_str: str) -> Optional[Dict[str, Any]]:
    """Resolve a market string to a canonical market code and win-check function.

    Returns dict with {'market': canonical_code, 'check': callable(total_goals, home_goals, away_goals) -> bool}
    or None if unrecognised.
    """
    normalized = market_str.strip().lower()

    market_defs = {
        # GG / BTTS
        'gg': {
            'market': 'GG',
            'check': lambda tg, hg, ag: hg > 0 and ag > 0,
        },
        'btts yes': {
            'market': 'GG',
            'check': lambda tg, hg, ag: hg > 0 and ag > 0,
        },
        'btts': {
            'market': 'GG',
            'check': lambda tg, hg, ag: hg > 0 and ag > 0,
        },
        'both teams to score': {
            'market': 'GG',
            'check': lambda tg, hg, ag: hg > 0 and ag > 0,
        },
        'goal-goal': {
            'market': 'GG',
            'check': lambda tg, hg, ag: hg > 0 and ag > 0,
        },
        'goal goal': {
            'market': 'GG',
            'check': lambda tg, hg, ag: hg > 0 and ag > 0,
        },

        # NG / BTTS No
        'ng': {
            'market': 'NG',
            'check': lambda tg, hg, ag: hg == 0 or ag == 0,
        },
        'btts no': {
            'market': 'NG',
            'check': lambda tg, hg, ag: hg == 0 or ag == 0,
        },
        'no goal': {
            'market': 'NG',
            'check': lambda tg, hg, ag: hg == 0 or ag == 0,
        },

        # Over / Under goals
        'o1.5': {
            'market': 'O1.5',
            'check': lambda tg, hg, ag: (tg or 0) > 1,
        },
        'over 1.5 goals': {
            'market': 'O1.5',
            'check': lambda tg, hg, ag: (tg or 0) > 1,
        },
        'over 1.5': {
            'market': 'O1.5',
            'check': lambda tg, hg, ag: (tg or 0) > 1,
        },

        'o2.5': {
            'market': 'O2.5',
            'check': lambda tg, hg, ag: (tg or 0) > 2,
        },
        'over 2.5 goals': {
            'market': 'O2.5',
            'check': lambda tg, hg, ag: (tg or 0) > 2,
        },
        'over 2.5': {
            'market': 'O2.5',
            'check': lambda tg, hg, ag: (tg or 0) > 2,
        },

        'u1.5': {
            'market': 'U1.5',
            'check': lambda tg, hg, ag: (tg or 0) < 2,
        },
        'under 1.5 goals': {
            'market': 'U1.5',
            'check': lambda tg, hg, ag: (tg or 0) < 2,
        },
        'under 1.5': {
            'market': 'U1.5',
            'check': lambda tg, hg, ag: (tg or 0) < 2,
        },

        'u2.5': {
            'market': 'U2.5',
            'check': lambda tg, hg, ag: (tg or 0) < 3,
        },
        'under 2.5 goals': {
            'market': 'U2.5',
            'check': lambda tg, hg, ag: (tg or 0) < 3,
        },
        'under 2.5': {
            'market': 'U2.5',
            'check': lambda tg, hg, ag: (tg or 0) < 3,
        },

        'u3.5': {
            'market': 'U3.5',
            'check': lambda tg, hg, ag: (tg or 0) < 4,
        },
        'under 3.5 goals': {
            'market': 'U3.5',
            'check': lambda tg, hg, ag: (tg or 0) < 4,
        },
        'under 3.5': {
            'market': 'U3.5',
            'check': lambda tg, hg, ag: (tg or 0) < 4,
        },

        # Double Chance / Result markets
        'dc 1x': {
            'market': 'DC 1X',
            'check': lambda tg, hg, ag: hg >= ag,
        },
        'double chance home/draw': {
            'market': 'DC 1X',
            'check': lambda tg, hg, ag: hg >= ag,
        },
        '1x': {
            'market': 'DC 1X',
            'check': lambda tg, hg, ag: hg >= ag,
        },

        'home win': {
            'market': 'Home Win',
            'check': lambda tg, hg, ag: hg > ag,
        },
        '1': {
            'market': 'Home Win',
            'check': lambda tg, hg, ag: hg > ag,
        },

        'away win': {
            'market': 'Away Win',
            'check': lambda tg, hg, ag: hg < ag,
        },
        '2': {
            'market': 'Away Win',
            'check': lambda tg, hg, ag: hg < ag,
        },

        'dnb home': {
            'market': 'DNB Home',
            'check': lambda tg, hg, ag: True if hg > ag else (False if hg < ag else None),
        },
        'draw no bet home': {
            'market': 'DNB Home',
            'check': lambda tg, hg, ag: True if hg > ag else (False if hg < ag else None),
        },
        'dnb 1': {
            'market': 'DNB Home',
            'check': lambda tg, hg, ag: True if hg > ag else (False if hg < ag else None),
        },

        'dnb away': {
            'market': 'DNB Away',
            'check': lambda tg, hg, ag: True if hg < ag else (False if hg > ag else None),
        },
        'draw no bet away': {
            'market': 'DNB Away',
            'check': lambda tg, hg, ag: True if hg < ag else (False if hg > ag else None),
        },
        'dnb 2': {
            'market': 'DNB Away',
            'check': lambda tg, hg, ag: True if hg < ag else (False if hg > ag else None),
        },

        'draw': {
            'market': 'Draw',
            'check': lambda tg, hg, ag: hg == ag,
        },
        'x': {
            'market': 'Draw',
            'check': lambda tg, hg, ag: hg == ag,
        },
    }

    return market_defs.get(normalized)


# ──────────────────────────────────────────────────────────────────────
# PICK LOADING
# ──────────────────────────────────────────────────────────────────────


def load_live_predictions() -> Optional[Dict]:
    """Load predictions from predictions_latest.json."""
    if not os.path.isfile(LIVE_PREDICTIONS_PATH):
        print(f"ERROR: Live predictions file not found: {LIVE_PREDICTIONS_PATH}", file=sys.stderr)
        return None
    with open(LIVE_PREDICTIONS_PATH, 'r') as f:
        data = json.load(f)
    return data


def load_picks_from_file(picks_path: str) -> List[Dict]:
    """Load picks from an arbitrary JSON file.

    Supports:
      - Direct list of pick dicts
      - Dict with 'picks' key (pipeline format)
      - Dict with 'matchdays' key (orchestrator format)
    """
    if not os.path.isfile(picks_path):
        print(f"ERROR: Picks file not found: {picks_path}", file=sys.stderr)
        sys.exit(1)

    with open(picks_path, 'r') as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Pipeline format: { "picks": [...] }
        if 'picks' in data:
            picks = data['picks']
            season_id = data.get('season_id', '')
            matchday = data.get('matchday', 0)
            for p in picks:
                if 'season_id' not in p:
                    p['season_id'] = season_id
                if 'match_day' not in p:
                    p['match_day'] = matchday
            return picks
        # Orchestrator format: { "matchdays": [{ "fixtures": [...] }] }
        if 'matchdays' in data:
            return _extract_picks_from_orchestrator(data)
    return []


def _extract_picks_from_orchestrator(data: Dict) -> List[Dict]:
    """Extract picks from the live_test_predictions.json format."""
    picks = []
    for md_entry in data.get('matchdays', []):
        season_name = md_entry.get('season_name', '')
        season_id = md_entry.get('season_id', '')
        matchday = md_entry.get('matchday', 0)
        for fx in md_entry.get('fixtures', []):
            home = fx.get('home', '') or fx.get('home_team', '')
            away = fx.get('away', '') or fx.get('away_team', '')
            event_id = fx.get('event_id', '')
            
            pred = fx.get('prediction')
            primary = {}
            
            if isinstance(pred, dict):
                primary = pred.get('primary') or {}
                if (not primary or not primary.get('market')) and 'predictions' in pred:
                    preds = pred['predictions']
                    if preds:
                        primary = preds[0] if isinstance(preds[0], dict) else {}
            elif 'predictions' in fx and isinstance(fx['predictions'], list):
                preds = fx['predictions']
                if preds:
                    primary = preds[0] if isinstance(preds[0], dict) else {}
            
            if not primary or not isinstance(primary, dict) or not primary.get('market'):
                picks.append({
                    'home_team': home,
                    'away_team': away,
                    'event_id': event_id,
                    'rec_bet': '',
                    'market': '',
                    'avg_odds': 0.0,
                    'odds': 0.0,
                    'season_name': season_name,
                    'season_id': season_id,
                    'match_day': matchday,
                    'source': 'orchestrator_unpredicted',
                })
                continue

            market = primary.get('market', '')
            odds = primary.get('odds', 0.0)

            picks.append({
                'home_team': home,
                'away_team': away,
                'event_id': event_id,
                'rec_bet': market,
                'market': market,
                'avg_odds': odds,
                'odds': odds,
                'season_name': season_name,
                'season_id': season_id,
                'match_day': matchday,
                'source': 'orchestrator',
            })
    return picks


def resolve_season_id(season_identifier: str) -> str:
    """Resolve a season identifier to a full vf:season:XXXXXX ID.

    Accepts:
      - Full ID:  'vf:season:3091977'
      - Number:   '5113' or 5113
      - Name:     'VFLM 5113'
    """
    if not isinstance(season_identifier, str):
        season_identifier = str(season_identifier)
    if season_identifier.startswith('vf:season:'):
        return season_identifier
    match = re.search(r'(\d+)', season_identifier)
    if not match:
        return season_identifier
    season_num = match.group(1)
    conn = sqlite3.connect(ODDS_DB_PATH)
    try:
        rows = conn.execute("""
            SELECT DISTINCT season_id FROM event_details
            WHERE season_name = ? LIMIT 1
        """, (f'VFLM {season_num}',)).fetchall()
        if rows:
            return rows[0][0]
        rows = conn.execute("""
            SELECT DISTINCT season_id FROM event_details
            WHERE season_id LIKE ? LIMIT 1
        """, (f'%:{season_num}',)).fetchall()
        if rows:
            return rows[0][0]
        return season_identifier
    finally:
        conn.close()


def lookup_season_name(season_id: str) -> str:
    """Look up the human-readable season name."""
    conn = sqlite3.connect(ODDS_DB_PATH)
    try:
        rows = conn.execute("""
            SELECT DISTINCT season_name FROM event_details
            WHERE season_id = ? LIMIT 1
        """, (season_id,)).fetchall()
        return rows[0][0] if rows else season_id
    finally:
        conn.close()


def lookup_event_id(season_id: str, matchday: int,
                    home_team: str, away_team: str) -> str:
    """Look up event_id from odds DB for a given fixture."""
    conn = sqlite3.connect(ODDS_DB_PATH)
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


# ──────────────────────────────────────────────────────────────────────
# RESULTS QUERY
# ──────────────────────────────────────────────────────────────────────

def query_match_result(conn: sqlite3.Connection,
                       home_team: str, away_team: str,
                       season_id: str = '', matchday: int = 0,
                       event_id: str = '') -> Optional[Dict]:
    """Query vfl_results.db for a match result.

    Tries multiple strategies:
      1. By event_id (most precise)
      2. By home_team + away_team + season_id + match_day
      3. By home_team + away_team + season_id
      4. By home_team + away_team (last resort)
    """
    # Strategy 1: event_id
    if event_id:
        rows = conn.execute("""
            SELECT home_goals, away_goals, total_goals, status, season_name, match_day
            FROM results WHERE event_id = ?
        """, (event_id,)).fetchall()
        if rows:
            return dict(rows[0])

    # Strategy 2: exact fixture + season_name + matchday
    if season_id and matchday > 0:
        # Get season_name for season_id
        season_name = lookup_season_name(season_id)
        rows = conn.execute("""
            SELECT home_goals, away_goals, total_goals, status, season_name, match_day
            FROM results
            WHERE home_team = ? AND away_team = ?
              AND (season_name = ? OR season_name = (SELECT DISTINCT season_name FROM results WHERE season_id = ? LIMIT 1))
              AND match_day = ?
            ORDER BY captured_at DESC LIMIT 1
        """, (home_team, away_team, season_name or '', season_id, matchday)).fetchall()
        if rows:
            return dict(rows[0])

    # Strategy 3: home + away + season_name
    if season_id:
        season_name = lookup_season_name(season_id)
        rows = conn.execute("""
            SELECT home_goals, away_goals, total_goals, status, season_name, match_day
            FROM results
            WHERE home_team = ? AND away_team = ?
              AND (season_name = ? OR season_name = (SELECT DISTINCT season_name FROM results WHERE season_id = ? LIMIT 1))
            ORDER BY captured_at DESC LIMIT 1
        """, (home_team, away_team, season_name or '', season_id)).fetchall()
        if rows:
            return dict(rows[0])

    # Strategy 4: just home + away (fuzzy)
    rows = conn.execute("""
        SELECT home_goals, away_goals, total_goals, status, season_name, match_day
        FROM results
        WHERE home_team = ? AND away_team = ?
        ORDER BY captured_at DESC LIMIT 1
    """, (home_team, away_team)).fetchall()
    if rows:
        return dict(rows[0])

    return None


# ──────────────────────────────────────────────────────────────────────
# VERIFICATION STATE
# ──────────────────────────────────────────────────────────────────────

def load_verification_state() -> Dict:
    """Load the cluster verification state from disk."""
    if os.path.isfile(VERIFICATION_STATE_PATH):
        with open(VERIFICATION_STATE_PATH, 'r') as f:
            return json.load(f)
    return {
        'last_updated': None,
        'total_picks': 0,
        'clusters': {},
        'history': [],
    }


def save_verification_state(state: Dict):
    """Save the cluster verification state to disk."""
    os.makedirs(VERIFICATION_STATE_DIR, exist_ok=True)
    state['last_updated'] = datetime.now(timezone.utc).isoformat()
    with open(VERIFICATION_STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2)


def compute_verdict(hit_rate: float, roi_pct: float, avg_odds: float) -> str:
    """Compute cluster verdict based on hit rate and ROI.

    - 'PLAY':     ROI > 0% AND hit_rate >= breakeven
    - 'MONITOR':  ROI > -5%  (but not PLAY-worthy)
    - 'PAUSE':    ROI <= -5%
    """
    breakeven = 1.0 / avg_odds if avg_odds > 0 else 0.5
    if roi_pct > 0 and hit_rate >= breakeven:
        return 'PLAY'
    elif roi_pct > -5:
        return 'MONITOR'
    else:
        return 'PAUSE'


# ──────────────────────────────────────────────────────────────────────
# UPDATE CLUSTER RECOMMENDATIONS
# ──────────────────────────────────────────────────────────────────────

def update_cluster_recommendations(state: Dict) -> bool:
    """Patch odds_cluster_classifier.py's CLUSTER_RECOMMENDATIONS list
    when verified hit rate deviates by more than 5% from the stored rate.

    Returns True if any changes were made.
    """
    changes_made = False
    clusters = state.get('clusters', {})
    if not clusters:
        print("  No cluster data to update from.", file=sys.stderr)
        return False

    classifier_path = CLUSTER_RECOMMENDATIONS_PATH
    if not os.path.isfile(classifier_path):
        print(f"  ERROR: Classifier file not found: {classifier_path}", file=sys.stderr)
        return False

    with open(classifier_path, 'r') as f:
        content = f.read()

    for cid_str, cdata in sorted(clusters.items()):
        cid = int(cid_str)
        verified_rate = cdata.get('verified_hit_rate', 0)
        original_rate = cdata.get('stored_hit_rate', 0)
        total = cdata.get('total_picks', 0)

        # Need at least 10 picks for a statistically meaningful update
        if total < 10:
            continue

        deviation = verified_rate - original_rate
        if abs(deviation) <= 0.05:
            continue

        # Build the replacement line for this cluster's recommendation
        market = cdata.get('market', 'GG')
        avg_odds = cdata.get('avg_odds', 1.8)
        label_str = f"{market} {verified_rate*100:.1f}% @{avg_odds:.2f}"

        # Find and replace the CLUSTER_RECOMMENDATIONS entry for this index
        # Pattern: line in CLUSTER_RECOMMENDATIONS = [...]
        old_pattern = None
        new_line = None

        lines = content.split('\n')
        in_cluster_recs = False
        rec_lines = []
        rec_start = -1
        rec_end = -1
        depth = 0

        for i, line in enumerate(lines):
            stripped = line.strip()

            if 'CLUSTER_RECOMMENDATIONS' in stripped and '=' in stripped:
                in_cluster_recs = True
                rec_start = i
                depth = stripped.count('[') - stripped.count(']')
                if depth > 0:
                    rec_lines.append(i)
                continue

            if in_cluster_recs:
                rec_lines.append(i)
                depth += stripped.count('[') - stripped.count(']')
                if depth <= 0:
                    rec_end = i
                    break

        if rec_start < 0 or rec_end < 0:
            print(f"  WARNING: Could not locate CLUSTER_RECOMMENDATIONS in classifier.",
                  file=sys.stderr)
            return False

        # Extract the array block between rec_start and rec_end
        rec_block = lines[rec_start:rec_end + 1]
        rec_text = '\n'.join(rec_block)

        # Find the dict for our cluster index (nth entry, 0-indexed)
        import re as _re
        # Split by top-level dict entries
        entry_pattern = _re.compile(r"\{[^}]*\}")
        entries = entry_pattern.findall(rec_text)

        if cid >= len(entries):
            print(f"  WARNING: Cluster {cid} not found in recommendations (have {len(entries)}).",
                  file=sys.stderr)
            continue

        old_entry = entries[cid]
        # Parse old entry values
        old_market = _re.search(r"'market':\s*'([^']*)'", old_entry)
        old_hit_rate = _re.search(r"'hit_rate':\s*([\d.]+)", old_entry)
        old_avg_odds = _re.search(r"'avg_odds':\s*([\d.]+)", old_entry)

        if not old_market or not old_hit_rate or not old_avg_odds:
            continue

        new_hit_rate = round(verified_rate, 3)
        new_odds = round(cdata.get('avg_odds', float(old_avg_odds.group(1))), 2)
        new_market = cdata.get('market', old_market.group(1))

        new_entry = old_entry.replace(
            old_hit_rate.group(0),
            f"'hit_rate': {new_hit_rate}"
        )
        new_entry = new_entry.replace(
            old_avg_odds.group(0),
            f"'avg_odds': {new_odds}"
        )
        if cdata.get('market'):
            new_entry = new_entry.replace(
                f"'market': '{old_market.group(1)}'",
                f"'market': '{new_market}'"
            )
        # Update label
        old_label_match = _re.search(r"'label':\s*'([^']*)'", new_entry)
        if old_label_match:
            new_label = f"{new_market} {new_hit_rate*100:.1f}% @{new_odds:.2f}"
            new_entry = new_entry.replace(
                f"'label': '{old_label_match.group(1)}'",
                f"'label': '{new_label}'"
            )

        # Replace in content
        content = content.replace(old_entry, new_entry, 1)
        direction = "RAISED" if deviation > 0 else "LOWERED"
        print(f"  C{cid}: {direction} hit rate {original_rate*100:.1f}% → {verified_rate*100:.1f}% "
              f"(deviation {deviation*100:+.1f}%)", file=sys.stderr)
        changes_made = True

    if changes_made:
        with open(classifier_path, 'w') as f:
            f.write(content)
        print(f"  → Updated {classifier_path}", file=sys.stderr)
    else:
        print(f"  → No cluster updates needed (all within ±5% tolerance).", file=sys.stderr)

    return changes_made


# ──────────────────────────────────────────────────────────────────────
# VERIFICATION ENGINE
# ──────────────────────────────────────────────────────────────────────

def verify_picks(picks: List[Dict],
                 state: Dict,
                 season_id: str = '',
                 matchday: int = 0,
                 verbose: bool = True,
                 cron: bool = False) -> Dict:
    """Verify a list of picks against actual results.

    Args:
        picks: List of pick dicts (must have home_team, away_team, rec_bet/market)
        state: Current verification state dict (mutated in-place)
        season_id: Season identifier for context
        matchday: Matchday number for context
        verbose: Print progress during verification
        cron: Quiet mode (stderr only)

    Returns:
        Dict with verification results
    """
    conn = sqlite3.connect(RESULTS_DB_PATH)
    conn.row_factory = sqlite3.Row

    results_list = []
    cluster_md_picks = defaultdict(list)  # cid -> list of {(result, odds, market)}

    # Resolve season name for display
    season_name = ''
    if season_id:
        season_name = lookup_season_name(season_id)
    elif picks and picks[0].get('season_name'):
        season_name = picks[0]['season_name']

    if not cron:
        print(f"  Verifying {len(picks)} picks against results DB...", file=sys.stderr)

    for idx, pick in enumerate(picks):
        home = pick.get('home_team', '')
        away = pick.get('away_team', '')
        event_id = pick.get('event_id', '')

        # Get market — try multiple key names
        market_str = (pick.get('rec_bet') or pick.get('market') or
                      pick.get('recommended_market') or '')
        odds = (pick.get('avg_odds') or pick.get('odds') or 0)
        cid = pick.get('cluster_id')
        if cid is None:
            cid = -1

        # Resolve market
        resolved = resolve_market(market_str) if market_str else None
        if resolved is None and market_str and not cron:
            # Could be a source field, not a market — skip silently
            if verbose:
                print(f"  WARNING: Unrecognised market '{market_str}' for {home} vs {away}",
                      file=sys.stderr)

        pick_season_id = pick.get('season_id', season_id)
        pick_matchday = pick.get('match_day', matchday)

        # Query result
        result = query_match_result(
            conn, home, away,
            season_id=pick_season_id,
            matchday=pick_matchday,
            event_id=event_id,
        )

        entry = {
            'home_team': home,
            'away_team': away,
            'event_id': event_id,
            'market': market_str,
            'odds': odds,
            'cluster_id': cid,
        }

        if result is None:
            entry['status'] = 'PENDING'
            entry['result_found'] = False
            if not cron:
                print(f"  {idx+1:3d}. {home:20s} vs {away:20s} → ⏳ PENDING (no result found)",
                      file=sys.stderr)
        else:
            status = result['status']
            hg = result['home_goals']
            ag = result['away_goals']
            tg = result['total_goals']

            if status == 0 or hg is None:
                entry['status'] = 'PENDING'
                entry['result_found'] = False
                if not cron:
                    print(f"  {idx+1:3d}. {home:20s} vs {away:20s} → ⏳ PENDING (status={status})",
                          file=sys.stderr)
            else:
                entry['status'] = 'SETTLED'
                entry['result_found'] = True
                entry['home_goals'] = hg
                entry['away_goals'] = ag
                entry['total_goals'] = tg

                if resolved:
                    won = resolved['check'](tg, hg, ag)
                    entry['canonical_market'] = resolved['market']
                    entry['won'] = won

                    if cid >= 0:
                        cluster_md_picks[cid].append({
                            'won': won,
                            'odds': odds,
                            'market': resolved['market'],
                        })
                else:
                    entry['won'] = None
                    entry['canonical_market'] = None

                score_str = f"{hg}-{ag}"
                if not cron:
                    # Determine outcome symbol
                    if entry.get('won') is True:
                        sym = '✓ WON'
                    elif entry.get('won') is False:
                        sym = '✗ LOST'
                    else:
                        sym = '?'
                    cid_tag = f"[C{cid}]" if cid >= 0 else ""
                    print(f"  {idx+1:3d}. {home:20s} vs {away:20s}: {market_str:10s} "
                          f"@{odds:.2f} {cid_tag} → {sym} ({score_str})",
                          file=sys.stderr)

        results_list.append(entry)

    conn.close()

    # ── Update cluster stats ──────────────────────────────────────
    clusters_state = state.setdefault('clusters', {})
    overall_wins = 0
    overall_losses = 0
    overall_pending = 0
    overall_stake = 0.0
    overall_return = 0.0

    for cid, md_picks in cluster_md_picks.items():
        cid_str = str(cid)
        c_state = clusters_state.setdefault(cid_str, {
            'total_picks': 0,
            'wins': 0,
            'losses': 0,
            'hit_rate': 0.0,
            'total_stake': 0.0,
            'total_return': 0.0,
            'stored_hit_rate': None,
            'stored_avg_odds': None,
            'market': None,
            'verdict': 'NEW',
            'last_verified': None,
        })

        wins = sum(1 for p in md_picks if p['won'])
        losses = sum(1 for p in md_picks if not p['won'])
        stake = sum(DEFAULT_STAKE for p in md_picks if p['odds'] > 0)
        returns = sum(DEFAULT_STAKE * p['odds'] for p in md_picks if p['won'] and p['odds'] > 0)

        c_state['total_picks'] += len(md_picks)
        c_state['wins'] += wins
        c_state['losses'] += losses
        c_state['total_stake'] += stake
        c_state['total_return'] += returns

        total_picks_c = c_state['total_picks']
        c_state['hit_rate'] = round(c_state['wins'] / total_picks_c, 4) if total_picks_c > 0 else 0.0

        # Store the market from the most common pick for this cluster
        markets_in_cluster = [p['market'] for p in md_picks]
        if markets_in_cluster:
            most_common = max(set(markets_in_cluster), key=markets_in_cluster.count)
            c_state['market'] = most_common

        # Compute ROI
        roi_pct = 0.0
        if c_state['total_stake'] > 0:
            net = c_state['total_return'] - c_state['total_stake']
            roi_pct = round((net / c_state['total_stake']) * 100, 2)
        c_state['roi_pct'] = roi_pct

        # Store avg_odds from current data if not yet set
        if c_state['stored_avg_odds'] is None:
            valid_odds = [p['odds'] for p in md_picks if p['odds'] > 0]
            avg_odds = sum(valid_odds) / max(len(valid_odds), 1) if valid_odds else 0
            c_state['avg_odds'] = round(avg_odds, 2) if avg_odds > 0 else 1.8

        # Verdict
        avg_odds_used = c_state.get('avg_odds', c_state.get('stored_avg_odds', 1.8))
        c_state['verdict'] = compute_verdict(
            c_state['hit_rate'], roi_pct, avg_odds_used
        )
        c_state['last_verified'] = datetime.now(timezone.utc).isoformat()

        overall_wins += wins
        overall_losses += losses
        overall_stake += stake
        overall_return += returns

    # Process unclustered settled picks for overall stats
    for entry in results_list:
        status = entry['status']
        cid = entry.get('cluster_id', -1)
        settled = status == 'SETTLED' and entry.get('result_found', False)
        odds = entry.get('odds', 0) or 0
        won = entry.get('won')
        has_market = bool(entry.get('market', ''))

        if settled and won is True and has_market and odds > 0:
            if cid < 0:
                overall_wins += 1
                overall_stake += DEFAULT_STAKE
                overall_return += DEFAULT_STAKE * odds
        elif settled and won is False and has_market and odds > 0:
            if cid < 0:
                overall_losses += 1
                overall_stake += DEFAULT_STAKE
        elif settled and won is None:
            # Settled but no market to check (unpredicted fixture)
            if cid < 0:
                overall_pending += 1
        elif not settled:
            overall_pending += 1

    # ── Build verification result ─────────────────────────────────
    total_settled = overall_wins + overall_losses
    total_all = len(results_list)
    overall_hit_rate = round(overall_wins / total_settled, 4) if total_settled > 0 else 0.0
    overall_roi_pct = 0.0
    if overall_stake > 0:
        overall_roi_pct = round(((overall_return - overall_stake) / overall_stake) * 100, 2)

    vr = {
        'season_id': season_id,
        'season_name': season_name,
        'matchday': matchday,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_picks': total_all,
        'settled': total_settled,
        'pending': total_all - total_settled,
        'wins': overall_wins,
        'losses': overall_losses,
        'hit_rate': overall_hit_rate,
        'total_stake': round(overall_stake, 2),
        'total_return': round(overall_return, 2),
        'roi_pct': overall_roi_pct,
        'picks': results_list,
        'cluster_summary': {},
    }

    # Build cluster summary for report
    for cid_str, c_state in sorted(clusters_state.items(), key=lambda x: int(x[0])):
        vr['cluster_summary'][cid_str] = {
            'total_picks': c_state['total_picks'],
            'wins': c_state['wins'],
            'losses': c_state['losses'],
            'hit_rate': c_state['hit_rate'],
            'roi_pct': c_state['roi_pct'],
            'verdict': c_state['verdict'],
            'market': c_state.get('market', ''),
        }

    # Save state
    state['total_picks'] = sum(c['total_picks'] for c in clusters_state.values())
    history_entry = {
        'season_id': season_id,
        'season_name': season_name,
        'matchday': matchday,
        'timestamp': vr['timestamp'],
        'total_picks': total_all,
        'settled': total_settled,
        'wins': overall_wins,
        'losses': overall_losses,
        'hit_rate': overall_hit_rate,
        'roi_pct': overall_roi_pct,
    }
    state.setdefault('history', []).append(history_entry)
    save_verification_state(state)

    return vr


# ──────────────────────────────────────────────────────────────────────
# REPORT FORMATTING
# ──────────────────────────────────────────────────────────────────────

def format_verification_report(vr: Dict) -> str:
    """Format the verification result as a human-readable report string."""
    season_name = vr.get('season_name', f"Season {vr.get('season_id', '?')}")
    matchday = vr.get('matchday', '?')
    lines = []

    lines.append("═══ VERIFICATION REPORT ═══")
    lines.append(f"Season: {season_name} | Matchday: {matchday}")
    lines.append("")

    # ── Picks Detail ──
    lines.append("── Picks ──────────────────")
    for p in vr.get('picks', []):
        home = p.get('home_team', '?')
        away = p.get('away_team', '?')
        market = p.get('market', '?')
        odds = p.get('odds', 0)
        cid = p.get('cluster_id', -1)
        cid_tag = f"[C{cid}]" if cid >= 0 else ""

        if p.get('status') == 'SETTLED' and p.get('result_found'):
            score = f"{p.get('home_goals', '?')}-{p.get('away_goals', '?')}"
            if p.get('won') is True:
                status_str = f"✓ WON ({score})"
            elif p.get('won') is False:
                status_str = f"✗ LOST ({score})"
            else:
                status_str = f"? ({score})"
        else:
            status_str = "⏳ PENDING"

        lines.append(f"  {home} vs {away}: {market} @{odds:.2f} {cid_tag} → {status_str}")

    lines.append("")

    # ── Cluster Stats ──
    lines.append("── Cluster Stats ────────────")
    cluster_summary = vr.get('cluster_summary', {})
    if cluster_summary:
        for cid_str, cs in sorted(cluster_summary.items(), key=lambda x: int(x[0])):
            w = cs['wins']
            l_ = cs['losses']
            total = cs['total_picks']
            hr = cs['hit_rate'] * 100
            roi = cs['roi_pct']
            verdict = cs['verdict']
            market = cs.get('market', '')
            lines.append(f"  C{cid_str}: {total} picks | {w}W/{l_}L | {hr:.1f}% | "
                         f"ROI: {roi:+.1f}% → {verdict}")
    else:
        lines.append("  (no clustered picks in this batch)")

    lines.append("")

    # ── Overall ──
    total = vr['total_picks']
    settled = vr['settled']
    wins = vr['wins']
    losses = vr['losses']
    hr = vr['hit_rate'] * 100
    roi = vr['roi_pct']
    pending = vr['pending']
    lines.append(f"  Overall: {total} picks ({settled} settled, {pending} pending) | "
                 f"{wins}W/{losses}L | {hr:.1f}% | ROI: {roi:+.1f}%")

    return '\n'.join(lines)


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Verify VFL predictions against actual results.")
    parser.add_argument('--season', type=str, help='Season identifier (e.g. 5113, or vf:season:005113)')
    parser.add_argument('--matchday', type=int, help='Matchday number (e.g. 10)')
    parser.add_argument('--picks-file', type=str, help='Path to custom picks JSON file')
    parser.add_argument('--latest', action='store_true', help='Verify the latest predictions')
    parser.add_argument('--update-clusters', action='store_true', help='Update cluster recommendations in classifier')
    parser.add_argument('--cron', action='store_true', help='Output JSON for cron jobs.')
    parser.add_argument('--json', action='store_true', help='Output verification result as JSON')
    args = parser.parse_args()

    # Load state
    state = load_verification_state()

    # Determine picks file
    picks_path = None
    if args.picks_file:
        picks_path = args.picks_file
    elif args.season and args.matchday is not None:
        picks_path = os.path.join(SIGNALS_DIR, f"pipeline_picks_md{args.matchday}.json")
    elif args.matchday is not None:
        picks_path = os.path.join(SIGNALS_DIR, f"pipeline_picks_md{args.matchday}.json")
    elif args.latest or (not args.season and args.matchday is None):
        # Scan SIGNALS_DIR for pipeline_picks_md*.json
        if os.path.isdir(SIGNALS_DIR):
            files = os.listdir(SIGNALS_DIR)
            pattern = re.compile(r'^pipeline_picks_md(\d+)\.json$')
            matchday_files = []
            for f in files:
                m = pattern.match(f)
                if m:
                    matchday_files.append((int(m.group(1)), os.path.join(SIGNALS_DIR, f)))
            if matchday_files:
                matchday_files.sort(key=lambda x: x[0], reverse=True)
                picks_path = matchday_files[0][1]
                if not args.cron and not args.json:
                    print(f"No matchday specified, resolved to latest matchday: {matchday_files[0][0]} from {picks_path}")
            else:
                # If no pipeline_picks_md*.json, check predictions_latest.json
                if os.path.isfile(LIVE_PREDICTIONS_PATH):
                    picks_path = LIVE_PREDICTIONS_PATH
                    if not args.cron and not args.json:
                        print(f"No pipeline picks files found. Using live predictions from: {LIVE_PREDICTIONS_PATH}")

    if not picks_path or not os.path.isfile(picks_path):
        print(f"ERROR: Could not resolve picks file path. Specified: season={args.season}, matchday={args.matchday}, picks_file={args.picks_file}", file=sys.stderr)
        sys.exit(1)

    picks = load_picks_from_file(picks_path)
    if not picks:
        print(f"ERROR: No picks loaded from {picks_path}", file=sys.stderr)
        sys.exit(1)

    # Resolve season and matchday
    season_id = ""
    matchday_num = 0
    
    # Try to find a valid season_id and match_day in the picks
    for p in picks:
        if not season_id and p.get('season_id'):
            season_id = p['season_id']
        if not matchday_num and p.get('match_day'):
            try:
                matchday_num = int(p['match_day'])
            except (ValueError, TypeError):
                pass

    # Override with command line arguments if specified
    if args.season:
        season_id = resolve_season_id(args.season)
    if args.matchday is not None:
        matchday_num = args.matchday

    # If still not found, try predictions_latest.json
    if not season_id or not matchday_num:
        pred_data = load_live_predictions()
        if pred_data and pred_data.get('matchdays'):
            first_md = pred_data['matchdays'][0]
            if not season_id:
                season_id = resolve_season_id(first_md.get('season', ''))
            if not matchday_num:
                matchday_num = first_md.get('matchday', 0)

    if not season_id:
        print("ERROR: Could not resolve season_id. Please specify with --season.", file=sys.stderr)
        sys.exit(1)
    if not matchday_num:
        print("ERROR: Could not resolve matchday. Please specify with --matchday.", file=sys.stderr)
        sys.exit(1)

    verbose = not (args.cron or args.json)
    
    # Verify picks
    try:
        vr = verify_picks(
            picks=picks,
            state=state,
            season_id=season_id,
            matchday=matchday_num,
            verbose=verbose,
            cron=args.cron
        )
    except Exception as e:
        print(f"ERROR: Verification failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Perform updates if requested
    if args.update_clusters:
        if verbose:
            print("\nUpdating cluster recommendations in classifier...")
        updated = update_cluster_recommendations(state)
        if verbose:
            if updated:
                print("Successfully updated cluster recommendations!")
            else:
                print("No updates needed or no cluster recommendations changed.")

    # Output formatting
    if args.cron or args.json:
        # Return full verification result structure as json
        print(json.dumps(vr, indent=2))
    else:
        report = format_verification_report(vr)
        print(report)


if __name__ == '__main__':
    main()
