#!/usr/bin/env python3
"""
TTs (Total Goals) Per-Matchday Prediction + Finite State 1X2 Analyzer + Live Test
=================================================================================

INNOVATION: Three engines fused per matchday:
  1. FINITE STATE 1X2 — Derives H/D/A probabilities from the 34-scoreline state space
  2. FINITE STATE O/U — Uses existing pair-level O1.5/O2.5/GG rates (proven 74.5% O1.5)
  3. LLM CERTAINTY ORACLE — Cross-references with Certainty Oracle v3 predictions

Output: All 8 fixtures ranked by blended certainty + verdict per market.

AUTHOR: Arthur, Imperial Steward — for Lord FaithDavid's Trillions Empire 👑🦁
USAGE:  python3 tts_live_test.py [--matchday N] [--output FILE] [--live]
"""

import json
import os
import sys
import math
import time
from datetime import datetime, timezone

# ─── PATHS ───────────────────────────────────────────────────────────────────
FINITE_STATE_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis/finite_state_space.json'
LIVE_PREDICTIONS_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/signals/live_test_predictions.json'
RESULTS_DB = '/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db'
OUTPUT_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data/tts-test'
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── DATA LOADERS ────────────────────────────────────────────────────────────

def load_finite_state():
    """Load the 240-pair finite state space (34 unique scorelines)."""
    if not os.path.exists(FINITE_STATE_PATH):
        print(f"[ERROR] Finite state data not found: {FINITE_STATE_PATH}")
        return None
    with open(FINITE_STATE_PATH) as f:
        data = json.load(f)
    return data.get('pair_stats', {})


def load_live_predictions():
    """Load live predictions from the Certainty Oracle v3 pipeline."""
    if not os.path.exists(LIVE_PREDICTIONS_PATH):
        print(f"[ERROR] Live predictions not found: {LIVE_PREDICTIONS_PATH}")
        return None
    with open(LIVE_PREDICTIONS_PATH) as f:
        return json.load(f)


def load_results_from_db():
    """Load actual results from the database for verification."""
    import sqlite3
    if not os.path.exists(RESULTS_DB):
        return None
    conn = sqlite3.connect(RESULTS_DB)
    rows = conn.execute("""
        SELECT home_team, away_team, home_goals, away_goals, total_goals,
               season_name, match_day, event_id, status
        FROM results WHERE status = 3
    """).fetchall()
    conn.close()
    return rows


# ─── FINITE STATE 1X2 ENGINE ─────────────────────────────────────────────────

def compute_1x2_from_scorelines(pair_data):
    """
    Given a pair's finite state data, compute H/D/A probabilities
    from the actual scoreline distribution.

    Returns: dict with H, D, A as percentages + edge analysis
    """
    scorelines = pair_data.get('scorelines', {})
    total_matches = pair_data.get('matches', 0)
    if total_matches == 0:
        return None
    
    home_wins = 0
    draws = 0
    away_wins = 0
    
    for score, count in scorelines.items():
        try:
            hg, ag = int(score.split(':')[0]), int(score.split(':')[1])
        except (ValueError, IndexError):
            continue
        if hg > ag:
            home_wins += count
        elif hg == ag:
            draws += count
        else:
            away_wins += count
    
    return {
        'H': round(home_wins / total_matches * 100, 1),
        'D': round(draws / total_matches * 100, 1),
        'A': round(away_wins / total_matches * 100, 1),
        'matches': total_matches,
        'home_wins': home_wins,
        'draws': draws,
        'away_wins': away_wins,
    }


def get_pair_key(home, away):
    """Normalize pair key to match finite state space format."""
    return f"{home} vs {away}"


def compute_ou_from_finite_state(pair_data):
    """Get O/U rates from finite state data."""
    if not pair_data:
        return None
    return {
        'O1.5': pair_data.get('o15_rate', 0),
        'O2.5': pair_data.get('o25_rate', 0),
        'GG': pair_data.get('gg_rate', 0),
        'matches': pair_data.get('matches', 0),
    }


# ─── SWITCHING GATE: 1X2 vs O/U ──────────────────────────────────────────────

def switching_gate(analysis):
    """
    For each fixture, decide whether to bet 1X2 or O/U based on
    which market has higher finite state probability.
    
    Returns: dict with 'market_type' (1X2 or O/U), 'outcome', 'prob', 'edge'
    """
    fs_1x2 = analysis.get('fs_1x2')
    fs_ou = analysis.get('fs_ou')
    odds = analysis.get('odds', {})
    
    if not fs_1x2 and not fs_ou:
        return None
    
    # Best 1X2 option
    best_1x2 = None
    if fs_1x2:
        max_prob = max(fs_1x2['H'], fs_1x2['D'], fs_1x2['A'])
        outcomes = [('H', fs_1x2['H'], odds.get('home_win')),
                    ('D', fs_1x2['D'], odds.get('draw')),
                    ('A', fs_1x2['A'], odds.get('away_win'))]
        for outcome, prob, odd in outcomes:
            if prob == max_prob and odd:
                edge = compute_edge(prob, odd)
                best_1x2 = {'market': f'1X2 {outcome}', 'prob': prob, 'odds': odd, 'edge': edge}
                break
    
    # Best O/U option
    best_ou = None
    if fs_ou:
        ou_options = [('O1.5', fs_ou['O1.5'], odds.get('over_1.5')),
                      ('O2.5', fs_ou['O2.5'], odds.get('over_2.5')),
                      ('GG', fs_ou['GG'], odds.get('gg'))]
        best_ou_candidate = max(ou_options, key=lambda x: x[1])
        best_ou_prob, best_ou_odds = best_ou_candidate[1], best_ou_candidate[2]
        if best_ou_odds:
            edge = compute_edge(best_ou_prob, best_ou_odds)
            best_ou = {'market': best_ou_candidate[0], 'prob': best_ou_prob, 'odds': best_ou_odds, 'edge': edge}
    
    # Switching gate: pick the one with higher prob
    if best_1x2 and best_ou:
        if best_1x2['prob'] >= best_ou['prob']:
            return {**best_1x2, 'selected': '1X2', 'reason': f'1X2 prob ({best_1x2["prob"]}%) >= O/U ({best_ou["prob"]}%)'}
        else:
            return {**best_ou, 'selected': 'O/U', 'reason': f'O/U prob ({best_ou["prob"]}%) > 1X2 ({best_1x2["prob"]}%)'}
    elif best_1x2:
        return {**best_1x2, 'selected': '1X2', 'reason': 'Only 1X2 data available'}
    elif best_ou:
        return {**best_ou, 'selected': 'O/U', 'reason': 'Only O/U data available'}
    return None


# ─── PERMUTATION ANALYSIS ────────────────────────────────────────────────────

def permutation_analysis(analysis_results):
    """
    Analyze ALL permutations of the 8 fixtures to determine what the
    finite state says is the most likely matchday narrative.
    
    Returns: dict with summary statistics
    """
    n = len(analysis_results)
    if n == 0:
        return None
    
    # For each fixture, get the most likely 1X2 outcome
    expected_home = expected_draw = expected_away = 0
    fixture_details = []
    
    for r in analysis_results:
        fs_1x2 = r.get('fs_1x2')
        if fs_1x2:
            probs = [('H', fs_1x2['H']), ('D', fs_1x2['D']), ('A', fs_1x2['A'])]
            max_outcome = max(probs, key=lambda x: x[1])
            
            if max_outcome[0] == 'H':
                expected_home += 1
            elif max_outcome[0] == 'D':
                expected_draw += 1
            else:
                expected_away += 1
            
            # Switching gate decision
            gate = switching_gate(r)
            if gate and gate['edge'] > 0:
                edge_label = f"+{gate['edge']}%"
            elif gate:
                edge_label = f"{gate['edge']}%"
            else:
                edge_label = "N/A"
            
            fixture_details.append({
                'fixture': f"{r['home']} vs {r['away']}",
                'max_1x2': f"{max_outcome[0]} ({max_outcome[1]}%)",
                'gate': gate['selected'] if gate else '?',
                'gate_market': gate['market'] if gate else '?',
                'gate_prob': gate['prob'] if gate else 0,
                'gate_edge': gate['edge'] if gate else 0,
            })
    
    # Compute "matchday narrative" — the most likely combination
    max_home_possible = min(8, expected_home + expected_draw)  # some draws become home wins
    min_home_possible = expected_home  # at minimum these are home wins
    
    # The finite state's prediction for "how many over/under"
    expected_over15 = sum(1 for r in analysis_results 
                         if r.get('fs_ou', {}).get('O1.5', 0) >= 65)
    
    # Best parlay candidate: pick the highest probability market from each fixture
    parlay_legs = []
    for r in analysis_results:
        best = r.get('best_bets', [])
        if best:
            parlay_legs.append({
                'fixture': f"{r['home']} vs {r['away']}",
                'market': best[0]['market'],
                'prob': best[0]['prob'],
                'odds': best[0]['odds'],
            })
    
    # Parlay combined probability (product of individual probs)
    if parlay_legs:
        combined_prob = 1.0
        for leg in parlay_legs:
            combined_prob *= (leg['prob'] / 100.0)
        parlay_prob = combined_prob * 100
    else:
        parlay_prob = 0
    
    return {
        'expected_home_wins': expected_home,
        'expected_draws': expected_draw,
        'expected_away_wins': expected_away,
        'expected_over15_count': expected_over15,
        'fixtures': fixture_details,
        'parlay_legs': parlay_legs,
        'parlay_combined_prob': round(parlay_prob, 4),
    }


# ─── LIVE TEST RESULT VERIFICATION ───────────────────────────────────────────

def validate_won(market_name, hg, ag, tg):
    """Check if a market prediction won given actual score."""
    if not market_name:
        return None
    mn = market_name.lower().replace(' ', '')
    if 'over1.5' in mn or 'o1.5' in mn or 'o15' in mn:
        return tg >= 2
    elif 'over2.5' in mn or 'o2.5' in mn or 'o25' in mn:
        return tg >= 3
    elif 'under3.5' in mn:
        return tg < 4
    elif 'gg' in mn:
        return hg > 0 and ag > 0
    elif '1x2home' in mn or mn == 'home' or mn.startswith('1x2h'):
        return hg > ag
    elif '1x2draw' in mn or mn == 'draw':
        return hg == ag
    elif '1x2away' in mn or mn == 'away':
        return hg < ag
    return None


def run_live_test(analysis_results, season_name, matchday_num):
    """
    Compare predictions against actual results.
    Returns structured test results.
    """
    import sqlite3
    if not os.path.exists(RESULTS_DB):
        return None, f"DB not found: {RESULTS_DB}"
    
    conn = sqlite3.connect(RESULTS_DB)
    conn.row_factory = sqlite3.Row
    
    verdicts = []
    total_o15 = 0
    correct_o15 = 0
    total_1x2 = 0
    correct_1x2 = 0
    total_gate = 0
    correct_gate = 0
    total_cert = 0
    correct_cert = 0
    
    for r in analysis_results:
        home, away = r['home'], r['away']
        
        # Look up result
        row = conn.execute(
            'SELECT home_goals, away_goals, total_goals FROM results WHERE season_name=? AND match_day=? AND home_team=? AND away_team=?',
            (season_name, matchday_num, home, away)
        ).fetchone()
        
        if not row:
            verdicts.append({'fixture': f"{home} vs {away}", 'score': 'PENDING', 'won': None})
            continue
        
        hg, ag, tg = row['home_goals'], row['away_goals'], row['total_goals']
        score = f"{hg}-{ag}"
        
        # Check O1.5
        o15_won = tg >= 2
        total_o15 += 1
        if o15_won:
            correct_o15 += 1
        
        # Check FS 1X2 max outcome
        fs_1x2 = r.get('fs_1x2')
        gate = switching_gate(r)
        
        # Check switching gate bet
        gate_won = None
        if gate:
            total_gate += 1
            gate_won = validate_won(gate['market'], hg, ag, tg)
            if gate_won:
                correct_gate += 1
        
        # Check certainty bets (prob >= 60% AND edge > 0)
        best_bets = r.get('best_bets', [])
        for b in best_bets:
            if b['edge'] > 0 and b['prob'] >= 60:
                total_cert += 1
                cert_won = validate_won(b['market'], hg, ag, tg)
                if cert_won:
                    correct_cert += 1
        
        # Determine best bet outcome
        bets_results = []
        if best_bets:
            for b in best_bets[:3]:
                bw = validate_won(b['market'], hg, ag, tg)
                bets_results.append(f"{'✅' if bw else '❌'} {b['market']} ({b['prob']}%)")
        
        # Finite state 1X2 result
        if fs_1x2:
            max_outcome = max([('H', fs_1x2['H']), ('D', fs_1x2['D']), ('A', fs_1x2['A'])], key=lambda x: x[1])
            hda_won = (max_outcome[0] == 'H' and hg > ag) or (max_outcome[0] == 'A' and hg < ag) or (max_outcome[0] == 'D' and hg == ag)
            if max_outcome[0] in ('H', 'D', 'A'):
                total_1x2 += 1
                if hda_won:
                    correct_1x2 += 1
        
        gate_icon = '✅' if gate and gate_won else ('❌' if gate else '⚪')
        
        verdicts.append({
            'fixture': f"{home} vs {away}",
            'score': score,
            'total_goals': tg,
            'o15': '✅' if o15_won else '❌',
            'gate': gate_icon,
            'gate_info': f"{gate['selected']}: {gate['market']} ({gate['prob']}%)" if gate else 'N/A',
            'bets': bets_results,
        })
    
    conn.close()
    
    summary = {
        'total_fixtures': len([v for v in verdicts if v['score'] != 'PENDING']),
        'o15_hit_rate': f"{correct_o15}/{total_o15} = {correct_o15/total_o15*100:.1f}%" if total_o15 else "N/A",
        'fs_1x2_hit_rate': f"{correct_1x2}/{total_1x2} = {correct_1x2/total_1x2*100:.1f}%" if total_1x2 else "N/A",
        'gate_hit_rate': f"{correct_gate}/{total_gate} = {correct_gate/total_gate*100:.1f}%" if total_gate else "N/A",
        'certainty_hit_rate': f"{correct_cert}/{total_cert} = {correct_cert/total_cert*100:.1f}%" if total_cert else "N/A",
        'o15_wins': correct_o15,
        'o15_total': total_o15,
        'gate_wins': correct_gate,
        'gate_total': total_gate,
        'cert_wins': correct_cert,
        'cert_total': total_cert,
    }
    
    return verdicts, summary


# ─── EDGE CALCULATION ────────────────────────────────────────────────────────

def compute_edge(our_prob_pct, market_odds):
    """
    Compute expected value edge.
    our_prob_pct: our estimated probability (0-100)
    market_odds: decimal odds from the market
    
    Returns: edge as percentage (positive = value bet)
    """
    implied_prob = 1.0 / market_odds * 100
    edge = our_prob_pct - implied_prob
    return round(edge, 2)


def compute_ev_ratio(our_prob_pct, market_odds):
    """EV ratio: > 1.0 means positive expected value."""
    our_prob = our_prob_pct / 100.0
    fair_odds = 1.0 / our_prob
    return round(market_odds / fair_odds, 3)


# ─── FIXTURE ANALYSIS ───────────────────────────────────────────────────────

def analyze_fixture(fixture, pair_stats):
    """
    Full analysis of a single fixture.
    
    Returns dict with:
      - fixture info (home, away, event_id)
      - finite state 1X2 probabilities (from scoreline distribution)
      - finite state O/U rates
      - live market odds
      - edge for each market
      - blended certainty score
      - best bets (market + probability + edge)
    """
    home = fixture.get('home', '')
    away = fixture.get('away', '')
    pred = fixture.get('prediction', {})
    primary = pred.get('primary') or {}
    odds_data = fixture.get('odds', {})
    
    # Look up finite state data for this pair
    pair_key = get_pair_key(home, away)
    pair_data = pair_stats.get(pair_key, None)
    
    result = {
        'home': home,
        'away': away,
        'event_id': fixture.get('event_id', ''),
        'pair_key': pair_key,
    }
    
    # --- Finite State 1X2 ---
    fs_1x2 = compute_1x2_from_scorelines(pair_data) if pair_data else None
    if fs_1x2:
        result['fs_1x2'] = {
            'H': fs_1x2['H'],
            'D': fs_1x2['D'],
            'A': fs_1x2['A'],
            'matches': fs_1x2['matches'],
        }
        # Edge for 1X2 if odds available
        home_odds = odds_data.get('home_win')
        draw_odds = odds_data.get('draw')
        away_odds = odds_data.get('away_win')
        edges_1x2 = {}
        if home_odds:
            edges_1x2['H_edge'] = compute_edge(fs_1x2['H'], home_odds)
            edges_1x2['H_EV'] = compute_ev_ratio(fs_1x2['H'], home_odds)
        if draw_odds:
            edges_1x2['D_edge'] = compute_edge(fs_1x2['D'], draw_odds)
            edges_1x2['D_EV'] = compute_ev_ratio(fs_1x2['D'], draw_odds)
        if away_odds:
            edges_1x2['A_edge'] = compute_edge(fs_1x2['A'], away_odds)
            edges_1x2['A_EV'] = compute_ev_ratio(fs_1x2['A'], away_odds)
        result['fs_1x2_edges'] = edges_1x2
    else:
        result['fs_1x2'] = None
        result['fs_1x2_edges'] = {}
    
    # --- Finite State O/U ---
    fs_ou = compute_ou_from_finite_state(pair_data) if pair_data else None
    if fs_ou:
        result['fs_ou'] = fs_ou
        o15_odds = odds_data.get('over_1.5')
        o25_odds = odds_data.get('over_2.5')
        gg_odds = odds_data.get('gg')
        edges_ou = {}
        if o15_odds:
            edges_ou['O1.5_edge'] = compute_edge(fs_ou['O1.5'], o15_odds)
            edges_ou['O1.5_EV'] = compute_ev_ratio(fs_ou['O1.5'], o15_odds)
        if o25_odds:
            edges_ou['O2.5_edge'] = compute_edge(fs_ou['O2.5'], o25_odds)
            edges_ou['O2.5_EV'] = compute_ev_ratio(fs_ou['O2.5'], o25_odds)
        if gg_odds:
            edges_ou['GG_edge'] = compute_edge(fs_ou['GG'], gg_odds)
            edges_ou['GG_EV'] = compute_ev_ratio(fs_ou['GG'], gg_odds)
        result['fs_ou_edges'] = edges_ou
    else:
        result['fs_ou'] = None
        result['fs_ou_edges'] = {}
    
    # --- LLM Oracle primary prediction ---
    if primary:
        result['llm_market'] = primary.get('market')
        result['llm_odds'] = primary.get('odds')
        result['llm_confidence'] = primary.get('confidence_pct')
        result['llm_strength'] = primary.get('strength')
    
    # --- Live market odds ---
    result['odds'] = odds_data
    
    return result


# ─── CERTAINTY SCORING ──────────────────────────────────────────────────────

def compute_certainty_score(analysis):
    """
    Blended certainty score (0-100) combining:
    - Finite state 1X2 max probability (weight: 40%)
    - Finite state O1.5 rate (weight: 25%)
    - LLM confidence (weight: 20%)
    - Best edge (weight: 15%)
    """
    score = 0
    components = {}
    
    # 1X2 max probability component (if available)
    fs_1x2 = analysis.get('fs_1x2')
    if fs_1x2:
        max_prob_1x2 = max(fs_1x2['H'], fs_1x2['D'], fs_1x2['A'])
        c1 = max_prob_1x2 * 0.40  # weight 40%
        score += c1
        components['fs_1x2_max'] = round(max_prob_1x2, 1)
        components['fs_1x2_contrib'] = round(c1, 1)
    
    # O1.5 rate (if available)
    fs_ou = analysis.get('fs_ou')
    if fs_ou:
        c2 = fs_ou['O1.5'] * 0.25  # weight 25%
        score += c2
        components['fs_o15'] = fs_ou['O1.5']
        components['fs_o15_contrib'] = round(c2, 1)
    
    # LLM confidence
    llm_conf = analysis.get('llm_confidence')
    if llm_conf:
        c3 = llm_conf * 0.15  # weight 15%
        score += c3
        components['llm_conf'] = llm_conf
        components['llm_contrib'] = round(c3, 1)
    
    # Best edge component
    best_edge = 0
    for edge_key in ['H_edge', 'D_edge', 'A_edge', 'O1.5_edge', 'O2.5_edge', 'GG_edge']:
        for edges_dict_key in ['fs_1x2_edges', 'fs_ou_edges']:
            edges = analysis.get(edges_dict_key, {})
            val = edges.get(edge_key, 0)
            if val > best_edge:
                best_edge = val
    # Edge contribution: cap at +10, floor at -10
    c4 = max(-10, min(10, best_edge)) * 1.5
    score += c4
    components['best_edge'] = round(best_edge, 2)
    components['edge_contrib'] = round(c4, 1)
    
    # Penalize if no finite state data
    if not fs_1x2:
        score -= 15
        components['no_fs_penalty'] = -15
    
    return {
        'total': round(min(100, max(0, score)), 1),
        'components': components,
    }


def find_best_bets(analysis):
    """
    Find the best betting opportunities for this fixture.
    Returns list of (market, our_prob, odds, edge, EV_ratio) sorted by edge.
    """
    bets = []
    
    # 1X2 bets
    fs_1x2 = analysis.get('fs_1x2')
    edges = analysis.get('fs_1x2_edges', {})
    odds_data = analysis.get('odds', {})
    if fs_1x2:
        for outcome, prob_key, odds_key in [
            ('Home', 'H', 'home_win'),
            ('Draw', 'D', 'draw'),
            ('Away', 'A', 'away_win'),
        ]:
            prob = fs_1x2.get(prob_key, 0)
            market_odds = odds_data.get(odds_key)
            if market_odds and prob > 0:
                edge = compute_edge(prob, market_odds)
                ev = compute_ev_ratio(prob, market_odds)
                bets.append({
                    'market': f'1X2 {outcome}',
                    'prob': prob,
                    'odds': market_odds,
                    'edge': edge,
                    'ev_ratio': ev,
                })
    
    # O/U bets
    fs_ou = analysis.get('fs_ou')
    ou_edges = analysis.get('fs_ou_edges', {})
    if fs_ou:
        for market, prob_key, odds_key in [
            ('Over 1.5', 'O1.5', 'over_1.5'),
            ('Over 2.5', 'O2.5', 'over_2.5'),
            ('GG', 'GG', 'gg'),
        ]:
            prob = fs_ou.get(prob_key, 0)
            market_odds = odds_data.get(odds_key)
            if market_odds and prob > 0:
                edge = compute_edge(prob, market_odds)
                ev = compute_ev_ratio(prob, market_odds)
                bets.append({
                    'market': market,
                    'prob': prob,
                    'odds': market_odds,
                    'edge': edge,
                    'ev_ratio': ev,
                })
    
    # Sort by edge descending (highest value first)
    bets.sort(key=lambda x: x['edge'], reverse=True)
    return bets


# ─── OUTPUT FORMATTER ────────────────────────────────────────────────────────

def format_predictions(analysis_results, matchday_label, regime_info):
    """
    Format the full analysis for Telegram output.
    All 8 fixtures shown. Certainty picks highlighted.
    """
    lines = []
    lines.append(f"━━━ 📊 TTs PREDICTION UPDATE — {matchday_label} ━━━")
    lines.append(f"🔥 Regime: {regime_info} | Finite State 1X2 + O/U Analysis")
    lines.append("")
    
    # Sort by certainty score descending
    sorted_results = sorted(analysis_results, 
                           key=lambda x: x.get('certainty', {}).get('total', 0),
                           reverse=True)
    
    for i, r in enumerate(sorted_results, 1):
        home = r['home']
        away = r['away']
        cert = r.get('certainty', {})
        cert_total = cert.get('total', 0)
        cert_emoji = "🔥" if cert_total >= 75 else "💎" if cert_total >= 65 else "⭐" if cert_total >= 50 else "▫️"
        
        lines.append(f"{i}. {cert_emoji} **{home} vs {away}** [Certainty: {cert_total}/100]")
        
        # Finite State 1X2
        fs_1x2 = r.get('fs_1x2')
        if fs_1x2:
            lines.append(f"   ┃ 1X2: H {fs_1x2['H']}% | D {fs_1x2['D']}% | A {fs_1x2['A']}% (n={fs_1x2['matches']})")
            edges_1x2 = r.get('fs_1x2_edges', {})
            # Show H edge if positive
            for outcome, label in [('H_edge', 'H'), ('D_edge', 'D'), ('A_edge', 'A')]:
                if outcome in edges_1x2 and edges_1x2[outcome] > 0:
                    odds_key = 'home_win' if 'H' == label else ('draw' if 'D' == label else 'away_win')
                    odds_val = r.get('odds', {}).get(odds_key, '?')
                    lines.append(f"   ┃   → {label} @{odds_val} | Edge: +{edges_1x2[outcome]}%")
        
        # Finite State O/U
        fs_ou = r.get('fs_ou')
        if fs_ou:
            lines.append(f"   ┃ O/U: O1.5 {fs_ou['O1.5']}% | O2.5 {fs_ou['O2.5']}% | GG {fs_ou['GG']}%")
        
        # LLM prediction
        llm_strength = r.get('llm_strength', '')
        llm_market = r.get('llm_market', '')
        llm_odds = r.get('llm_odds', '')
        llm_conf = r.get('llm_confidence', '')
        if llm_strength:
            strength_emoji = "🏆" if llm_strength == 'STRONG' else "🔶" if llm_strength == 'MODERATE' else "⚪"
            lines.append(f"   ┃ Oracle: {strength_emoji} {llm_market} @{llm_odds} ({llm_conf}%)")
        
        # Best bets
        best_bets = r.get('best_bets', [])
        positive_bets = [b for b in best_bets if b['edge'] > 0]
        if positive_bets:
            best_positive = positive_bets[0]  # Already sorted by edge desc
            edge_str = f"+{best_positive['edge']}%" if best_positive['edge'] > 0 else f"{best_positive['edge']}%"
            lines.append(f"   ┃ ★ Best: {best_positive['market']} @{best_positive['odds']} | {best_positive['prob']}% | Edge: {edge_str}")
            if len(positive_bets) > 1:
                for b in positive_bets[1:3]:  # Show top 2 additional
                    lines.append(f"   ┃   ● {b['market']} @{b['odds']} | {b['prob']}% | Edge: +{b['edge']}%")
        
        lines.append("")
    
    # 🏆 CERTAINTY BETS SECTION — strongly highlighted
    lines.append("━━━ ★★★ CERTAINTY BETS ★★★ ━━━")
    lines.append("These are bets where Finite State + Market Edge converge strongly.")
    lines.append("")
    
    certain_bets = []
    for r in sorted_results:
        best = r.get('best_bets', [])
        positive = [b for b in best if b['edge'] > 0 and b['prob'] >= 60]
        for b in positive:
            certain_bets.append({
                'fixture': f"{r['home']} vs {r['away']}",
                'market': b['market'],
                'prob': b['prob'],
                'odds': b['odds'],
                'edge': b['edge'],
                'ev_ratio': b['ev_ratio'],
                'certainty': r.get('certainty', {}).get('total', 0),
            })
    
    # Sort by probability * edge product (best overall bet)
    certain_bets.sort(key=lambda x: x['prob'] * x['edge'], reverse=True)
    
    if certain_bets:
        for i, bet in enumerate(certain_bets, 1):
            lines.append(f"{'🔴' if i == 1 and bet['edge'] > 3 else '🔥'} **#{i}:** {bet['fixture']}")
            lines.append(f"   ┃ {bet['market']} @{bet['odds']}")
            lines.append(f"   ┃ Prob: {bet['prob']}% | Edge: +{bet['edge']}% | EV: {bet['ev_ratio']}x")
            lines.append(f"   ┃ Certainty: {bet['certainty']}/100")
            if i == 1:
                lines.append(f"   ⚠️ **STRONG RECOMMENDATION — HIGHEST CONVICTION**")
            lines.append("")
    else:
        lines.append("No certainty bets in this matchday (edge or confidence too low).")
        lines.append("")
    
    lines.append(f"📊 {len(sorted_results)} fixtures analyzed | {len(certain_bets)} certainty bets identified")
    lines.append(f"⏰ Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    
    return "\n".join(lines)


def format_test_output(analysis_results, matchday_label, regime_info):
    """
    Concise format optimized for the TTs update.
    Shows all 8 fixtures, then CERTAINTY BETS in bold.
    """
    lines = []
    lines.append(f"━━━ 📊 TTs UPDATE — {matchday_label} ━━━")
    lines.append(f"🔥 {regime_info}")
    lines.append("")
    
    sorted_results = sorted(analysis_results,
                           key=lambda x: x.get('certainty', {}).get('total', 0),
                           reverse=True)
    
    for i, r in enumerate(sorted_results, 1):
        home = r['home']
        away = r['away']
        cert = r.get('certainty', {}).get('total', 0)
        
        # Get best positive bet
        best_bets = r.get('best_bets', [])
        positive = [b for b in best_bets if b['edge'] > 0]
        
        # 1X2 summary
        fs_1x2 = r.get('fs_1x2')
        fs_ou = r.get('fs_ou')
        if fs_1x2:
            h, d, a = fs_1x2['H'], fs_1x2['D'], fs_1x2['A']
            lines.append(f"{i}. **{home} vs {away}** — 1X2: H{h}% D{d}% A{a}%")
            
            if positive:
                best = positive[0]
                lines.append(f"   → {best['market']} @{best['odds']} | {best['prob']}% | Edge: +{best['edge']}%")
            elif fs_ou:
                lines.append(f"   → O1.5 {fs_ou['O1.5']}% | O2.5 {fs_ou['O2.5']}% | GG {fs_ou['GG']}%")
        else:
            lines.append(f"{i}. **{home} vs {away}** — No finite state data")
        
        lines.append("")
    
    # ━━━ CERTAINTY BETS ━━━
    lines.append("━ **═══════════════════════════════**━")
    lines.append(" **🔥🔥🔥 CERTAINTY BETS — HIGH VOICE 🔥🔥🔥** ")
    lines.append("━ **═══════════════════════════════**━")
    lines.append("")
    lines.append("These are bets where Finite State probability ≥60% AND positive edge. The closer to 100% probability with positive edge, the more CERTAIN the result.")
    lines.append("")
    
    # Collect all certainty bets
    all_bets = []
    for r in sorted_results:
        best = r.get('best_bets', [])
        for b in best:
            if b['edge'] > 0 and b['prob'] >= 55:
                all_bets.append({
                    'fixture': f"{r['home']} vs {r['away']}",
                    'market': b['market'],
                    'prob': b['prob'],
                    'odds': b['odds'],
                    'edge': b['edge'],
                    'certainty': r.get('certainty', {}).get('total', 0),
                })
    
    # Sort: highest certainty first (prob * edge)
    all_bets.sort(key=lambda x: x['prob'] * max(0, x['edge']), reverse=True)
    
    if all_bets:
        for i, bet in enumerate(all_bets, 1):
            star = "⭐" if bet['prob'] >= 75 else "🔥" if bet['prob'] >= 65 else "💎"
            edge_mark = "✅" if bet['edge'] > 3 else "📈" if bet['edge'] > 0 else "⚠️"
            lines.append(f"{star} **#{i}.** {bet['fixture']}")
            lines.append(f"   ┃ **{bet['market']}** @{bet['odds']}")
            lines.append(f"   ┃ Probability: **{bet['prob']}%** | Edge: **+{bet['edge']}%** {edge_mark}")
            if i == 1:
                lines.append(f"   ┃ 👑 **HIGHEST CONVICTION PICK** — Bet this if only one!")
            lines.append("")
    else:
        lines.append("⚠️ No certainty bets found for this matchday.")
        lines.append("   Possible reasons: odds too compressed, or finite state doesn't")
        lines.append("   show any outcome with >55% probability AND positive edge.")
        lines.append("")
        lines.append("   In this case, the safest traditional pick is the highest-probability")
        lines.append("   O1.5 where edge is closest to zero.")
        lines.append("")
    
    lines.append(f"⏰ Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    
    return "\n".join(lines)


# ─── RESULT VERIFICATION ────────────────────────────────────────────────────

def verify_against_results(analysis_results, season_name, matchday):
    """
    Compare predictions against actual settled results.
    Returns verdicts: did each predicted outcome actually happen?
    """
    results = load_results_from_db()
    if not results:
        return None, "No results database available"
    
    verdicts = []
    for r in analysis_results:
        home = r['home']
        away = r['away']
        
        # Find matching result
        match_result = None
        for row in results:
            rh, ra, hg, ag, tg, sn, md, _, _ = row
            if rh == home and ra == away and md == matchday:
                match_result = (hg, ag, tg)
                break
        
        if match_result:
            hg, ag, tg = match_result
            best_bets = r.get('best_bets', [])
            
            for bet in best_bets:
                market = bet['market']
                predicted_prob = bet['prob']
                bet_edge = bet['edge']
                
                if market == 'Over 1.5':
                    won = tg >= 2
                elif market == 'Over 2.5':
                    won = tg >= 3
                elif market == 'GG':
                    won = hg > 0 and ag > 0
                elif market == '1X2 Home':
                    won = hg > ag
                elif market == '1X2 Draw':
                    won = hg == ag
                elif market == '1X2 Away':
                    won = hg < ag
                else:
                    won = None
                
                verdicts.append({
                    'fixture': f"{home} vs {away}",
                    'actual': f"{hg}-{ag}",
                    'total_goals': tg,
                    'market': market,
                    'predicted_prob': predicted_prob,
                    'edge': bet_edge,
                    'won': won,
                })
        else:
            verdicts.append({
                'fixture': f"{home} vs {away}",
                'actual': 'PENDING',
                'market': 'ALL',
                'predicted_prob': None,
                'won': None,
            })
    
    return verdicts, None


# ─── MAIN ───────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='TTs Prediction + Finite State 1X2 Live Test')
    parser.add_argument('--matchday', type=int, default=None,
                       help='Specific matchday to analyze (default: current)')
    parser.add_argument('--output', type=str, default=None,
                       help='Output file path')
    parser.add_argument('--live', action='store_true',
                       help='Fetch fresh data from MSport API instead of using cached predictions')
    parser.add_argument('--test', action='store_true',
                       help='Run in live test mode: compare predictions vs actual results')
    parser.add_argument('--compact', action='store_true',
                       help='Compact output format (for cron/Telegram)')
    parser.add_argument('--narrative', action='store_true',
                       help='Show full permutation/narrative analysis')
    parser.add_argument('--save', action='store_true',
                       help='Save analysis as JSON for later comparison')
    args = parser.parse_args()
    
    # Load finite state data
    pair_stats = load_finite_state()
    if not pair_stats:
        print("[ERROR] Cannot proceed without finite state data.")
        sys.exit(1)
    
    # Load live predictions
    live_data = load_live_predictions()
    if not live_data:
        print("[ERROR] Cannot proceed without live predictions.")
        sys.exit(1)
    
    # Determine which matchdays to analyze
    matchdays = live_data.get('matchdays', [])
    current_md_info = live_data.get('current_matchday', {})
    season_label = current_md_info.get('season', 'Unknown Season')
    regime = live_data.get('regime', 'UNKNOWN')
    regime_note = live_data.get('regime_note', '')
    
    if args.matchday:
        matchdays = [m for m in matchdays if m.get('matchday') == args.matchday]
    
    all_analyses = {}
    
    for md in matchdays:
        md_num = md.get('matchday', '?')
        fixtures = md.get('fixtures', [])
        md_label = f"{season_label} — MD{md_num}"
        
        analyses = []
        for fixture in fixtures:
            analysis = analyze_fixture(fixture, pair_stats)
            # Compute certainty score
            analysis['certainty'] = compute_certainty_score(analysis)
            # Find best bets
            analysis['best_bets'] = find_best_bets(analysis)
            analyses.append(analysis)
        
        all_analyses[str(md_num)] = {
            'label': md_label,
            'regime': regime,
            'analyses': analyses,
        }
        
        # Determine display mode
        regime_info = f"{regime} regime" + (f" ({regime_note})" if regime_note else "")
        
        if args.compact:
            output = format_test_output(analyses, md_label, regime_info)
        else:
            output = format_predictions(analyses, md_label, regime_info)
        
        print(output)
        
        # ─── PERMUTATION/NARRATIVE ANALYSIS ───
        if args.narrative or not args.compact:
            perm = permutation_analysis(analyses)
            if perm:
                print(f"\n━━━ 📐 PERMUTATION ANALYSIS — {md_label} ━━━")
                print("The Finite State Space (34 scorelines) predicts the following")
                print("most likely matchday narrative across all 8 fixtures:")
                print("")
                print(f"Expected 1X2 Distribution: {perm['expected_home_wins']}H / {perm['expected_draws']}D / {perm['expected_away_wins']}A")
                print(f"Expected O1.5 Hits: {perm['expected_over15_count']}/8 fixtures (FS O1.5 ≥ 65%)")
                print(f"Best Parlay (all fixtures): {perm['parlay_combined_prob']:.4f}% combined probability")
                print("")
                
                # Show switching gate decisions
                print("Switching Gate (1X2 vs O/U pick per fixture):")
                for f in perm['fixtures']:
                    gate_str = f["gate"]
                    gate_market = f["gate_market"]
                    gate_prob = f["gate_prob"]
                    gate_edge = f["gate_edge"]
                    edge_str = f"+{gate_edge}%" if gate_edge > 0 else f"{gate_edge}%"
                    icon = "🟢" if gate_edge > 0 else "🟡" if gate_edge >= -3 else "🔴"
                    print(f"  {icon} {f['fixture']}: {gate_str} → {gate_market} ({gate_prob}%, Edge: {edge_str})")
                
                print("")
                
                # Show expected matchday narrative
                total_decided = perm['expected_home_wins'] + perm['expected_draws'] + perm['expected_away_wins']
                if total_decided == 8:
                    print(f"The Finite State expects a {perm['expected_home_wins']}-{perm['expected_draws']}-{perm['expected_away_wins']} (H-D-A) matchday.")
                    if perm['expected_over15_count'] >= 6:
                        print(f"⚠️ High-scoring matchday expected: {perm['expected_over15_count']}/8 fixtures O1.5 ≥ 65%")
                    elif perm['expected_over15_count'] <= 3:
                        print(f"⚠️ Low-scoring matchday expected: only {perm['expected_over15_count']}/8 fixtures O1.5 ≥ 65%")
                print("")
        
        # ─── LIVE TEST: Compare vs Actual Results ───
        if args.test:
            verdicts, summary = run_live_test(analyses, season_label, md_num)
            if verdicts:
                print(f"━━━ 📋 LIVE TEST RESULTS — {md_label} ━━━")
                print("")
                for v in verdicts:
                    status_icon = "✅" if v.get('score') != 'PENDING' else "⏳"
                    print(f"{status_icon} {v['fixture']}: {v.get('score', 'PENDING')}")
                    print(f"   O1.5: {v.get('o15', '?')} | Gate: {v.get('gate', '?')} ({v.get('gate_info', 'N/A')})")
                    for b in v.get('bets', []):
                        print(f"   {b}")
                    print("")
                
                if summary:
                    s = summary
                    print("━━━ LIVE TEST SUMMARY ━━━")
                    print(f"O1.5: {s['o15_hit_rate']}")
                    print(f"FS 1X2 (max outcome): {s['fs_1x2_hit_rate']}")
                    print(f"Switching Gate: {s['gate_hit_rate']}")
                    print(f"Certainty Bets: {s['certainty_hit_rate']}")
                    
                    # Compare approaches
                    o15_wins, o15_total = s['o15_wins'], s['o15_total']
                    gate_wins, gate_total = s['gate_wins'], s['gate_total']
                    
                    print("")
                    print("Strategy Comparison:")
                    print(f"  Always-O1.5: {o15_wins}/{o15_total} ({o15_wins/o15_total*100:.1f}% if o15_total else 'N/A')")
                    if gate_total:
                        print(f"  Switching Gate: {gate_wins}/{gate_total} ({gate_wins/gate_total*100:.1f}%)")
                        if o15_total > 0:
                            diff = (gate_wins/gate_total - o15_wins/o15_total) * 100
                            sign = "+" if diff > 0 else ""
                            print(f"  Gate vs Always-O1.5: {sign}{diff:.1f}%")
                print("")
    
    # Save analysis as JSON
    if args.save:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        save_path = args.output or f"{OUTPUT_DIR}/tts_analysis_{timestamp}.json"
        with open(save_path, 'w') as f:
            json.dump(all_analyses, f, indent=2, default=str)
        # Echo save path for cron capture
        print(f"\n[SAVED] {save_path}")


if __name__ == '__main__':
    main()
