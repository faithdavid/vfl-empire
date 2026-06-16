#!/usr/bin/env python3
"""
VFL EV Engine - Chronological Backtesting with Zero Lookahead Bias
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime

# Import components from ev_engine
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from ev_engine import (
    DB_RESULTS, DB_ODDS, DB_EV,
    poisson_pmf, predict_match, calculate_ev
)

def run_backtest(ev_threshold=10.0):
    print(f"Initializing VFL EV Backtesting Engine with EV Threshold >= {ev_threshold}%...")
    print(f"Results DB: {DB_RESULTS}")
    print(f"Odds DB: {DB_ODDS}")
    
    # 1. Connect to Odds DB and load event mapping
    print("Loading event details and matching odds from vfl_odds.db...")
    conn_odds = sqlite3.connect(DB_ODDS)
    cursor_odds = conn_odds.cursor()
    
    # Map (season_name, match_day, home_team, away_team) -> event_id
    cursor_odds.execute("""
        SELECT event_id, season_name, match_day, home_team, away_team 
        FROM event_details;
    """)
    event_rows = cursor_odds.fetchall()
    
    event_map = {}
    for event_id, season, md, home, away in event_rows:
        key = (season, md, home, away)
        event_map[key] = event_id
        
    print(f"Loaded {len(event_map)} event mappings.")
    
    # Load all deep market odds
    print("Loading deep market odds into memory for maximum speed...")
    cursor_odds.execute("""
        SELECT event_id, market_name, specifiers, selection_name, odds 
        FROM deep_markets 
        WHERE market_name IN ('1x2', 'Over/Under', 'GG/NG');
    """)
    odds_rows = cursor_odds.fetchall()
    conn_odds.close()
    
    # Structure: odds_dict[event_id][market_name][specifier][selection_name] = odds
    odds_dict = {}
    for event_id, market_name, specifiers, selection_name, odds in odds_rows:
        if event_id not in odds_dict:
            odds_dict[event_id] = {}
        if market_name not in odds_dict[event_id]:
            odds_dict[event_id][market_name] = {}
            
        spec = specifiers or ""
        if spec not in odds_dict[event_id][market_name]:
            odds_dict[event_id][market_name][spec] = {}
            
        odds_dict[event_id][market_name][spec][selection_name] = odds
        
    print(f"Loaded odds for {len(odds_dict)} unique events.")
    
    # 2. Connect to Results DB and load all matches chronologically
    print("Loading all results chronologically...")
    conn_res = sqlite3.connect(DB_RESULTS)
    cursor_res = conn_res.cursor()
    cursor_res.execute("""
        SELECT season_name, match_day, home_team, away_team, home_goals, away_goals
        FROM results 
        WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
        ORDER BY CAST(SUBSTR(season_name, 6) AS INTEGER) ASC, match_day ASC;
    """)
    all_results = cursor_res.fetchall()
    conn_res.close()
    
    total_matches = len(all_results)
    print(f"Loaded {total_matches} historical results.")
    
    # 3. Initialize running statistics for team strengths (no lookahead bias)
    total_completed_matches = 0
    total_home_goals = 0
    total_away_goals = 0
    
    # Find all unique teams to initialize stats
    teams = set()
    for r in all_results:
        teams.add(r[2])
        teams.add(r[3])
        
    team_stats = {t: {
        'home_played': 0, 'home_scored': 0, 'home_conceded': 0,
        'away_played': 0, 'away_scored': 0, 'away_conceded': 0
    } for t in teams}
    
    # Tracking bets and metrics
    bets_placed = []
    
    # Burn-in period (e.g., let's collect stats for 300 matches before placing bets)
    burn_in_matches = 300
    
    print(f"Starting chronological simulation (burn-in period: {burn_in_matches} matches)...")
    
    for idx, (season, md, home, away, h_goals, a_goals) in enumerate(all_results):
        # Check if we have odds for this match AND we are past burn-in
        key = (season, md, home, away)
        event_id = event_map.get(key)
        
        if event_id and event_id in odds_dict and total_completed_matches >= burn_in_matches:
            # 1. Compute current team strengths BEFORE this match is added to history
            g_avg_home = total_home_goals / total_completed_matches
            g_avg_away = total_away_goals / total_completed_matches
            global_stats = (g_avg_home, g_avg_away)
            
            # Compute strengths dict for just these two teams
            precomputed_strengths = {}
            for t in [home, away]:
                stats = team_stats[t]
                h_played = stats['home_played']
                a_played = stats['away_played']
                
                avg_home_scored = stats['home_scored'] / h_played if h_played > 0 else g_avg_home
                avg_home_conceded = stats['home_conceded'] / h_played if h_played > 0 else g_avg_away
                avg_away_scored = stats['away_scored'] / a_played if a_played > 0 else g_avg_away
                avg_away_conceded = stats['away_conceded'] / a_played if a_played > 0 else g_avg_home
                
                precomputed_strengths[t] = {
                    'home_attack': avg_home_scored / g_avg_home,
                    'home_defense': avg_home_conceded / g_avg_away,
                    'away_attack': avg_away_scored / g_avg_away,
                    'away_defense': avg_away_conceded / g_avg_home
                }
                
            # 2. Predict match
            pred = predict_match(home, away, precomputed_strengths=precomputed_strengths, global_stats=global_stats)
            
            # 3. Retrieve market odds and evaluate EV
            match_odds = odds_dict[event_id]
            
            # Helper to safely get odds list for overround computation
            def get_market_odds_list(market_name, spec, selections):
                try:
                    return [match_odds[market_name][spec][sel] for sel in selections if sel in match_odds[market_name][spec]]
                except KeyError:
                    return []
                    
            # We will evaluate 7 target bets:
            # Format: (bet_name, market_name, specifier, selection_name, our_prob, winning_condition)
            markets_to_evaluate = [
                ('Home', '1x2', '', 'Home', pred['prob_home'], h_goals > a_goals),
                ('Draw', '1x2', '', 'Draw', pred['prob_draw'], h_goals == a_goals),
                ('Away', '1x2', '', 'Away', pred['prob_away'], h_goals < a_goals),
                ('Over 1.5', 'Over/Under', 'total=1.5', 'Over 1.5', pred['prob_o15'], h_goals + a_goals >= 2),
                ('Over 2.5', 'Over/Under', 'total=2.5', 'Over 2.5', pred['prob_o25'], h_goals + a_goals >= 3),
                ('Over 3.5', 'Over/Under', 'total=3.5', 'Over 3.5', pred['prob_o35'], h_goals + a_goals >= 4),
                ('GG', 'GG/NG', '', 'Yes', pred['prob_gg'], h_goals > 0 and a_goals > 0),
            ]
            
            for bet_name, mkt_name, spec, sel_name, our_prob, is_win in markets_to_evaluate:
                try:
                    target_odds = match_odds[mkt_name][spec][sel_name]
                    # Get all odds for this market for margin stripping
                    if mkt_name == '1x2':
                        all_odds = get_market_odds_list('1x2', '', ['Home', 'Draw', 'Away'])
                    elif mkt_name == 'Over/Under':
                        all_odds = get_market_odds_list('Over/Under', spec, [f'Over {spec.split("=")[1]}', f'Under {spec.split("=")[1]}'])
                    elif mkt_name == 'GG/NG':
                        all_odds = get_market_odds_list('GG/NG', '', ['Yes', 'No'])
                    else:
                        all_odds = []
                        
                    ev_res = calculate_ev(target_odds, our_prob, all_odds)
                    
                    if ev_res['ev_pct'] >= ev_threshold:
                        bets_placed.append({
                            'season': season,
                            'match_day': md,
                            'home': home,
                            'away': away,
                            'market': bet_name,
                            'odds': target_odds,
                            'our_prob': our_prob,
                            'ev_pct': ev_res['ev_pct'],
                            'kelly': ev_res['kelly'],
                            'is_win': is_win,
                            'profit_flat': (target_odds - 1.0) if is_win else -1.0,
                            'profit_kelly': (target_odds - 1.0) * ev_res['kelly'] if is_win else -ev_res['kelly']
                        })
                except KeyError:
                    # Odds for this specific market not available for this event
                    continue

        # Update historical stats for next iteration
        total_completed_matches += 1
        total_home_goals += h_goals
        total_away_goals += a_goals
        
        team_stats[home]['home_played'] += 1
        team_stats[home]['home_scored'] += h_goals
        team_stats[home]['home_conceded'] += a_goals
        
        team_stats[away]['away_played'] += 1
        team_stats[away]['away_scored'] += a_goals
        team_stats[away]['away_conceded'] += h_goals

    # 4. Generate Backtest Report
    total_bets = len(bets_placed)
    if total_bets == 0:
        print("No +EV bets found during the backtest period.")
        return
        
    wins = sum(1 for b in bets_placed if b['is_win'])
    losses = total_bets - wins
    win_rate = (wins / total_bets) * 100.0
    
    total_stake_flat = total_bets
    total_profit_flat = sum(b['profit_flat'] for b in bets_placed)
    roi_flat = (total_profit_flat / total_stake_flat) * 100.0
    
    total_stake_kelly = sum(b['kelly'] for b in bets_placed)
    total_profit_kelly = sum(b['profit_kelly'] for b in bets_placed)
    roi_kelly = (total_profit_kelly / total_stake_kelly) * 100.0 if total_stake_kelly > 0 else 0.0
    
    # Group performance by market
    market_stats = {}
    for b in bets_placed:
        m = b['market']
        if m not in market_stats:
            market_stats[m] = {'bets': 0, 'wins': 0, 'profit_flat': 0.0, 'stake_flat': 0.0}
        market_stats[m]['bets'] += 1
        if b['is_win']:
            market_stats[m]['wins'] += 1
        market_stats[m]['profit_flat'] += b['profit_flat']
        market_stats[m]['stake_flat'] += 1.0

    print("\n" + "="*60)
    print("                 VFL EV BACKTEST REPORT")
    print("="*60)
    print(f"Total Matches Analyzed:     {total_matches}")
    print(f"Burn-in Matches (No bets):  {burn_in_matches}")
    print(f"Total +EV Bets Placed:      {total_bets}")
    print(f"Wins / Losses:              {wins} / {losses}")
    print(f"Overall Win Rate:           {win_rate:.2f}%")
    print("-" * 60)
    print(f"Flat Staking ROI:           {roi_flat:.2f}% (Profit: {total_profit_flat:.2f} units)")
    print(f"Half-Kelly Staking ROI:     {roi_kelly:.2f}% (Profit: {total_profit_kelly:.4f} units)")
    print("="*60)
    
    print("\n--- Performance by Market ---")
    print(f"{'Market':<12} | {'Bets':<6} | {'Win Rate':<10} | {'Profit (Flat)':<12} | {'ROI (Flat)'}")
    print("-" * 55)
    for m, stats in sorted(market_stats.items(), key=lambda x: x[1]['profit_flat'], reverse=True):
        m_win_rate = (stats['wins'] / stats['bets']) * 100.0
        m_roi = (stats['profit_flat'] / stats['stake_flat']) * 100.0
        print(f"{m:<12} | {stats['bets']:<6} | {m_win_rate:<9.2f}% | {stats['profit_flat']:<12.2f} | {m_roi:.2f}%")
    print("="*60 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VFL EV Engine Backtest")
    parser.add_argument("--ev-threshold", type=float, default=10.0, help="Minimum EV percentage to place a bet (default: 10.0)")
    args = parser.parse_args()
    
    run_backtest(ev_threshold=args.ev_threshold)
