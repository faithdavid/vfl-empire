#!/usr/bin/env python3
"""
VFL H2H Matchup Pattern Analysis
Analyzes history.db to produce per-matchup head-to-head patterns across all seasons.
"""

import sqlite3
import json
import os
import math
from collections import defaultdict
from datetime import datetime

DB_PATH = os.path.expanduser("~/Documents/Projects/vfl-data/databases/history.db")
OUTPUT_DIR = os.path.expanduser("~/Documents/Projects/vfl-data/analysis")
JSON_OUTPUT = os.path.join(OUTPUT_DIR, "h2h_matchup_patterns.json")
MD_OUTPUT = os.path.join(OUTPUT_DIR, "h2h_playbook.md")

# The 16 teams and their tiers
TEAMS = [
    "Manchester Blue", "Liverpool", "Manchester Red", "Chelsea",
    "Tottenham", "London Guns", "Aston Villa", "Everton",
    "West Ham", "Brighton", "Leeds", "Wolverhampton",
    "Crystal Palace", "Newcastle", "Fulham", "Bournemouth"
]

TIER_MAP = {
    "Manchester Blue": 1, "Liverpool": 1, "Manchester Red": 1,
    "Chelsea": 1, "Tottenham": 1, "London Guns": 1,
    "Aston Villa": 2, "Everton": 2, "West Ham": 2, "Brighton": 2,
    "Leeds": 3, "Wolverhampton": 3, "Crystal Palace": 3, "Newcastle": 3,
    "Fulham": 4, "Bournemouth": 4
}

def normalize_team(name):
    """Normalize team name to canonical title case."""
    if not name:
        return None
    n = name.strip().upper()
    mapping = {
        "MANCHESTER BLUE": "Manchester Blue",
        "MANCHESTER RED": "Manchester Red",
        "ASTON VILLA": "Aston Villa",
        "LIVERPOOL": "Liverpool",
        "CHELSEA": "Chelsea",
        "TOTTENHAM": "Tottenham",
        "LONDON GUNS": "London Guns",
        "EVERTON": "Everton",
        "WEST HAM": "West Ham",
        "BRIGHTON": "Brighton",
        "LEEDS": "Leeds",
        "WOLVERHAMPTON": "Wolverhampton",
        "CRYSTAL PALACE": "Crystal Palace",
        "NEWCASTLE": "Newcastle",
        "FULHAM": "Fulham",
        "BOURNEMOUTH": "Bournemouth",
    }
    return mapping.get(n, name.strip().title())

def normalize_outcome(outcome):
    """Normalize outcome to HOME/AWAY/DRAW."""
    if not outcome:
        return None
    o = outcome.strip().upper()
    if o in ('H', 'HOME'):
        return 'HOME'
    elif o in ('A', 'AWAY'):
        return 'AWAY'
    elif o in ('D', 'DRAW'):
        return 'DRAW'
    return None

def implied_prob(odds):
    """Convert decimal odds to implied probability."""
    if odds is None or odds <= 0:
        return None
    return 1.0 / odds

def brier_score(prob_home, prob_draw, prob_away, outcome):
    """Calculate Brier score for a match."""
    if outcome == 'HOME':
        return (prob_home - 1)**2 + (prob_draw - 0)**2 + (prob_away - 0)**2
    elif outcome == 'DRAW':
        return (prob_home - 0)**2 + (prob_draw - 1)**2 + (prob_away - 0)**2
    elif outcome == 'AWAY':
        return (prob_home - 0)**2 + (prob_draw - 0)**2 + (prob_away - 1)**2
    return None

def main():
    print(f"Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Fetch all matches
    print("Fetching all matches...")
    cursor.execute("""
        SELECT season, day, home, away, oh, od, oa, outcome, h, a, total, gg, o25
        FROM matches
        ORDER BY season, day
    """)
    rows = cursor.fetchall()
    print(f"Total rows fetched: {len(rows)}")
    
    # ---- Phase 1: Normalize and classify ----
    matches_normalized = []
    skipped_no_outcome = 0
    skipped_unknown_team = 0

    for r in rows:
        home = normalize_team(r['home'])
        away = normalize_team(r['away'])
        outcome = normalize_outcome(r['outcome'])
        
        if home not in TIER_MAP or away not in TIER_MAP:
            skipped_unknown_team += 1
            continue
        if outcome is None:
            skipped_no_outcome += 1
            continue
        
        match = {
            'season': r['season'],
            'day': r['day'],
            'home': home,
            'away': away,
            'oh': r['oh'],
            'od': r['od'],
            'oa': r['oa'],
            'outcome': outcome,
            'h_goals': r['h'],
            'a_goals': r['a'],
            'total': r['total'],
            'gg': r['gg'],
            'o25': r['o25'],
        }
        matches_normalized.append(match)
    
    print(f"Normalized matches: {len(matches_normalized)}")
    print(f"Skipped (no outcome): {skipped_no_outcome}")
    print(f"Skipped (unknown team): {skipped_unknown_team}")

    # ---- Phase 2: Results-only H2H matrix ----
    print("\nBuilding results-only H2H matrix...")
    
    # h2h_results[team_a][team_b] = {'home': {HOME: n, DRAW: n, AWAY: n}, 'away': {...}}
    # For each matchup, we track when A is home vs B, and when A is away vs B
    h2h_results = defaultdict(lambda: defaultdict(lambda: {
        'total_home': 0, 'home_wins': 0, 'home_draws': 0, 'home_losses': 0,
        'total_away': 0, 'away_wins': 0, 'away_draws': 0, 'away_losses': 0,
        'total': 0, 'wins': 0, 'draws': 0, 'losses': 0,
        'home_goals_for': 0, 'home_goals_against': 0,
        'away_goals_for': 0, 'away_goals_against': 0,
        'total_goals_for': 0, 'total_goals_against': 0,
        'matches': []
    }))

    for m in matches_normalized:
        h, a = m['home'], m['away']
        outcome = m['outcome']
        
        entry = h2h_results[h][a]
        entry['total'] += 1
        entry['total_home'] += 1
        
        hf = m['h_goals'] if m['h_goals'] is not None else 0
        af = m['a_goals'] if m['a_goals'] is not None else 0
        
        if outcome == 'HOME':
            entry['home_wins'] += 1
            entry['wins'] += 1
        elif outcome == 'DRAW':
            entry['home_draws'] += 1
            entry['draws'] += 1
        elif outcome == 'AWAY':
            entry['home_losses'] += 1
            entry['losses'] += 1
        
        entry['home_goals_for'] += hf
        entry['home_goals_against'] += af
        entry['total_goals_for'] += hf
        entry['total_goals_against'] += af
        
        if hf is not None and af is not None:
            entry['matches'].append({
                'season': m['season'],
                'day': m['day'],
                'home': h, 'away': a,
                'score': f"{hf}-{af}",
                'outcome': outcome
            })
        
        # Also track from away perspective
        entry_a = h2h_results[a][h]
        entry_a['total'] += 1
        entry_a['total_away'] += 1
        entry_a['away_goals_for'] += af
        entry_a['away_goals_against'] += hf
        entry_a['total_goals_for'] += af
        entry_a['total_goals_against'] += hf
        
        if outcome == 'HOME':
            entry_a['away_losses'] += 1
            entry_a['losses'] += 1
        elif outcome == 'DRAW':
            entry_a['away_draws'] += 1
            entry_a['draws'] += 1
        elif outcome == 'AWAY':
            entry_a['away_wins'] += 1
            entry_a['wins'] += 1
    
    # Build results matrix
    results_matrix = {}
    for team_a in TEAMS:
        results_matrix[team_a] = {}
        for team_b in TEAMS:
            if team_a == team_b:
                continue
            d = h2h_results[team_a].get(team_b, {})
            total = d.get('total', 0)
            if total == 0:
                continue
            
            home_w = d.get('home_wins', 0)
            home_d = d.get('home_draws', 0)
            home_l = d.get('home_losses', 0)
            total_h = d.get('total_home', 0)
            
            away_w = d.get('away_wins', 0)
            away_d = d.get('away_draws', 0)
            away_l = d.get('away_losses', 0)
            total_a = d.get('total_away', 0)
            
            results_matrix[team_a][team_b] = {
                'total_matches': total,
                'home_games': total_h,
                'away_games': total_a,
                'overall': {
                    'wins': d.get('wins', 0),
                    'draws': d.get('draws', 0),
                    'losses': d.get('losses', 0),
                    'win_pct': round(d.get('wins', 0) / total * 100, 2) if total else 0,
                    'draw_pct': round(d.get('draws', 0) / total * 100, 2) if total else 0,
                    'loss_pct': round(d.get('losses', 0) / total * 100, 2) if total else 0,
                },
                'when_home': {
                    'wins': home_w, 'draws': home_d, 'losses': home_l,
                    'win_pct': round(home_w / total_h * 100, 2) if total_h else 0,
                    'draw_pct': round(home_d / total_h * 100, 2) if total_h else 0,
                    'loss_pct': round(home_l / total_h * 100, 2) if total_h else 0,
                    'goals_for': d.get('home_goals_for', 0),
                    'goals_against': d.get('home_goals_against', 0),
                    'avg_goals_for': round(d.get('home_goals_for', 0) / total_h, 2) if total_h else 0,
                    'avg_goals_against': round(d.get('home_goals_against', 0) / total_h, 2) if total_h else 0,
                },
                'when_away': {
                    'wins': away_w, 'draws': away_d, 'losses': away_l,
                    'win_pct': round(away_w / total_a * 100, 2) if total_a else 0,
                    'draw_pct': round(away_d / total_a * 100, 2) if total_a else 0,
                    'loss_pct': round(away_l / total_a * 100, 2) if total_a else 0,
                    'goals_for': d.get('away_goals_for', 0),
                    'goals_against': d.get('away_goals_against', 0),
                    'avg_goals_for': round(d.get('away_goals_for', 0) / total_a, 2) if total_a else 0,
                    'avg_goals_against': round(d.get('away_goals_against', 0) / total_a, 2) if total_a else 0,
                }
            }
    
    # ---- Phase 3: Odds-adjusted H2H ----
    print("Building odds-adjusted H2H analysis...")
    
    odds_analysis = {}
    for team_a in TEAMS:
        odds_analysis[team_a] = {}
        for team_b in TEAMS:
            if team_a == team_b:
                continue
            
            # Gather all matches with odds between these two
            odds_matches = []
            for m in matches_normalized:
                if ((m['home'] == team_a and m['away'] == team_b) or
                    (m['home'] == team_b and m['away'] == team_a)):
                    if m['oh'] is not None and m['od'] is not None and m['oa'] is not None:
                        odds_matches.append(m)
            
            if not odds_matches:
                continue
            
            total_odds = len(odds_matches)
            
            # For team_a perspective
            actual_home_wins = 0
            actual_draws = 0
            actual_away_wins = 0
            
            sum_implied_home = 0.0
            sum_implied_draw = 0.0
            sum_implied_away = 0.0
            
            # For when team_a is home
            home_matches = [m for m in odds_matches if m['home'] == team_a]
            away_matches = [m for m in odds_matches if m['home'] == team_b]
            
            home_actual = {'wins': 0, 'draws': 0, 'losses': 0}
            home_implied = {'wins': 0.0, 'draws': 0.0, 'losses': 0.0}
            away_actual = {'wins': 0, 'draws': 0, 'losses': 0}
            away_implied = {'wins': 0.0, 'draws': 0.0, 'losses': 0.0}
            
            brier_scores = []
            
            for m in odds_matches:
                ip_h = implied_prob(m['oh'])
                ip_d = implied_prob(m['od'])
                ip_a = implied_prob(m['oa'])
                
                if ip_h is None or ip_d is None or ip_a is None:
                    continue
                
                # Normalize to sum=1 (remove overround)
                total_ip = ip_h + ip_d + ip_a
                ip_h_norm = ip_h / total_ip if total_ip else 0
                ip_d_norm = ip_d / total_ip if total_ip else 0
                ip_a_norm = ip_a / total_ip if total_ip else 0
                
                bs = brier_score(ip_h_norm, ip_d_norm, ip_a_norm, m['outcome'])
                if bs is not None:
                    brier_scores.append(bs)
                
                if m['home'] == team_a:
                    # team_a is home
                    home_actual['wins'] += 1 if m['outcome'] == 'HOME' else 0
                    home_actual['draws'] += 1 if m['outcome'] == 'DRAW' else 0
                    home_actual['losses'] += 1 if m['outcome'] == 'AWAY' else 0
                    home_implied['wins'] += ip_h_norm
                    home_implied['draws'] += ip_d_norm
                    home_implied['losses'] += ip_a_norm
                else:
                    # team_a is away
                    away_actual['wins'] += 1 if m['outcome'] == 'AWAY' else 0
                    away_actual['draws'] += 1 if m['outcome'] == 'DRAW' else 0
                    away_actual['losses'] += 1 if m['outcome'] == 'HOME' else 0
                    away_implied['wins'] += ip_a_norm
                    away_implied['draws'] += ip_d_norm
                    away_implied['losses'] += ip_h_norm
            
            n_home = len(home_matches)
            n_away = len(away_matches)
            
            avg_brier = round(sum(brier_scores) / len(brier_scores), 4) if brier_scores else None
            
            odds_analysis[team_a][team_b] = {
                'total_odds_matches': total_odds,
                'avg_brier_score': avg_brier,
                'when_home': {
                    'matches': n_home,
                    'actual_win_pct': round(home_actual['wins'] / n_home * 100, 2) if n_home else 0,
                    'actual_draw_pct': round(home_actual['draws'] / n_home * 100, 2) if n_home else 0,
                    'actual_loss_pct': round(home_actual['losses'] / n_home * 100, 2) if n_home else 0,
                    'implied_win_pct': round(home_implied['wins'] / n_home * 100, 2) if n_home else 0,
                    'implied_draw_pct': round(home_implied['draws'] / n_home * 100, 2) if n_home else 0,
                    'implied_loss_pct': round(home_implied['losses'] / n_home * 100, 2) if n_home else 0,
                    'edge': round((home_actual['wins'] / n_home - home_implied['wins'] / n_home) * 100, 2) if n_home else 0,
                },
                'when_away': {
                    'matches': n_away,
                    'actual_win_pct': round(away_actual['wins'] / n_away * 100, 2) if n_away else 0,
                    'actual_draw_pct': round(away_actual['draws'] / n_away * 100, 2) if n_away else 0,
                    'actual_loss_pct': round(away_actual['losses'] / n_away * 100, 2) if n_away else 0,
                    'implied_win_pct': round(away_implied['wins'] / n_away * 100, 2) if n_away else 0,
                    'implied_draw_pct': round(away_implied['draws'] / n_away * 100, 2) if n_away else 0,
                    'implied_loss_pct': round(away_implied['losses'] / n_away * 100, 2) if n_away else 0,
                    'edge': round((away_actual['wins'] / n_away - away_implied['wins'] / n_away) * 100, 2) if n_away else 0,
                }
            }

    # ---- Phase 4: Specific patterns per matchup ----
    print("Extracting specific patterns...")
    
    patterns = []
    
    for team_a in TEAMS:
        for team_b in TEAMS:
            if team_a == team_b:
                continue
            d = h2h_results[team_a].get(team_b, {})
            total = d.get('total', 0)
            if total < 3:  # Need minimum matches for pattern
                continue
            
            total_h = d.get('total_home', 0)
            total_a = d.get('total_away', 0)
            
            # Home win pattern
            if total_h >= 3:
                hw_pct = d['home_wins'] / total_h * 100
                if hw_pct >= 55:
                    patterns.append({
                        'type': 'home_dominance',
                        'team': team_a,
                        'opponent': team_b,
                        'context': 'home',
                        'stat': f"{team_a} beats {team_b} {hw_pct:.1f}% of the time at home",
                        'pct': round(hw_pct, 1),
                        'matches': total_h,
                        'wins': d['home_wins'],
                        'draws': d['home_draws'],
                        'losses': d['home_losses'],
                        'strength': 'strong' if hw_pct >= 65 else 'moderate',
                        'avg_goals_for': round(d.get('home_goals_for', 0) / total_h, 2) if total_h else 0,
                        'avg_goals_against': round(d.get('home_goals_against', 0) / total_h, 2) if total_h else 0,
                    })
            
            # Away win pattern (team_a winning at team_b's home)
            if total_a >= 3:
                aw_pct = d['away_wins'] / total_a * 100
                if aw_pct >= 50:
                    patterns.append({
                        'type': 'away_dominance',
                        'team': team_a,
                        'opponent': team_b,
                        'context': 'away',
                        'stat': f"{team_a} beats {team_b} {aw_pct:.1f}% of the time away",
                        'pct': round(aw_pct, 1),
                        'matches': total_a,
                        'wins': d['away_wins'],
                        'draws': d['away_draws'],
                        'losses': d['away_losses'],
                        'strength': 'strong' if aw_pct >= 60 else 'moderate',
                        'avg_goals_for': round(d.get('away_goals_for', 0) / total_a, 2) if total_a else 0,
                        'avg_goals_against': round(d.get('away_goals_against', 0) / total_a, 2) if total_a else 0,
                    })
            
            # Draw tendency
            if total >= 5:
                draw_pct = d['draws'] / total * 100
                if draw_pct >= 35:
                    patterns.append({
                        'type': 'draw_tendency',
                        'team': team_a,
                        'opponent': team_b,
                        'context': 'overall',
                        'stat': f"{team_a} vs {team_b} draws {draw_pct:.1f}% of the time",
                        'pct': round(draw_pct, 1),
                        'matches': total,
                        'draws': d['draws'],
                        'strength': 'strong' if draw_pct >= 45 else 'moderate',
                    })
            
            # Home vulnerability (team_a losing at home to team_b)
            if total_h >= 3:
                hl_pct = d['home_losses'] / total_h * 100
                if hl_pct >= 35:
                    patterns.append({
                        'type': 'home_vulnerability',
                        'team': team_a,
                        'opponent': team_b,
                        'context': 'home',
                        'stat': f"{team_a} loses at home to {team_b} {hl_pct:.1f}% of the time",
                        'pct': round(hl_pct, 1),
                        'matches': total_h,
                        'wins': d['home_wins'],
                        'draws': d['home_draws'],
                        'losses': d['home_losses'],
                        'strength': 'strong' if hl_pct >= 50 else 'moderate',
                    })
            
            # Away vulnerability (team_a losing away to team_b)
            if total_a >= 3:
                al_pct = d['away_losses'] / total_a * 100
                if al_pct >= 55:
                    patterns.append({
                        'type': 'away_vulnerability',
                        'team': team_a,
                        'opponent': team_b,
                        'context': 'away',
                        'stat': f"{team_a} loses away at {team_b} {al_pct:.1f}% of the time",
                        'pct': round(al_pct, 1),
                        'matches': total_a,
                        'wins': d['away_wins'],
                        'draws': d['away_draws'],
                        'losses': d['away_losses'],
                        'strength': 'strong' if al_pct >= 70 else 'moderate',
                    })
            
            # High-scoring matchups
            if total >= 5:
                goals_for_avg = (d.get('home_goals_for', 0) + d.get('away_goals_for', 0)) / total
                goals_against_avg = (d.get('home_goals_against', 0) + d.get('away_goals_against', 0)) / total
                total_goals_avg = goals_for_avg + goals_against_avg
                if total_goals_avg >= 3.0:
                    patterns.append({
                        'type': 'high_scoring',
                        'team': team_a,
                        'opponent': team_b,
                        'context': 'overall',
                        'stat': f"{team_a} vs {team_b} averages {total_goals_avg:.1f} goals per match",
                        'pct': round(total_goals_avg, 1),
                        'matches': total,
                        'avg_total_goals': round(total_goals_avg, 2),
                        'strength': 'strong' if total_goals_avg >= 3.5 else 'moderate',
                    })
            
            # Low-scoring matchups
            if total >= 5:
                total_goals_avg = (d.get('home_goals_for', 0) + d.get('away_goals_for', 0) +
                                   d.get('home_goals_against', 0) + d.get('away_goals_against', 0)) / total
                if total_goals_avg <= 1.8:
                    patterns.append({
                        'type': 'low_scoring',
                        'team': team_a,
                        'opponent': team_b,
                        'context': 'overall',
                        'stat': f"{team_a} vs {team_b} averages only {total_goals_avg:.1f} goals per match",
                        'pct': round(total_goals_avg, 1),
                        'matches': total,
                        'avg_total_goals': round(total_goals_avg, 2),
                        'strength': 'strong' if total_goals_avg <= 1.5 else 'moderate',
                    })

    # Sort patterns by absolute deviation from baseline
    patterns.sort(key=lambda p: abs(p['pct'] - 50) if p['type'] not in ('high_scoring', 'low_scoring') else abs(p['pct']), reverse=True)

    # ---- Phase 5: Tier upset frequency ----
    print("Computing tier upset frequencies...")
    
    tier_upsets = defaultdict(lambda: {
        'total_matches': 0,
        'lower_tier_wins': 0,
        'lower_tier_draws': 0,
        'higher_tier_wins': 0,
        'upset_pct': 0.0,
        'matchups': []
    })
    
    for m in matches_normalized:
        h_tier = TIER_MAP[m['home']]
        a_tier = TIER_MAP[m['away']]
        
        if h_tier == a_tier:
            continue  # Same tier
        
        if h_tier > a_tier:
            # Lower tier at home vs higher tier
            lower_team = m['home']
            higher_team = m['away']
            is_upset = m['outcome'] == 'HOME'
            key = f"T{h_tier}home_v_T{a_tier}away"
            tier_key = (h_tier, a_tier)
        else:
            # Higher tier at home vs lower tier
            lower_team = m['away']
            higher_team = m['home']
            is_upset = m['outcome'] == 'AWAY'
            key = f"T{a_tier}away_v_T{h_tier}home"
            tier_key = (a_tier, h_tier)
        
        entry = tier_upsets[tier_key]
        entry['total_matches'] += 1
        if is_upset:
            entry['lower_tier_wins'] += 1
        elif m['outcome'] == 'DRAW':
            entry['lower_tier_draws'] += 1
        else:
            entry['higher_tier_wins'] += 1
        
        if entry['total_matches'] <= 100:  # Store last 100 match details
            entry['matchups'].append({
                'lower': lower_team, 'higher': higher_team,
                'score': f"{m['h_goals']}-{m['a_goals']}",
                'outcome': m['outcome'],
                'season': m['season'],
                'h_tier': h_tier, 'a_tier': a_tier,
                'is_upset': is_upset
            })
    
    # Calculate percentages
    tier_upsets_formatted = {}
    for (low_tier, high_tier), data in sorted(tier_upsets.items()):
        t = data['total_matches']
        tier_upsets_formatted[f"T{low_tier}_vs_T{high_tier}"] = {
            'lower_tier': f"T{low_tier}",
            'higher_tier': f"T{high_tier}",
            'total_matches': t,
            'lower_tier_wins': data['lower_tier_wins'],
            'lower_tier_draws': data['lower_tier_draws'],
            'higher_tier_wins': data['higher_tier_wins'],
            'lower_tier_win_pct': round(data['lower_tier_wins'] / t * 100, 2) if t else 0,
            'draw_pct': round(data['lower_tier_draws'] / t * 100, 2) if t else 0,
            'higher_tier_win_pct': round(data['higher_tier_wins'] / t * 100, 2) if t else 0,
            'sample_matchups': data['matchups'][:10]  # First 10
        }
    
    # Specific upset patterns: which lower-tier teams beat which higher-tier teams most often
    upset_matchups = []
    for m in matches_normalized:
        h_tier = TIER_MAP[m['home']]
        a_tier = TIER_MAP[m['away']]
        
        if h_tier > a_tier and m['outcome'] == 'HOME':
            upset_matchups.append({
                'lower': m['home'], 'higher': m['away'],
                'lower_tier': h_tier, 'higher_tier': a_tier,
            })
        elif a_tier > h_tier and m['outcome'] == 'AWAY':
            upset_matchups.append({
                'lower': m['away'], 'higher': m['home'],
                'lower_tier': a_tier, 'higher_tier': h_tier,
            })
    
    upset_freq = defaultdict(int)
    upset_total = defaultdict(int)
    for u in upset_matchups:
        key = (u['lower'], u['higher'])
        upset_freq[key] += 1
        upset_total[(u['lower'], u['higher'])] += 1
    
    # Count total matches per upset pairing
    for m in matches_normalized:
        h_tier = TIER_MAP[m['home']]
        a_tier = TIER_MAP[m['away']]
        if h_tier > a_tier:
            key = (m['home'], m['away'])
            upset_total[key] = upset_total.get(key, 0)
        elif a_tier > h_tier:
            key = (m['away'], m['home'])
            upset_total[key] = upset_total.get(key, 0)
    
    # Re-count properly
    upset_total = defaultdict(int)
    for m in matches_normalized:
        h_tier = TIER_MAP[m['home']]
        a_tier = TIER_MAP[m['away']]
        if h_tier > a_tier:
            key = (m['home'], m['away'])
            upset_total[key] += 1
        elif a_tier > h_tier:
            key = (m['away'], m['home'])
            upset_total[key] += 1
    
    upset_matchup_analysis = []
    for (lower, higher), wins in upset_freq.items():
        total = upset_total.get((lower, higher), 0)
        if total >= 3:
            upset_matchup_analysis.append({
                'lower_tier_team': lower,
                'higher_tier_team': higher,
                'total_matches': total,
                'lower_tier_wins': wins,
                'upset_pct': round(wins / total * 100, 2) if total else 0,
            })
    
    upset_matchup_analysis.sort(key=lambda x: x['upset_pct'], reverse=True)

    # ---- Assemble final output ----
    print("Assembling final JSON output...")
    
    # Prune match detail lists to keep JSON manageable
    for team_a in TEAMS:
        for team_b in TEAMS:
            if team_a != team_b and team_b in results_matrix.get(team_a, {}):
                if 'matches' in h2h_results[team_a][team_b]:
                    del h2h_results[team_a][team_b]['matches']
    
    output = {
        'metadata': {
            'analysis_date': datetime.now().isoformat(),
            'database': 'history.db',
            'total_matches': len(matches_normalized),
            'total_seasons': len(set(m['season'] for m in matches_normalized)),
            'teams': TEAMS,
            'tier_map': TIER_MAP,
        },
        'results_h2h_matrix': results_matrix,
        'odds_adjusted_h2h': odds_analysis,
        'patterns': {
            'total_patterns': len(patterns),
            'patterns_by_type': {},
            'all_patterns': patterns,
        },
        'tier_upset_analysis': {
            'tier_pair_summary': tier_upsets_formatted,
            'specific_upset_matchups': upset_matchup_analysis,
        }
    }
    
    # Count patterns by type
    for p in patterns:
        ptype = p['type']
        if ptype not in output['patterns']['patterns_by_type']:
            output['patterns']['patterns_by_type'][ptype] = {'count': 0, 'examples': []}
        output['patterns']['patterns_by_type'][ptype]['count'] += 1
        if len(output['patterns']['patterns_by_type'][ptype]['examples']) < 5:
            output['patterns']['patterns_by_type'][ptype]['examples'].append(p['stat'])
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(JSON_OUTPUT, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"Saved JSON to {JSON_OUTPUT}")
    
    # ---- Generate Markdown Playbook ----
    print("Generating markdown playbook...")
    
    md_lines = []
    md_lines.append("# VFL Head-to-Head Matchup Playbook\n")
    md_lines.append(f"*Analysis generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
    md_lines.append(f"*Based on {len(matches_normalized):,} matches across {len(set(m['season'] for m in matches_normalized))} historical seasons*\n")
    md_lines.append("---\n")
    
    md_lines.append("## Top 20 Most Actionable Patterns\n")
    
    # Score patterns for "actionability" — balanced across categories
    scored_patterns = []
    # Track best per category to ensure diversity
    category_best = defaultdict(list)
    
    for p in patterns:
        score = 0
        if p['type'] == 'home_dominance':
            score = p['pct'] * 0.6 + min(p['matches'], 100) * 0.2
            if p['strength'] == 'strong':
                score *= 1.15
        elif p['type'] == 'away_dominance':
            score = p['pct'] * 0.7 + min(p['matches'], 100) * 0.2
            if p['strength'] == 'strong':
                score *= 1.15
        elif p['type'] == 'draw_tendency':
            score = p['pct'] * 0.7 + min(p['matches'], 100) * 0.15
        elif p['type'] == 'home_vulnerability':
            score = p['pct'] * 0.6 + min(p['matches'], 100) * 0.2
        elif p['type'] == 'high_scoring':
            score = (p['pct'] - 2.0) * 25 + min(p['matches'], 100) * 0.15
        elif p['type'] == 'low_scoring':
            score = (2.5 - p['pct']) * 25 + min(p['matches'], 100) * 0.15
        elif p['type'] == 'away_vulnerability':
            score = p['pct'] * 0.6 + min(p['matches'], 100) * 0.2
        scored_patterns.append((score, p))
        category_best[p['type']].append((score, p))
    
    scored_patterns.sort(key=lambda x: x[0], reverse=True)
    
    # Select top 20 ensuring category diversity: pick top 3 from each major category
    # then fill remaining with best overall
    selected = []
    seen_stats = set()
    
    # First pass: pick top 3 from each category
    categories_in_order = ['home_dominance', 'away_dominance', 'home_vulnerability', 
                           'away_vulnerability', 'draw_tendency', 'high_scoring', 'low_scoring']
    for cat in categories_in_order:
        items = sorted(category_best.get(cat, []), key=lambda x: x[0], reverse=True)
        for score, p in items[:3]:
            if p['stat'] not in seen_stats:
                selected.append((score, p))
                seen_stats.add(p['stat'])
    
    # Second pass: fill remaining slots with best overall not already selected
    for score, p in scored_patterns:
        if len(selected) >= 20:
            break
        if p['stat'] not in seen_stats:
            selected.append((score, p))
            seen_stats.add(p['stat'])
    
    selected.sort(key=lambda x: x[0], reverse=True)
    top20 = selected[:20]
    
    for idx, (score, p) in enumerate(top20, 1):
        md_lines.append(f"### {idx}. {p['stat']}\n")
        md_lines.append(f"- **Type**: {p['type'].replace('_', ' ').title()} | **Strength**: {p['strength'].title()} | **Matches**: {p['matches']}")
        md_lines.append(f"- **Confidence Score**: {score:.1f}")
        
        if p['type'] in ('home_dominance', 'away_dominance', 'home_vulnerability', 'away_vulnerability'):
            md_lines.append(f"- **Record**: {p['wins']}W - {p['draws']}D - {p['losses']}L")
            if 'avg_goals_for' in p:
                md_lines.append(f"- **Avg Goals For**: {p['avg_goals_for']} | **Avg Goals Against**: {p['avg_goals_against']}")
        
        if p['type'] in ('high_scoring', 'low_scoring'):
            md_lines.append(f"- **Avg Total Goals**: {p.get('avg_total_goals', p['pct'])}")
        
        if p['type'] == 'draw_tendency':
            md_lines.append(f"- **Draws**: {p['draws']}/{p['matches']} matches")
        
        # Add betting implication
        implication = ""
        if p['type'] == 'home_dominance' and p['strength'] == 'strong':
            implication = f"Strong play: Back {p['team']} when hosting {p['opponent']}"
        elif p['type'] == 'away_dominance' and p['strength'] == 'strong':
            implication = f"Strong play: Back {p['team']} when visiting {p['opponent']}"
        elif p['type'] == 'draw_tendency' and p['strength'] == 'strong':
            implication = f"Consider draw bet when {p['team']} faces {p['opponent']}"
        elif p['type'] == 'home_vulnerability' and p['strength'] == 'strong':
            implication = f"Fade {p['team']} at home vs {p['opponent']}"
        elif p['type'] == 'high_scoring':
            implication = f"Over goals likely in {p['team']} vs {p['opponent']}"
        elif p['type'] == 'low_scoring':
            implication = f"Under goals likely in {p['team']} vs {p['opponent']}"
        
        if implication:
            md_lines.append(f"- **💰 Action**: {implication}")
        
        md_lines.append("")
    
    # Add tier upset section
    md_lines.append("---\n")
    md_lines.append("## Tier Upset Analysis\n")
    md_lines.append("\n### Summary by Tier Pairing\n")
    md_lines.append("| Matchup | Total Matches | Lower Tier Win% | Draw% | Higher Tier Win% |\n")
    md_lines.append("|---------|:---:|:---:|:---:|:---:|\n")
    
    for key, data in sorted(tier_upsets_formatted.items()):
        md_lines.append(
            f"| {data['lower_tier']} (home/away) vs {data['higher_tier']} | "
            f"{data['total_matches']} | {data['lower_tier_win_pct']}% | "
            f"{data['draw_pct']}% | {data['higher_tier_win_pct']}% |"
        )
    
    md_lines.append("\n### Most Frequent Specific Upsets (Lower Tier Beating Higher Tier)\n")
    md_lines.append("| Lower Tier Team | Higher Tier Team | Matches | Upset Wins | Upset % |\n")
    md_lines.append("|---------|---------|:---:|:---:|:---:|\n")
    
    for u in upset_matchup_analysis[:15]:
        md_lines.append(
            f"| {u['lower_tier_team']} | {u['higher_tier_team']} | "
            f"{u['total_matches']} | {u['lower_tier_wins']} | {u['upset_pct']}% |"
        )
    
    # Add odds edge section
    md_lines.append("\n---\n")
    md_lines.append("## Notable Odds Edges (Actual vs Implied Probability)\n")
    md_lines.append("*Where the market significantly misprices a matchup*\n")
    
    odds_edges = []
    for team_a in TEAMS:
        for team_b in TEAMS:
            if team_a == team_b:
                continue
            oa = odds_analysis.get(team_a, {}).get(team_b, {})
            if not oa:
                continue
            for context in ['when_home', 'when_away']:
                c = oa.get(context, {})
                if c.get('matches', 0) >= 5:
                    edge = c.get('edge', 0)
                    if abs(edge) >= 5:
                        direction = "value" if edge > 0 else "overpriced"
                        odds_edges.append({
                            'team': team_a,
                            'opponent': team_b,
                            'context': context.replace('_', ' '),
                            'edge': edge,
                            'direction': direction,
                            'actual_pct': c['actual_win_pct'],
                            'implied_pct': c['implied_win_pct'],
                            'matches': c['matches']
                        })
    
    odds_edges.sort(key=lambda x: abs(x['edge']), reverse=True)
    
    md_lines.append("\n| Team | Opponent | Context | Matches | Actual Win% | Implied Win% | Edge | Signal |\n")
    md_lines.append("|------|----------|---------|:-------:|:-----------:|:------------:|:----:|:------:|\n")
    
    for oe in odds_edges[:20]:
        signal = "📈 VALUE" if oe['edge'] > 0 else "📉 FADE"
        md_lines.append(
            f"| {oe['team']} | {oe['opponent']} | {oe['context']} | "
            f"{oe['matches']} | {oe['actual_pct']}% | {oe['implied_pct']}% | "
            f"{oe['edge']:+.1f}% | {signal} |"
        )
    
    # Add quick-reference H2H summary
    md_lines.append("\n---\n")
    md_lines.append("## Quick-Reference: Best/Worst Matchups for Each Team\n")
    
    for team in TEAMS:
        best_opponent_home = None
        best_pct_home = 0
        worst_opponent_home = None
        worst_pct_home = 100
        best_opponent_away = None
        best_pct_away = 0
        worst_opponent_away = None
        worst_pct_away = 100
        
        for opp in TEAMS:
            if team == opp:
                continue
            d = results_matrix.get(team, {}).get(opp, {})
            if not d:
                continue
            wh = d.get('when_home', {})
            wa = d.get('when_away', {})
            
            if d.get('home_games', 0) >= 3:
                wp = wh['win_pct']
                if wp > best_pct_home:
                    best_pct_home = wp
                    best_opponent_home = opp
                if wp < worst_pct_home:
                    worst_pct_home = wp
                    worst_opponent_home = opp
            
            if d.get('away_games', 0) >= 3:
                wp = wa['win_pct']
                if wp > best_pct_away:
                    best_pct_away = wp
                    best_opponent_away = opp
                if wp < worst_pct_away:
                    worst_pct_away = wp
                    worst_opponent_away = opp
        
        md_lines.append(f"\n### **{team}**\n")
        if best_opponent_home:
            md_lines.append(f"- 🏠 **Best home matchup**: vs {best_opponent_home} — **{best_pct_home:.0f}%** win rate")
        if worst_opponent_home:
            md_lines.append(f"- 🏠 **Toughest home matchup**: vs {worst_opponent_home} — **{worst_pct_home:.0f}%** win rate")
        if best_opponent_away:
            md_lines.append(f"- 🛩️ **Best away matchup**: at {best_opponent_away} — **{best_pct_away:.0f}%** win rate")
        if worst_opponent_away:
            md_lines.append(f"- 🛩️ **Toughest away matchup**: at {worst_opponent_away} — **{worst_pct_away:.0f}%** win rate")
    
    md_content = "\n".join(md_lines)
    
    with open(MD_OUTPUT, 'w') as f:
        f.write(md_content)
    print(f"Saved markdown to {MD_OUTPUT}")
    
    print("\nDone! Analysis complete.")
    
    # Print summary
    print(f"\n=== Summary ===")
    print(f"Matches analyzed: {len(matches_normalized):,}")
    print(f"Patterns found: {len(patterns)}")
    print(f"Tier upset categories: {len(tier_upsets_formatted)}")
    print(f"Specific upset matchups: {len(upset_matchup_analysis)}")
    print(f"Odds edges found: {len(odds_edges)}")
    
    conn.close()

if __name__ == '__main__':
    main()
