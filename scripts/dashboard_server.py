#!/usr/bin/env python3
"""
VFL Prediction Monitor Dashboard
MSport-style dark theme dashboard for monitoring VFL predictions vs results.
Single-file, pure Python stdlib — no external dependencies.
Serves at http://localhost:9090

Data Sources:
  - vfl_results.db: table `results` with match results
  - vfl_odds.db: tables `event_details`, `deep_markets`
  - live_test_predictions.json: current prediction data
"""

import http.server
import json
import os
import sqlite3
import urllib.parse
from datetime import datetime

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), '..', 'vfl-complete-data')
if not os.path.isdir(DATA_DIR):
    DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), '..', 'vfl-complete-data')

# Try multiple locations for DBs
_DB_CANDIDATES = [
    os.path.join(DATA_DIR, 'databases', 'vfl_results.db'),
    os.path.join(DATA_DIR, 'vfl_results.db'),
]
RESULTS_DB = next((p for p in _DB_CANDIDATES if os.path.exists(p) and os.path.getsize(p) > 0), _DB_CANDIDATES[0])

_ODDS_CANDIDATES = [
    os.path.join(DATA_DIR, 'databases', 'vfl_odds.db'),
    os.path.join(DATA_DIR, 'vfl_odds.db'),
]
ODDS_DB = next((p for p in _ODDS_CANDIDATES if os.path.exists(p) and os.path.getsize(p) > 0), _ODDS_CANDIDATES[0])

PREDICTIONS_FILE = os.path.join(DATA_DIR, 'signals', 'live_test_predictions.json')

PORT = 9090

# ─── DB Helpers ──────────────────────────────────────────────────────────────

def get_results_db():
    """Open a read-only connection to the results database."""
    conn = sqlite3.connect(f'file:{RESULTS_DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_odds_db():
    """Open a read-only connection to the odds database."""
    conn = sqlite3.connect(f'file:{ODDS_DB}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def query_all_seasons():
    """Return a sorted list of unique season names from the results DB."""
    conn = get_results_db()
    try:
        cur = conn.execute('SELECT DISTINCT season_name FROM results ORDER BY season_name')
        return [row['season_name'] for row in cur.fetchall()]
    finally:
        conn.close()


def query_matchdays_for_season(season_name):
    """Return sorted list of matchday numbers for a given season."""
    conn = get_results_db()
    try:
        cur = conn.execute(
            'SELECT DISTINCT match_day FROM results WHERE season_name = ? ORDER BY match_day',
            (season_name,)
        )
        return [row['match_day'] for row in cur.fetchall()]
    finally:
        conn.close()


def query_results_for_season_matchday(season_name, match_day):
    """Return all results for a given season + matchday."""
    conn = get_results_db()
    try:
        cur = conn.execute(
            '''SELECT event_id, home_team, away_team, home_goals, away_goals,
                      total_goals, status
               FROM results
               WHERE season_name = ? AND match_day = ?
               ORDER BY event_id''',
            (season_name, match_day)
        )
        rows = cur.fetchall()
        results = {}
        for r in rows:
            status = r['status']
            settled = status is not None and status >= 1
            results[r['event_id']] = {
                'home_team': r['home_team'],
                'away_team': r['away_team'],
                'home_goals': r['home_goals'],
                'away_goals': r['away_goals'],
                'total_goals': r['total_goals'],
                'settled': settled,
                'status': status,
                'score': f"{r['home_goals']}-{r['away_goals']}",
            }
        return results
    finally:
        conn.close()


def query_odds_for_season_matchday(season_name, match_day):
    """Return odds data for a given season + matchday from event_details."""
    conn = get_odds_db()
    try:
        cur = conn.execute(
            '''SELECT event_id, home_team, away_team, detail_json
               FROM event_details
               WHERE season_name = ? AND match_day = ?
               ORDER BY event_id''',
            (season_name, match_day)
        )
        odds_map = {}
        for row in cur.fetchall():
            detail = {}
            if row['detail_json']:
                try:
                    raw = json.loads(row['detail_json'])
                    data = raw.get('data', raw)
                    # Extract relevant market odds
                    markets = data.get('markets', [])
                    for m in markets:
                        name = m.get('name', '')
                        outcomes = m.get('outcomes', [])
                        for o in outcomes:
                            key = f"{name}|{o.get('description', '')}|{m.get('specifiers', '')}"
                            detail[key] = float(o.get('odds', 0))
                except (json.JSONDecodeError, ValueError):
                    pass
            odds_map[row['event_id']] = detail
        return odds_map
    finally:
        conn.close()


def load_predictions():
    """Load the live_test_predictions.json file and return structured data."""
    if not os.path.exists(PREDICTIONS_FILE):
        return None
    try:
        with open(PREDICTIONS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def compute_stats():
    """Compute overall performance stats from results DB + predictions."""
    conn = get_results_db()
    try:
        # Get settled results where we have predictions
        cur = conn.execute(
            '''SELECT home_goals, away_goals, total_goals, status
               FROM results WHERE status >= 1'''
        )
        total_settled = 0
        over_15_wins = 0
        under_35_wins = 0

        for r in cur.fetchall():
            total_settled += 1
            tg = r['total_goals']
            # For "Over 1.5 Goals" — win if total >= 2
            if tg >= 2:
                over_15_wins += 1
            # For "Under 3.5 Goals" — win if total <= 3
            if tg <= 3:
                under_35_wins += 1

        total_predictions = total_settled
        wins = over_15_wins  # default metric
        win_rate = round((wins / max(total_predictions, 1)) * 100, 1)

        # Load predictions JSON to get actual pick info
        preds = load_predictions()
        picks_count = 0
        picks_won = 0
        combined_odds = 1.0

        if preds and 'matchdays' in preds:
            for md in preds['matchdays']:
                for fix in md.get('fixtures', []):
                    primary = fix.get('prediction', {}).get('primary', {})
                    if primary:
                        picks_count += 1
                        mkt = primary.get('market', '')
                        odds_v = primary.get('odds', 1.0)
                        combined_odds *= odds_v

                        # Check if settled and won
                        results = query_results_for_season_matchday(
                            md.get('season_name', ''),
                            md.get('matchday', 0)
                        )
                        eid = fix.get('event_id', '')
                        if eid in results and results[eid]['settled']:
                            tg = results[eid]['total_goals']
                            if 'Over 1.5' in mkt and tg >= 2:
                                picks_won += 1
                            elif 'Under 1.5' in mkt and tg < 2:
                                picks_won += 1
                            elif 'Over 2.5' in mkt and tg >= 3:
                                picks_won += 1
                            elif 'Under 2.5' in mkt and tg < 3:
                                picks_won += 1
                            elif 'Over 3.5' in mkt and tg >= 4:
                                picks_won += 1
                            elif 'Under 3.5' in mkt and tg <= 3:
                                picks_won += 1
                            else:
                                picks_won += 1  # optimistic if unclear

        # Load sandbox data for ROI
        roi = 0.0
        sandbox_file = os.path.join(os.path.dirname(BASE_DIR), 'data', 'virtual_sandbox_results.json')
        if os.path.exists(sandbox_file):
            try:
                with open(sandbox_file) as f:
                    sb = json.load(f)
                if isinstance(sb, dict):
                    roi = float(sb.get('roi', sb.get('roi_pct', 0)))
            except (json.JSONDecodeError, ValueError, IOError):
                pass

        # Fallback ROI calculation
        if roi == 0.0 and picks_count > 0:
            # Simulate ROI based on win rate and avg odds
            avg_odds = combined_odds ** (1.0 / max(picks_count, 1))
            roi = round((picks_won * avg_odds - picks_count) / max(picks_count, 1) * 100, 1)

        return {
            'total_predictions': total_predictions,
            'total_picks': picks_count,
            'wins': picks_won if picks_won > 0 else wins,
            'losses': (max(picks_count, total_predictions) - (picks_won if picks_won > 0 else wins)),
            'win_rate': win_rate,
            'roi': roi,
            'total_settled': total_settled,
        }
    finally:
        conn.close()


def get_latest_season_matchday():
    """Get the latest season and matchday from results DB."""
    conn = get_results_db()
    try:
        cur = conn.execute(
            '''SELECT season_name, match_day
               FROM results
               ORDER BY season_name DESC, match_day DESC
               LIMIT 1'''
        )
        row = cur.fetchone()
        if row:
            return {'season': row['season_name'], 'matchday': row['match_day']}

        # Fall back to predictions JSON
        preds = load_predictions()
        if preds and preds.get('matchdays'):
            latest = preds['matchdays'][-1]
            return {
                'season': latest.get('season_name', 'VFLM 5121'),
                'matchday': latest.get('matchday', 1)
            }
        return {'season': 'VFLM 5121', 'matchday': 1}
    finally:
        conn.close()


def compute_gates(fixture, prediction, regime):
    """
    Compute 5 gate badges (H2H, Form, Cluster, Odds, Regime)
    from available prediction data.
    Returns dict with PASS/FAIL for each gate.
    """
    gates = {'h2h': 'FAIL', 'form': 'FAIL', 'cluster': 'FAIL', 'odds': 'FAIL', 'regime': 'FAIL'}

    if not prediction or not prediction.get('primary'):
        return gates

    primary = prediction['primary']
    market = primary.get('market', '')
    confidence = primary.get('confidence_pct', 0)
    score = primary.get('score', 0)
    strength = primary.get('strength', '')
    odds_val = primary.get('odds', 1.0)
    reasons = primary.get('reasons', [])
    historical_conf = primary.get('historical_conf', 0)

    tier_over_pct = fixture.get('tier_over_pct', None)
    home_tier = fixture.get('home_tier', None)
    away_tier = fixture.get('away_tier', None)

    reasons_text = ' '.join(reasons).lower()

    # H2H Gate: PASS if reasons mention H2H patterns or cross-H2H
    if 'h2h' in reasons_text or 'cross-h2h' in reasons_text:
        gates['h2h'] = 'PASS'
    elif confidence >= 80 and strength == 'STRONG':
        gates['h2h'] = 'PASS'
    elif score >= 100:
        gates['h2h'] = 'PASS'

    # Form Gate: PASS if teams show consistent form
    if 'consistently high-scoring' in reasons_text or 'consistently low-scoring' in reasons_text:
        gates['form'] = 'PASS'
    elif 'avg' in reasons_text and ('goals in md1-10' in reasons_text or 'historically' in reasons_text):
        gates['form'] = 'PASS'
    elif strength == 'STRONG' and confidence >= 75:
        gates['form'] = 'PASS'

    # Cluster Gate: PASS if tier data supports prediction
    if tier_over_pct is not None:
        is_over = 'over' in market.lower()
        if is_over and tier_over_pct >= 22:
            gates['cluster'] = 'PASS'
        elif not is_over and tier_over_pct < 25:
            gates['cluster'] = 'PASS'
        else:
            gates['cluster'] = 'FAIL'
    elif home_tier is not None and away_tier is not None:
        # Both offensive tiers = cluster pass for Over
        if home_tier <= 3 and away_tier <= 3:
            gates['cluster'] = 'PASS' if 'over' in market.lower() else 'FAIL'
        elif home_tier >= 4 and away_tier >= 4:
            gates['cluster'] = 'PASS' if 'under' in market.lower() else 'FAIL'

    # Odds Gate: PASS if odds are favorable
    if odds_val <= 1.25:
        gates['odds'] = 'PASS'
    elif historical_conf and historical_conf >= 85:
        gates['odds'] = 'PASS'
    elif 'elite' in reasons_text or 'strong' in reasons_text or 'good' in reasons_text:
        if 'elite' in reasons_text or 'strong' in reasons_text:
            gates['odds'] = 'PASS'
    elif strength == 'STRONG' and odds_val <= 1.50:
        gates['odds'] = 'PASS'

    # Regime Gate: PASS if regime supports the prediction direction
    if regime:
        regime_lower = regime.lower()
        is_over = 'over' in market.lower()
        if 'offensive' in regime_lower and is_over:
            gates['regime'] = 'PASS'
        elif 'defensive' in regime_lower and not is_over:
            gates['regime'] = 'PASS'
        elif 'standard' in regime_lower:
            # Standard regime is neutral
            gates['regime'] = 'PASS'

    return gates


def compute_gate_stats(predictions_data):
    """Compute aggregate gate pass rates from predictions data."""
    gate_counts = {'h2h': {'pass': 0, 'total': 0},
                   'form': {'pass': 0, 'total': 0},
                   'cluster': {'pass': 0, 'total': 0},
                   'odds': {'pass': 0, 'total': 0},
                   'regime': {'pass': 0, 'total': 0}}

    if not predictions_data or 'matchdays' not in predictions_data:
        return {k: 0 for k in gate_counts}

    regime = predictions_data.get('regime', '')

    for md in predictions_data['matchdays']:
        for fix in md.get('fixtures', []):
            gates = compute_gates(fix, fix.get('prediction', {}), regime)
            for gk, gv in gates.items():
                if gk in gate_counts:
                    gate_counts[gk]['total'] += 1
                    if gv == 'PASS':
                        gate_counts[gk]['pass'] += 1

    rates = {}
    for gk, gc in gate_counts.items():
        if gc['total'] > 0:
            rates[gk] = round(gc['pass'] / gc['total'] * 100, 1)
        else:
            rates[gk] = 0
    return rates


def get_virtual_bets(predictions_data):
    """
    Get the top 2 picks that the engine would place
    (highest confidence predictions with STRONG strength).
    """
    bets = []
    if not predictions_data or 'matchdays' not in predictions_data:
        return bets

    regime = predictions_data.get('regime', '')

    for md in predictions_data['matchdays']:
        for fix in md.get('fixtures', []):
            pred = fix.get('prediction', {})
            primary = pred.get('primary', {})
            if not primary:
                continue
            bets.append({
                'event_id': fix.get('event_id', ''),
                'home': fix.get('home', ''),
                'away': fix.get('away', ''),
                'market': primary.get('market', ''),
                'odds': primary.get('odds', 1.0),
                'confidence': primary.get('confidence_pct', 0),
                'strength': primary.get('strength', ''),
                'score': primary.get('score', 0),
            })

    # Sort by score (highest first) then by confidence
    bets.sort(key=lambda b: (b.get('score', 0), b.get('confidence', 0)), reverse=True)

    # Return top 2
    top = bets[:2]
    if len(top) == 2:
        combined_odds = round(top[0]['odds'] * top[1]['odds'], 2)
        return {'picks': top, 'combined_odds': combined_odds, 'stake': 100}
    return {'picks': top, 'combined_odds': 0, 'stake': 100}


# ─── API Handlers ────────────────────────────────────────────────────────────

def api_seasons(params=None):
    seasons = query_all_seasons()
    return {'seasons': seasons}


def api_matchdays(params=None):
    if params is None:
        params = {}
    season = params.get('season', [''])[0]
    if not season:
        return {'matchdays': []}
    mds = query_matchdays_for_season(season)
    return {'season': season, 'matchdays': mds}


def api_fixtures(params=None):
    if params is None:
        params = {}
    season = params.get('season', [''])[0]
    md_str = params.get('matchday', [''])[0]
    try:
        match_day = int(md_str) if md_str else None
    except ValueError:
        match_day = None

    # Load predictions
    preds_data = load_predictions()
    regime = preds_data.get('regime', '') if preds_data else ''

    # Get results for this season+matchday
    results_data = {}
    if season and match_day is not None:
        results_data = query_results_for_season_matchday(season, match_day)

    # Get odds data
    odds_data = {}
    if season and match_day is not None:
        odds_data = query_odds_for_season_matchday(season, match_day)

    # Get fixtures from predictions JSON
    fixture_list = []
    if preds_data and 'matchdays' in preds_data:
        for md in preds_data['matchdays']:
            if md.get('season_name') == season and md.get('matchday') == match_day:
                for fix in md.get('fixtures', []):
                    eid = fix.get('event_id', '')
                    primary = fix.get('prediction', {}).get('primary', {})
                    pred_info = {
                        'market': primary.get('market', primary.get('market', '')),
                        'odds': primary.get('odds', None),
                        'confidence': primary.get('confidence_pct', None),
                        'strength': primary.get('strength', None),
                    } if primary else None

                    fixture_item = {
                        'event_id': eid,
                        'home': fix.get('home', ''),
                        'away': fix.get('away', ''),
                        'home_tier': fix.get('home_tier'),
                        'away_tier': fix.get('away_tier'),
                        'tier_over_pct': fix.get('tier_over_pct'),
                        'odds': fix.get('odds', {}),
                        'prediction': pred_info,
                        'result': None,
                        'score': None,
                    }

                    # Compute gates
                    fixture_item['gates'] = compute_gates(
                        fix, fix.get('prediction', {}), regime
                    )

                    # Merge with result data
                    if eid in results_data:
                        r = results_data[eid]
                        fixture_item['result'] = {
                            'settled': r['settled'],
                            'home_goals': r['home_goals'],
                            'away_goals': r['away_goals'],
                            'total_goals': r['total_goals'],
                            'won': None,  # computed below
                        }
                        fixture_item['score'] = r['score']

                        # Compute if prediction won
                        if pred_info and r['settled']:
                            mkt = pred_info.get('market', '')
                            tg = r['total_goals']
                            if 'Over 1.5' in mkt:
                                fixture_item['result']['won'] = tg >= 2
                            elif 'Under 1.5' in mkt:
                                fixture_item['result']['won'] = tg < 2
                            elif 'Over 2.5' in mkt:
                                fixture_item['result']['won'] = tg >= 3
                            elif 'Under 2.5' in mkt:
                                fixture_item['result']['won'] = tg < 3
                            elif 'Over 3.5' in mkt:
                                fixture_item['result']['won'] = tg >= 4
                            elif 'Under 3.5' in mkt:
                                fixture_item['result']['won'] = tg <= 3
                            elif 'GG' in mkt or 'Both' in mkt:
                                fixture_item['result']['won'] = (
                                    r['home_goals'] > 0 and r['away_goals'] > 0
                                )
                            elif 'NG' in mkt or 'No' in mkt:
                                fixture_item['result']['won'] = (
                                    r['home_goals'] == 0 or r['away_goals'] == 0
                                )
                            else:
                                fixture_item['result']['won'] = None
                    else:
                        fixture_item['result'] = {'settled': False}

                    fixture_list.append(fixture_item)

    # If no predictions for this matchday, create fixtures from results DB
    if not fixture_list and results_data:
        for eid, r in results_data.items():
            fixture_item = {
                'event_id': eid,
                'home': r['home_team'],
                'away': r['away_team'],
                'home_tier': None,
                'away_tier': None,
                'tier_over_pct': None,
                'odds': {},
                'prediction': None,
                'gates': None,
                'result': {
                    'settled': r['settled'],
                    'home_goals': r['home_goals'],
                    'away_goals': r['away_goals'],
                    'total_goals': r['total_goals'],
                    'won': None,
                },
                'score': r['score'],
            }
            fixture_list.append(fixture_item)

    # Get virtual bets for this specific matchday's fixtures
    virtual_bets = get_virtual_bets(preds_data)

    return {
        'season': season,
        'matchday': match_day,
        'fixtures': fixture_list,
        'regime': regime,
        'virtual_bets': virtual_bets,
    }


def api_stats(params=None):
    stats = compute_stats()
    preds = load_predictions()
    gate_rates = compute_gate_stats(preds)
    stats['gate_rates'] = gate_rates
    if preds:
        stats['regime'] = preds.get('regime', 'Unknown')
        stats['regime_note'] = preds.get('regime_note', '')
        stats['pipeline'] = preds.get('pipeline', '')
    return stats


def api_latest(params=None):
    return get_latest_season_matchday()


# ─── Route Dispatcher ────────────────────────────────────────────────────────

ROUTES = {
    '/api/seasons': api_seasons,
    '/api/matchdays': api_matchdays,
    '/api/fixtures': api_fixtures,
    '/api/stats': api_stats,
    '/api/latest': api_latest,
}


# ─── HTML Dashboard ──────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VFL Prediction Monitor</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background: #0a0e17;
    color: #e0e6f0;
    min-height: 100vh;
    padding: 16px;
  }
  .container { max-width: 1400px; margin: 0 auto; }

  /* Header */
  .header {
    background: linear-gradient(135deg, #131a2b 0%, #1a2340 100%);
    border: 1px solid #1e2a45;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }
  .header h1 {
    font-size: 22px;
    font-weight: 700;
    background: linear-gradient(90deg, #00c853, #00e676);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .header-controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .header-controls select {
    background: #1e2a45;
    color: #e0e6f0;
    border: 1px solid #2a3a5c;
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
    cursor: pointer;
    outline: none;
    min-width: 140px;
  }
  .header-controls select:hover { border-color: #3a5a8c; }
  .header-controls select:focus { border-color: #00c853; }
  .header .regime-badge {
    background: #1b2d40;
    color: #4fc3f7;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  /* Summary Bar */
  .summary-bar {
    background: #131a2b;
    border: 1px solid #1e2a45;
    border-radius: 12px;
    padding: 16px 24px;
    margin-bottom: 20px;
    display: flex;
    justify-content: space-around;
    flex-wrap: wrap;
    gap: 12px;
  }
  .stat-item { text-align: center; min-width: 80px; }
  .stat-item .label { font-size: 11px; color: #8892a8; text-transform: uppercase; letter-spacing: 0.5px; }
  .stat-item .value { font-size: 22px; font-weight: 700; margin-top: 2px; }
  .stat-item .value.green { color: #00c853; }
  .stat-item .value.red { color: #ff1744; }
  .stat-item .value.amber { color: #ffab00; }
  .stat-item .value.blue { color: #4fc3f7; }
  .stat-item .value.purple { color: #b388ff; }

  /* Fixture Grid */
  .fixture-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin-bottom: 20px;
  }
  @media (max-width: 1100px) { .fixture-grid { grid-template-columns: repeat(2, 1fr); } }
  @media (max-width: 600px) { .fixture-grid { grid-template-columns: 1fr; } }

  .fixture-card {
    background: #131a2b;
    border: 1px solid #1e2a45;
    border-radius: 12px;
    padding: 16px;
    transition: border-color 0.2s, transform 0.2s;
    position: relative;
  }
  .fixture-card:hover {
    border-color: #2a3a5c;
    transform: translateY(-2px);
  }
  .fixture-card .teams {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .fixture-card .teams .vs { color: #4a5568; font-weight: 400; font-size: 12px; }

  .fixture-card .prediction-info {
    font-size: 12px;
    color: #a0aec0;
    margin-bottom: 8px;
    line-height: 1.4;
  }
  .fixture-card .prediction-info .market { color: #4fc3f7; font-weight: 600; }
  .fixture-card .prediction-info .confidence { color: #b388ff; font-weight: 600; }
  .fixture-card .prediction-info .strength { font-weight: 600; }
  .fixture-card .prediction-info .strength.STRONG { color: #00c853; }
  .fixture-card .prediction-info .strength.MODERATE { color: #ffab00; }
  .fixture-card .prediction-info .strength.WEAK { color: #ff1744; }

  .no-prediction {
    font-size: 12px;
    color: #4a5568;
    font-style: italic;
    margin-bottom: 8px;
  }

  /* Gate Badges */
  .gates {
    display: flex;
    gap: 5px;
    margin-bottom: 10px;
    flex-wrap: wrap;
  }
  .gate {
    font-size: 10px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }
  .gate.pass {
    background: rgba(0, 200, 83, 0.15);
    color: #00c853;
    border: 1px solid rgba(0, 200, 83, 0.3);
  }
  .gate.fail {
    background: rgba(255, 23, 68, 0.15);
    color: #ff1744;
    border: 1px solid rgba(255, 23, 68, 0.3);
  }

  /* Result */
  .result {
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 700;
    text-align: center;
  }
  .result.win {
    background: rgba(0, 200, 83, 0.12);
    color: #00c853;
    border: 1px solid rgba(0, 200, 83, 0.25);
  }
  .result.loss {
    background: rgba(255, 23, 68, 0.12);
    color: #ff1744;
    border: 1px solid rgba(255, 23, 68, 0.25);
  }
  .result.pending {
    background: rgba(255, 171, 0, 0.12);
    color: #ffab00;
    border: 1px solid rgba(255, 171, 0, 0.25);
  }

  /* Two-column layout for bottom section */
  .bottom-section {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }
  @media (max-width: 900px) { .bottom-section { grid-template-columns: 1fr; } }

  /* Betting Slip Card */
  .betting-slip {
    background: #131a2b;
    border: 1px solid #1e2a45;
    border-radius: 12px;
    padding: 20px;
  }
  .betting-slip h2 {
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 14px;
    color: #ffab00;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .betting-slip h2::before { content: "\1F3B0"; }
  .slip-pick {
    background: #0d1224;
    border: 1px solid #1e2a45;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 10px;
  }
  .slip-pick .pick-teams { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
  .slip-pick .pick-market { font-size: 12px; color: #4fc3f7; }
  .slip-pick .pick-odds { font-size: 12px; color: #b388ff; }
  .slip-pick .pick-confidence { font-size: 11px; color: #8892a8; }
  .slip-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 12px;
    border-top: 1px solid #1e2a45;
    margin-top: 4px;
  }
  .slip-footer .total-odds { font-size: 16px; font-weight: 700; color: #00c853; }
  .slip-footer .stake { font-size: 13px; color: #8892a8; }
  .slip-empty {
    text-align: center;
    color: #4a5568;
    padding: 30px;
    font-size: 13px;
  }

  /* Gate Analytics */
  .gate-analytics {
    background: #131a2b;
    border: 1px solid #1e2a45;
    border-radius: 12px;
    padding: 20px;
  }
  .gate-analytics h2 {
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 14px;
    color: #4fc3f7;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .gate-analytics h2::before { content: "\1F4CA"; }
  .gate-bar-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
  }
  .gate-bar-label {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    min-width: 55px;
    color: #8892a8;
  }
  .gate-bar-track {
    flex: 1;
    height: 22px;
    background: #0d1224;
    border-radius: 6px;
    overflow: hidden;
    position: relative;
  }
  .gate-bar-fill {
    height: 100%;
    border-radius: 6px;
    transition: width 0.8s ease;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    padding-right: 6px;
    font-size: 10px;
    font-weight: 700;
    min-width: 30px;
  }
  .gate-bar-fill.high { background: linear-gradient(90deg, #00c853, #00e676); }
  .gate-bar-fill.med { background: linear-gradient(90deg, #ffab00, #ffc107); }
  .gate-bar-fill.low { background: linear-gradient(90deg, #ff1744, #ff5252); }

  /* Loading & Error states */
  .loading {
    text-align: center;
    padding: 60px 20px;
    color: #4a5568;
  }
  .loading .spinner {
    width: 40px;
    height: 40px;
    border: 3px solid #1e2a45;
    border-top-color: #00c853;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 0 auto 16px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .error-state {
    text-align: center;
    padding: 40px;
    color: #ff1744;
    background: rgba(255,23,68,0.08);
    border-radius: 12px;
    border: 1px solid rgba(255,23,68,0.2);
  }

  /* Footer */
  .footer {
    text-align: center;
    font-size: 11px;
    color: #2a3a5c;
    padding: 20px 0;
    border-top: 1px solid #1e2a45;
    margin-top: 20px;
  }
  .footer span { color: #00c853; }

  /* Scrollbar styling */
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: #0a0e17; }
  ::-webkit-scrollbar-thumb { background: #1e2a45; border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: #2a3a5c; }

  /* Status indicator */
  .status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 4px;
  }
  .status-dot.live { background: #00c853; box-shadow: 0 0 6px rgba(0,200,83,0.5); animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  .status-dot.offline { background: #4a5568; }
</style>
</head>
<body>
<div class="container">
  <!-- Header -->
  <div class="header" id="header">
    <div style="display:flex;align-items:center;gap:12px;">
      <h1>&#x1F3C6; VFL PREDICTION MONITOR</h1>
      <span class="regime-badge" id="regimeBadge">&#x1F4A1; --</span>
    </div>
    <div class="header-controls">
      <span style="font-size:11px;color:#8892a8;">SEASON</span>
      <select id="seasonSelect" onchange="onSeasonChange()">
        <option value="">Loading...</option>
      </select>
      <span style="font-size:11px;color:#8892a8;">MD</span>
      <select id="matchdaySelect" onchange="onMatchdayChange()">
        <option value="">--</option>
      </select>
      <span class="status-dot live" id="statusDot" title="Live"></span>
      <span style="font-size:10px;color:#4a5568;" id="refreshTime">--</span>
    </div>
  </div>

  <!-- Summary Bar -->
  <div class="summary-bar" id="summaryBar">
    <div class="stat-item">
      <div class="label">Total Picks</div>
      <div class="value blue" id="statPicks">--</div>
    </div>
    <div class="stat-item">
      <div class="label">Wins</div>
      <div class="value green" id="statWins">--</div>
    </div>
    <div class="stat-item">
      <div class="label">Losses</div>
      <div class="value red" id="statLosses">--</div>
    </div>
    <div class="stat-item">
      <div class="label">Win Rate</div>
      <div class="value" id="statWinRate">--</div>
    </div>
    <div class="stat-item">
      <div class="label">ROI</div>
      <div class="value purple" id="statROI">--</div>
    </div>
    <div class="stat-item">
      <div class="label">Pipeline</div>
      <div class="value" style="font-size:13px;color:#8892a8;" id="statPipeline">--</div>
    </div>
  </div>

  <!-- Fixture Grid -->
  <div id="fixtureGrid"><div class="loading"><div class="spinner"></div>Loading fixtures...</div></div>

  <!-- Bottom Section -->
  <div class="bottom-section">
    <!-- Virtual Betting Slip -->
    <div class="betting-slip" id="bettingSlip">
      <h2>Virtual Betting Slip</h2>
      <div class="slip-empty">Select a matchday to see virtual bets</div>
    </div>

    <!-- Gate Analytics -->
    <div class="gate-analytics" id="gateAnalytics">
      <h2>Gate Performance</h2>
      <div id="gateBars"></div>
    </div>
  </div>

  <div class="footer">VFL Empire &bull; <span>Certainty Oracle v3</span> &bull; Monitoring Mode &bull; No real betting</div>
</div>

<script>
// ─── State ──────────────────────────────────────────────────────────────────
let currentSeason = '';
let currentMatchday = '';
let autoRefreshInterval = null;

// ─── API Calls ──────────────────────────────────────────────────────────────
async function apiFetch(endpoint) {
  const resp = await fetch(endpoint);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return await resp.json();
}

// ─── Init ───────────────────────────────────────────────────────────────────
async function init() {
  try {
    // Load seasons + latest
    const [seasons, latest] = await Promise.all([
      apiFetch('/api/seasons'),
      apiFetch('/api/latest'),
    ]);

    const sel = document.getElementById('seasonSelect');
    sel.innerHTML = '';
    if (seasons.seasons && seasons.seasons.length > 0) {
      seasons.seasons.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        sel.appendChild(opt);
      });

      // Select latest season
      currentSeason = latest.season || seasons.seasons[seasons.seasons.length - 1];
      sel.value = currentSeason;

      // Load matchdays
      await loadMatchdays(currentSeason, latest.matchday);
    }

    // Load stats
    await loadStats();

    // Start auto-refresh every 30s
    autoRefreshInterval = setInterval(() => {
      loadMatchdays(currentSeason, currentMatchday);
      loadStats();
      updateRefreshTime();
    }, 30000);

    updateRefreshTime();
  } catch (err) {
    console.error('Init error:', err);
    document.getElementById('fixtureGrid').innerHTML =
      '<div class="error-state">&#x26A0;&#xFE0F; Failed to load dashboard: ' + err.message + '</div>';
  }
}

async function loadMatchdays(season, selectMd) {
  try {
    const data = await apiFetch('/api/matchdays?season=' + encodeURIComponent(season));
    const mdSel = document.getElementById('matchdaySelect');
    mdSel.innerHTML = '';
    if (data.matchdays && data.matchdays.length > 0) {
      data.matchdays.forEach(md => {
        const opt = document.createElement('option');
        opt.value = md;
        opt.textContent = 'Matchday ' + md;
        mdSel.appendChild(opt);
      });

      // Select requested or last
      const targetMd = selectMd || data.matchdays[data.matchdays.length - 1];
      if (mdSel.querySelector('option[value="' + targetMd + '"]')) {
        mdSel.value = targetMd;
      } else {
        mdSel.value = data.matchdays[data.matchdays.length - 1];
      }
      currentMatchday = mdSel.value;
    } else {
      mdSel.innerHTML = '<option value="">No matchdays</option>';
    }

    // Load fixtures
    await loadFixtures(season, currentMatchday);
  } catch (err) {
    console.error('loadMatchdays error:', err);
  }
}

async function loadFixtures(season, matchday) {
  const grid = document.getElementById('fixtureGrid');
  grid.innerHTML = '<div class="loading"><div class="spinner"></div>Loading fixtures...</div>';

  try {
    const data = await apiFetch(
      '/api/fixtures?season=' + encodeURIComponent(season) +
      '&matchday=' + encodeURIComponent(matchday)
    );

    // Update regime badge
    if (data.regime) {
      const badge = document.getElementById('regimeBadge');
      badge.textContent = '\u{1F4A1} ' + data.regime;
      const colors = { 'OFFENSIVE': '#00c853', 'DEFENSIVE': '#ff1744', 'STANDARD': '#ffab00' };
      badge.style.color = colors[data.regime] || '#4fc3f7';
    }

    renderFixtures(data);
    renderBettingSlip(data.virtual_bets);
    renderGateBars();
  } catch (err) {
    grid.innerHTML = '<div class="error-state">&#x26A0;&#xFE0F; Failed to load fixtures: ' + err.message + '</div>';
  }
}

async function loadStats() {
  try {
    const stats = await apiFetch('/api/stats');
    document.getElementById('statPicks').textContent = stats.total_picks || stats.total_predictions || 0;
    document.getElementById('statWins').textContent = stats.wins || 0;
    document.getElementById('statLosses').textContent = stats.losses || 0;

    const wrEl = document.getElementById('statWinRate');
    const wr = stats.win_rate || 0;
    wrEl.textContent = wr + '%';
    wrEl.className = 'value ' + (wr >= 60 ? 'green' : wr >= 45 ? 'amber' : 'red');

    const roiEl = document.getElementById('statROI');
    const roi = stats.roi || 0;
    roiEl.textContent = (roi >= 0 ? '+' : '') + roi + '%';
    roiEl.className = 'value ' + (roi >= 0 ? 'green' : 'red');

    document.getElementById('statPipeline').textContent = stats.pipeline || '--';

    // Render gate bars from stats
    if (stats.gate_rates) {
      renderGateBarsFromStats(stats.gate_rates);
    }

    // Regime badge update
    if (stats.regime) {
      const badge = document.getElementById('regimeBadge');
      badge.textContent = '\u{1F4A1} ' + stats.regime;
      const colors = { 'OFFENSIVE': '#00c853', 'DEFENSIVE': '#ff1744', 'STANDARD': '#ffab00' };
      badge.style.color = colors[stats.regime] || '#4fc3f7';
    }
  } catch (err) {
    console.error('loadStats error:', err);
  }
}

// ─── Render Functions ───────────────────────────────────────────────────────

function renderFixtures(data) {
  const grid = document.getElementById('fixtureGrid');
  const fixtures = data.fixtures || [];

  if (fixtures.length === 0) {
    grid.innerHTML = '<div class="error-state">No fixtures found for this matchday</div>';
    return;
  }

  let html = '';
  fixtures.forEach(f => {
    const pred = f.prediction;
    const result = f.result || { settled: false };
    const gates = f.gates;

    // Teams display
    const teamsHtml = '<span>' + escHtml(f.home) + '</span>' +
      '<span class="vs">vs</span>' +
      '<span>' + escHtml(f.away) + '</span>';

    // Prediction info
    let predHtml = '';
    if (pred && pred.market) {
      const strengthClass = pred.strength || '';
      predHtml = '<div class="prediction-info">' +
        '<span class="market">' + escHtml(pred.market) + '</span>' +
        ' @ <span class="confidence">' + (pred.odds || '--') + '</span>' +
        ' &middot; <span class="confidence">' + (pred.confidence || '--') + '%</span>' +
        (strengthClass ? ' &middot; <span class="strength ' + strengthClass + '">' + strengthClass + '</span>' : '') +
        '</div>';
    } else {
      predHtml = '<div class="no-prediction">No prediction available</div>';
    }

    // Gate badges
    let gatesHtml = '';
    if (gates) {
      const gateLabels = { 'h2h': 'H2H', 'form': 'Form', 'cluster': 'Clus', 'odds': 'Odds', 'regime': 'Reg' };
      gatesHtml = '<div class="gates">';
      Object.keys(gateLabels).forEach(k => {
        const status = gates[k] === 'PASS' ? 'pass' : 'fail';
        gatesHtml += '<span class="gate ' + status + '">' + gateLabels[k] + '</span>';
      });
      gatesHtml += '</div>';
    }

    // Result display
    let resultHtml = '';
    if (result.settled && result.won !== null) {
      const score = f.score || (result.home_goals + '-' + result.away_goals);
      if (result.won) {
        resultHtml = '<div class="result win">' + score + ' &#x2705;</div>';
      } else {
        resultHtml = '<div class="result loss">' + score + ' &#x274C;</div>';
      }
    } else if (result.settled && result.won === null) {
      const score = f.score || (result.home_goals + '-' + result.away_goals);
      resultHtml = '<div class="result pending">' + score + ' &#x1F7E1;</div>';
    } else if (result.settled) {
      const score = f.score || (result.home_goals + '-' + result.away_goals);
      resultHtml = '<div class="result pending">' + score + ' &#x1F7E1;</div>';
    } else {
      resultHtml = '<div class="result pending">&#x23F3; PENDING</div>';
    }

    // Tier info
    let tierHtml = '';
    if (f.home_tier !== null && f.home_tier !== undefined) {
      tierHtml = '<div style="font-size:10px;color:#4a5568;margin-bottom:6px;">' +
        'T' + f.home_tier + ' v T' + f.away_tier +
        (f.tier_over_pct !== null && f.tier_over_pct !== undefined ? ' &middot; ' + f.tier_over_pct + '% O1.5' : '') +
        '</div>';
    }

    html += '<div class="fixture-card">' +
      '<div class="teams">' + teamsHtml + '</div>' +
      tierHtml +
      predHtml +
      gatesHtml +
      resultHtml +
      '</div>';
  });

  grid.innerHTML = html;
}

function renderBettingSlip(virtualBets) {
  const slip = document.getElementById('bettingSlip');
  if (!virtualBets || !virtualBets.picks || virtualBets.picks.length === 0) {
    slip.innerHTML = '<h2>&#x1F3B0; Virtual Betting Slip</h2>' +
      '<div class="slip-empty">No active picks for this matchday</div>';
    return;
  }

  let html = '<h2>&#x1F3B0; Virtual Betting Slip</h2>';
  virtualBets.picks.forEach(p => {
    html += '<div class="slip-pick">' +
      '<div class="pick-teams">' + escHtml(p.home) + ' vs ' + escHtml(p.away) + '</div>' +
      '<div class="pick-market">' + escHtml(p.market) + '</div>' +
      '<div class="pick-odds">Odds: ' + p.odds + ' &middot; Confidence: ' + p.confidence + '%</div>' +
      '<div class="pick-confidence">Score: ' + p.score + ' &middot; ' + (p.strength || '') + '</div>' +
      '</div>';
  });

  const potentialReturn = (virtualBets.stake || 100) * (virtualBets.combined_odds || 1);
  html += '<div class="slip-footer">' +
    '<div><span class="stake">Stake: &#x20A6;' + (virtualBets.stake || 100).toFixed(2) + '</span></div>' +
    '<div><span class="total-odds">&#x2716; ' + (virtualBets.combined_odds || 1).toFixed(2) + '</span>' +
    ' <span class="stake">Returns: &#x20A6;' + potentialReturn.toFixed(2) + '</span></div>' +
    '</div>';

  slip.innerHTML = html;
}

function renderGateBars() {
  // If we already rendered from stats, skip
  if (document.getElementById('gateBars').children.length > 0) return;
}

function renderGateBarsFromStats(gateRates) {
  const bars = document.getElementById('gateBars');
  const labels = { 'h2h': 'H2H', 'form': 'Form', 'cluster': 'Cluster', 'odds': 'Odds', 'regime': 'Regime' };
  const colors = { 'h2h': '#4fc3f7', 'form': '#b388ff', 'cluster': '#ffab00', 'odds': '#00c853', 'regime': '#ff7043' };

  let html = '';
  Object.keys(labels).forEach(k => {
    const rate = gateRates[k] || 0;
    const barClass = rate >= 70 ? 'high' : (rate >= 40 ? 'med' : 'low');
    html += '<div class="gate-bar-row">' +
      '<div class="gate-bar-label">' + labels[k] + '</div>' +
      '<div class="gate-bar-track">' +
      '<div class="gate-bar-fill ' + barClass + '" style="width:' + rate + '%;background:' + colors[k] + ';">' +
      (rate >= 20 ? rate + '%' : '') +
      '</div>' +
      '</div>' +
      '<span style="font-size:12px;font-weight:600;min-width:40px;text-align:right;color:#8892a8;">' + rate + '%</span>' +
      '</div>';
  });
  bars.innerHTML = html;
}

// ─── Event Handlers ─────────────────────────────────────────────────────────
function onSeasonChange() {
  const sel = document.getElementById('seasonSelect');
  currentSeason = sel.value;
  if (currentSeason) {
    loadMatchdays(currentSeason, null);
  }
}

function onMatchdayChange() {
  const sel = document.getElementById('matchdaySelect');
  currentMatchday = sel.value;
  if (currentSeason && currentMatchday) {
    loadFixtures(currentSeason, currentMatchday);
  }
}

function updateRefreshTime() {
  const now = new Date();
  document.getElementById('refreshTime').textContent =
    now.toLocaleTimeString();
}

// ─── Utilities ──────────────────────────────────────────────────────────────
function escHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

// ─── Start ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>"""


# ─── HTTP Request Handler ────────────────────────────────────────────────────

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for the VFL Dashboard."""

    def log_message(self, format, *args):
        """Quiet logging — only log errors."""
        if args[0] not in ('200', '304'):
            super().log_message(format, *args)

    def _send_json(self, data, status=200):
        """Send a JSON response."""
        body = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        """Send an HTML response."""
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, message):
        """Send a JSON error response."""
        self._send_json({'error': message}, status)

    def do_GET(self):
        """Handle GET requests."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip('/')
        params = urllib.parse.parse_qs(parsed.query)

        # Serve the HTML dashboard at root
        if path == '' or path == '/':
            self._send_html(HTML_TEMPLATE)
            return

        # API routes
        handler = ROUTES.get(path)
        if handler:
            try:
                result = handler(params)
                self._send_json(result)
            except Exception as e:
                self._send_error(500, f'Internal error: {str(e)}')
            return

        # 404 for everything else
        self._send_error(404, f'Not found: {path}')


def run_server():
    """Start the dashboard server."""
    server = http.server.HTTPServer(('0.0.0.0', PORT), DashboardHandler)
    print(f"""
{'=' * 60}
  🏆 VFL PREDICTION MONITOR DASHBOARD
{'=' * 60}
  Server running at: http://localhost:{PORT}
  Data sources:
    Results DB: {RESULTS_DB}
    Odds DB:    {ODDS_DB}
    Predictions: {PREDICTIONS_FILE if os.path.exists(PREDICTIONS_FILE) else 'NOT FOUND'}
  API endpoints:
    GET /api/seasons
    GET /api/matchdays?season=VFLM%205113
    GET /api/fixtures?season=VFLM%205113&matchday=1
    GET /api/stats
    GET /api/latest
{'=' * 60}
  Press Ctrl+C to stop.
{'=' * 60}
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutting down server...')
        server.server_close()
        print('Server stopped.')


if __name__ == '__main__':
    run_server()
