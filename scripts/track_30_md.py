#!/usr/bin/env python3
"""
VFL 30-Matchday Tracker and Live Prediction System
"""

import os
import sys
import math
import sqlite3
import urllib.request
import json
import time
import argparse
from datetime import datetime

# Add scripts directory to path to import ev_engine
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPTS_DIR)

from ev_engine import (
    DB_RESULTS, DB_ODDS, DB_EV,
    poisson_pmf, predict_match, calculate_ev, init_db, load_bias_adjustments, compute_global_stats
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Origin': 'https://www.msport.com',
    'Referer': 'https://www.msport.com/ng/virtual/soccer',
}

AKAMAI_LIVE = "https://vfdirectdatalive-vs001.akamaized.net//46215/msportnigeriavflm/en/Europe:Berlin"
MSPORT_INFO = "https://www.msport.com/api/ng/facts-center/query/frontend/virtual/current/match/day/info"

def fetch_api(url, timeout=10):
    """Fetch JSON from MSport or Akamai APIs."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except Exception as e:
        return None

def compute_historical_strengths(target_season, target_md):
    """
    Computes team strengths chronologically using matches prior to target_season & target_md.
    Ensures zero lookahead bias for simulation.
    """
    conn = sqlite3.connect(DB_RESULTS)
    cursor = conn.cursor()
    
    # Load all completed matches before target_season/target_md
    cursor.execute("""
        SELECT season_name, match_day, home_team, away_team, home_goals, away_goals 
        FROM results 
        WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
        ORDER BY CAST(SUBSTR(season_name, 6) AS INTEGER) ASC, match_day ASC;
    """)
    all_matches = cursor.fetchall()
    conn.close()
    
    # Filter matches before target_season, target_md
    target_season_num = int(target_season.replace("VFLM ", ""))
    filtered_matches = []
    
    for season, md, home, away, h_goals, a_goals in all_matches:
        s_num = int(season.replace("VFLM ", ""))
        if s_num < target_season_num or (s_num == target_season_num and md < target_md):
            filtered_matches.append((home, away, h_goals, a_goals))
            
    total_matches = len(filtered_matches)
    if total_matches == 0:
        return None, (1.1, 1.1) # Safe fallback
        
    total_home_goals = sum(m[2] for m in filtered_matches)
    total_away_goals = sum(m[3] for m in filtered_matches)
    
    g_avg_home = total_home_goals / total_matches
    g_avg_away = total_away_goals / total_matches
    
    # Group team stats
    teams = set()
    for m in filtered_matches:
        teams.add(m[0])
        teams.add(m[1])
        
    team_stats = {t: {
        'home_played': 0, 'home_scored': 0, 'home_conceded': 0,
        'away_played': 0, 'away_scored': 0, 'away_conceded': 0
    } for t in teams}
    
    for home, away, h_goals, a_goals in filtered_matches:
        team_stats[home]['home_played'] += 1
        team_stats[home]['home_scored'] += h_goals
        team_stats[home]['home_conceded'] += a_goals
        
        team_stats[away]['away_played'] += 1
        team_stats[away]['away_scored'] += a_goals
        team_stats[away]['away_conceded'] += h_goals
        
    precomputed_strengths = {}
    for t, stats in team_stats.items():
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
        
    return precomputed_strengths, (g_avg_home, g_avg_away)

def run_30md_simulation(season_name="VFLM 5115"):
    """
    Simulates prediction and tracking across 30 consecutive matchdays of a historical season.
    Generates a high-fidelity report detailing ROI, market-specific performance, and MD hit-distribution.
    """
    print(f"\n========================================================")
    print(f"       RUNNING 30-MATCHDAY SIMULATION ON {season_name}")
    print(f"========================================================\n")
    
    conn_odds = sqlite3.connect(DB_ODDS)
    cursor_odds = conn_odds.cursor()
    
    # Fetch all fixtures on this season
    cursor_odds.execute("""
        SELECT event_id, match_day, home_team, away_team 
        FROM event_details 
        WHERE season_name = ?
        ORDER BY match_day ASC;
    """, (season_name,))
    all_fixtures = cursor_odds.fetchall()
    
    if not all_fixtures:
        print(f"Error: No fixtures found for season {season_name} in vfl_odds.db.")
        conn_odds.close()
        return
        
    # Group fixtures by matchday
    md_fixtures = {}
    for ev_id, md, home, away in all_fixtures:
        if md not in md_fixtures:
            md_fixtures[md] = []
        md_fixtures[md].append((ev_id, home, away))
        
    # Connect to Results DB for actual settlement
    conn_res = sqlite3.connect(DB_RESULTS)
    cursor_res = conn_res.cursor()
    
    # Tracker metrics
    mds_tracked = 0
    picks_placed = []
    
    md_hit_counts = {3: 0, 2: 0, 1: 0, 0: 0}
    
    print(f"Simulating {len(md_fixtures)} matchdays...")
    
    for md in sorted(md_fixtures.keys()):
        fixtures = md_fixtures[md]
        
        # 1. Compute zero-lookahead strengths prior to this MD
        strengths, g_stats = compute_historical_strengths(season_name, md)
        
        candidates = []
        
        for ev_id, home, away in fixtures:
            # Predict probabilities
            pred = predict_match(home, away, precomputed_strengths=strengths, global_stats=g_stats)
            
            # Fetch odds
            cursor_odds.execute("""
                SELECT market_name, specifiers, selection_name, odds 
                FROM deep_markets 
                WHERE event_id = ? AND market_name IN ('1x2', 'Over/Under', 'GG/NG', 'Double Chance');
            """, (ev_id,))
            odds_rows = cursor_odds.fetchall()
            
            # Build odds maps
            odds_map = {}
            for market, spec, sel, odds in odds_rows:
                if market not in odds_map:
                    odds_map[market] = {}
                s = spec or ""
                if s not in odds_map[market]:
                    odds_map[market][s] = {}
                odds_map[market][s][sel] = odds
                
            # Helper to retrieve market odds lists for overround correction
            def get_odds_list(mkt, spec, sels):
                try:
                    return [odds_map[mkt][spec][sel] for sel in sels if sel in odds_map[mkt][spec]]
                except KeyError:
                    return []
                    
            # 1. Evaluate Over 1.5
            try:
                odds_o15 = odds_map['Over/Under']['total=1.5']['Over 1.5']
                all_o15 = get_odds_list('Over/Under', 'total=1.5', ['Over 1.5', 'Under 1.5'])
                ev_o15 = calculate_ev(odds_o15, pred['prob_o15'], all_o15)
                candidates.append({
                    'ev_id': ev_id, 'home': home, 'away': away,
                    'market': 'Over 1.5', 'selection': 'Over 1.5',
                    'odds': odds_o15, 'our_prob': pred['prob_o15'],
                    'ev_pct': ev_o15['ev_pct'], 'kelly': ev_o15['kelly']
                })
            except KeyError:
                pass
                
            # 2. Evaluate Over 2.5
            try:
                odds_o25 = odds_map['Over/Under']['total=2.5']['Over 2.5']
                all_o25 = get_odds_list('Over/Under', 'total=2.5', ['Over 2.5', 'Under 2.5'])
                ev_o25 = calculate_ev(odds_o25, pred['prob_o25'], all_o25)
                candidates.append({
                    'ev_id': ev_id, 'home': home, 'away': away,
                    'market': 'Over 2.5', 'selection': 'Over 2.5',
                    'odds': odds_o25, 'our_prob': pred['prob_o25'],
                    'ev_pct': ev_o25['ev_pct'], 'kelly': ev_o25['kelly']
                })
            except KeyError:
                pass
                
            # 3. Evaluate GG
            try:
                odds_gg = odds_map['GG/NG']['']['Yes']
                all_gg = get_odds_list('GG/NG', '', ['Yes', 'No'])
                ev_gg = calculate_ev(odds_gg, pred['prob_gg'], all_gg)
                candidates.append({
                    'ev_id': ev_id, 'home': home, 'away': away,
                    'market': 'GG', 'selection': 'Yes',
                    'odds': odds_gg, 'our_prob': pred['prob_gg'],
                    'ev_pct': ev_gg['ev_pct'], 'kelly': ev_gg['kelly']
                })
            except KeyError:
                pass
                
            # 4. Evaluate Double Chance
            dc_selections = [
                ('1 X', 'Double Chance (1 X)', pred['prob_home'] + pred['prob_draw']),
                ('1 2', 'Double Chance (1 2)', pred['prob_home'] + pred['prob_away']),
                ('X 2', 'Double Chance (X 2)', pred['prob_draw'] + pred['prob_away'])
            ]
            for sel_code, mkt_name, prob_val in dc_selections:
                try:
                    odds_dc = odds_map['Double Chance'][''][sel_code]
                    all_dc = get_odds_list('Double Chance', '', ['1 X', '1 2', 'X 2'])
                    ev_dc = calculate_ev(odds_dc, prob_val, all_dc)
                    candidates.append({
                        'ev_id': ev_id, 'home': home, 'away': away,
                        'market': mkt_name, 'selection': sel_code,
                        'odds': odds_dc, 'our_prob': prob_val,
                        'ev_pct': ev_dc['ev_pct'], 'kelly': ev_dc['kelly']
                    })
                except KeyError:
                    pass
        # Save EV calculation to market_ev for EVERY evaluated market
        init_db()
        conn_ev = sqlite3.connect(DB_EV)
        cursor_ev = conn_ev.cursor()
        now_str = datetime.now().isoformat()
        for c in candidates:
            cursor_ev.execute("""
                INSERT INTO market_ev (
                    match_id, season_name, match_day, home_team, away_team,
                    market, market_odds, fair_odds, our_prob, ev_pct, kelly_pct, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                c['ev_id'], season_name, md, c['home'], c['away'],
                c['market'], c['odds'], 1.0 / c['our_prob'] if c['our_prob'] > 0 else 0.0,
                c['our_prob'], c['ev_pct'], c['kelly'], now_str
            ))
        conn_ev.commit()
        conn_ev.close()

        # Apply filter: only keep picks where adjusted EV >= 10.0%
        valid_picks = [c for c in candidates if c['ev_pct'] >= 10.0]
        
        # Select up to 3 BEST picks based on highest confidence (our_prob)
        best_3_picks = sorted(valid_picks, key=lambda x: x['our_prob'], reverse=True)[:3]
        
        if len(best_3_picks) > 0:
            md_correct_count = 0
            
            # Settle each of the selected best picks
            for pick in best_3_picks:
                pick['match_day'] = md
                cursor_res.execute("""
                    SELECT home_goals, away_goals 
                    FROM results 
                    WHERE season_name = ? AND match_day = ? AND home_team = ? AND away_team = ?;
                """, (season_name, md, pick['home'], pick['away']))
                res_row = cursor_res.fetchone()
                
                if res_row is not None:
                    h_goals, a_goals = res_row
                    is_win = False
                    
                    if pick['market'] == 'Over 1.5' and h_goals + a_goals >= 2:
                        is_win = True
                    elif pick['market'] == 'Over 2.5' and h_goals + a_goals >= 3:
                        is_win = True
                    elif pick['market'] == 'GG' and h_goals > 0 and a_goals > 0:
                        is_win = True
                    elif pick['market'] == 'Double Chance (1 X)' and h_goals >= a_goals:
                        is_win = True
                    elif pick['market'] == 'Double Chance (1 2)' and h_goals != a_goals:
                        is_win = True
                    elif pick['market'] == 'Double Chance (X 2)' and h_goals <= a_goals:
                        is_win = True
                        
                    profit_flat = (pick['odds'] - 1.0) if is_win else -1.0
                    pick['is_win'] = is_win
                    pick['profit_flat'] = profit_flat
                    pick['result_str'] = f"{h_goals}-{a_goals}"
                    
                    picks_placed.append(pick)
                    if is_win:
                        md_correct_count += 1
                        
            if len(best_3_picks) == 3:
                md_hit_counts[md_correct_count] += 1
                
            mds_tracked += 1
            
    conn_odds.close()
    conn_res.close()
    
    # 4. Generate Backtest Report
    total_bets = len(picks_placed)
    if total_bets == 0:
        print("No picks met the EV >= 10.0% criterion in this season.")
        return
        
    wins = sum(1 for p in picks_placed if p['is_win'])
    losses = total_bets - wins
    overall_hit_rate = (wins / total_bets) * 100.0
    
    total_spent = total_bets
    total_returned = sum(p['odds'] for p in picks_placed if p['is_win'])
    total_profit = total_returned - total_spent
    roi = (total_profit / total_spent) * 100.0
    
    # Group by market
    market_stats = {}
    for p in picks_placed:
        m = p['market']
        if m not in market_stats:
            market_stats[m] = {'bets': 0, 'wins': 0, 'profit': 0.0}
        market_stats[m]['bets'] += 1
        if p['is_win']:
            market_stats[m]['wins'] += 1
        market_stats[m]['profit'] += p['profit_flat']
        
    # Display the results
    print("\n" + "="*70)
    print(f"            30-MATCHDAY TRACKER SIMULATION REPORT ({season_name})")
    print("="*70)
    print(f"Total Matchdays Simulated:    {mds_tracked}")
    print(f"Total Picks Placed (Max 3/MD): {total_bets}")
    print(f"Wins / Losses:                 {wins} / {losses}")
    print(f"Overall Pick Hit Rate:         {overall_hit_rate:.2f}%")
    print(f"Net Profit:                    {total_profit:+.2f} units (Flat 1-Unit Stakes)")
    print(f"Total Return on Investment:    {roi:+.2f}%")
    print("-" * 70)
    
    print("\n--- Matchday Pick Hit Distribution ---")
    total_full_mds = sum(md_hit_counts.values())
    for hits in [3, 2, 1, 0]:
        count = md_hit_counts[hits]
        pct = (count / total_full_mds * 100) if total_full_mds > 0 else 0.0
        print(f"  {hits}/3 picks correct: {count:<2} matchdays ({pct:.1f}%)")
    print("-" * 70)
    
    print("\n--- Market-Specific Breakdown ---")
    print(f"{'Market Category':<24} | {'Picks':<6} | {'Hit Rate':<10} | {'ROI (Flat)'}")
    print("-" * 62)
    for m, stats in sorted(market_stats.items(), key=lambda x: x[1]['profit'], reverse=True):
        m_hit_rate = (stats['wins'] / stats['bets']) * 100.0
        m_roi = (stats['profit'] / stats['bets']) * 100.0
        print(f"{m:<24} | {stats['bets']:<6} | {m_hit_rate:<9.2f}% | {m_roi:+.2f}%")
    print("="*70 + "\n")
    
    # Save the tracked predictions to the database as SETTLED simulation records
    init_db()
    conn_ev = sqlite3.connect(DB_EV)
    cursor_ev = conn_ev.cursor()
    
    saved_count = 0
    now_str = datetime.now().isoformat()
    
    for pick in picks_placed:
        # Check if already tracked to avoid duplicate simulation logs
        cursor_ev.execute("""
            SELECT id FROM tracked_predictions 
            WHERE season_name = ? AND match_day = ? AND home_team = ? AND market = ?;
        """, (season_name, pick['match_day'], pick['home'], pick['market']))
        if cursor_ev.fetchone() is None:
            cursor_ev.execute("""
                INSERT INTO tracked_predictions (
                    match_id, season_name, match_day, home_team, away_team,
                    market, predicted, odds, confidence, status, actual_result, correct, tracked_at, settled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'SETTLED', ?, ?, ?, ?);
            """, (
                pick['ev_id'], season_name, pick['match_day'], pick['home'], pick['away'],
                pick['market'], pick['selection'], pick['odds'], pick['our_prob'],
                pick['result_str'], 1 if pick['is_win'] else 0, now_str, now_str
            ))
            saved_count += 1
            
    conn_ev.commit()
    conn_ev.close()
    if saved_count > 0:
        print(f"Log: Saved {saved_count} settled simulation predictions to tracked_predictions in vfl_ev.db.")

def get_current_matchday():
    """Retrieve the current active matchday from the MSport API."""
    info = fetch_api(MSPORT_INFO)
    if info and info.get('data'):
        return info['data'].get('seasonId', '').replace("vf:season:", "VFLM "), info['data'].get('matchDay')
    return None, None

def run_live_tracker():
    """
    Continuous monitor check. Run every 2 minutes or on invocation.
    Pulls live matchday, evaluates EV with bias adjustments, picks top 3,
    and settles any pending previous matchdays automatically.
    """
    init_db()
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⏳ Running Live EV Prediction & Settlement Cycle...")
    
    # 1. Self-settling: detect completed matchdays and settle pending entries in DB
    conn_ev = sqlite3.connect(DB_EV)
    cursor_ev = conn_ev.cursor()
    cursor_ev.execute("SELECT DISTINCT season_name, match_day FROM tracked_predictions WHERE status = 'PENDING';")
    pending_days = cursor_ev.fetchall()
    conn_ev.close()
    
    if pending_days:
        print(f"Found pending days to auto-settle: {pending_days}")
        conn_res = sqlite3.connect(DB_RESULTS)
        cursor_res = conn_res.cursor()
        conn_ev = sqlite3.connect(DB_EV)
        cursor_ev = conn_ev.cursor()
        
        now_str = datetime.now().isoformat()
        settled_any = False
        
        for p_season, p_md in pending_days:
            # Check if results are populated for this matchday
            cursor_res.execute("SELECT COUNT(*) FROM results WHERE season_name = ? AND match_day = ? AND home_goals IS NOT NULL;", (p_season, p_md))
            completed_matches = cursor_res.fetchone()[0]
            
            if completed_matches >= 8: # A matchday has 8 matches
                print(f"Settle trigger: Results are complete in vfl_results.db for {p_season} Matchday {p_md}!")
                
                cursor_ev.execute("""
                    SELECT id, home_team, away_team, market, odds 
                    FROM tracked_predictions 
                    WHERE season_name = ? AND match_day = ? AND status = 'PENDING';
                """, (p_season, p_md))
                pending_picks = cursor_ev.fetchall()
                
                for p_id, home, away, market, odds in pending_picks:
                    cursor_res.execute("""
                        SELECT home_goals, away_goals 
                        FROM results 
                        WHERE season_name = ? AND match_day = ? AND home_team = ? AND away_team = ?;
                    """, (p_season, p_md, home, away))
                    res_row = cursor_res.fetchone()
                    
                    if res_row:
                        h_goals, a_goals = res_row
                        is_win = False
                        
                        if market == 'Over 1.5' and h_goals + a_goals >= 2:
                            is_win = True
                        elif market == 'Over 2.5' and h_goals + a_goals >= 3:
                            is_win = True
                        elif market == 'GG' and h_goals > 0 and a_goals > 0:
                            is_win = True
                        elif market == 'Double Chance (1 X)' and h_goals >= a_goals:
                            is_win = True
                        elif market == 'Double Chance (1 2)' and h_goals != a_goals:
                            is_win = True
                        elif market == 'Double Chance (X 2)' and h_goals <= a_goals:
                            is_win = True
                            
                        cursor_ev.execute("""
                            UPDATE tracked_predictions
                            SET status = 'SETTLED', actual_result = ?, correct = ?, settled_at = ?
                            WHERE id = ?;
                        """, (f"{h_goals}-{a_goals}", 1 if is_win else 0, now_str, p_id))
                        print(f"🏆 Settled: {p_season} MD {p_md} - {home} vs {away} ({h_goals}-{a_goals}) | Pick: {market} | Result: {'WIN' if is_win else 'LOSS'}")
                        settled_any = True
                        
        conn_res.close()
        conn_ev.commit()
        conn_ev.close()
        
    # 2. Run EV engine on upcoming/current matchday
    season, md = get_current_matchday()
    if not season:
        print("Could not retrieve current matchday from MSport. Fallback: looking for upcoming/unplayed days in vfl_odds.db...")
        # Fallback to database unplayed days
        conn_odds = sqlite3.connect(DB_ODDS)
        cursor_odds = conn_odds.cursor()
        cursor_odds.execute("ATTACH DATABASE ? AS results_db;", (DB_RESULTS,))
        cursor_odds.execute("""
            SELECT d.season_name, d.match_day 
            FROM event_details d
            LEFT JOIN results r 
                ON d.season_name = r.season_name 
                AND d.match_day = r.match_day 
                AND d.home_team = r.home_team 
                AND d.away_team = r.away_team
            WHERE r.event_id IS NULL
            ORDER BY CAST(SUBSTR(d.season_name, 6) AS INTEGER) ASC, d.match_day ASC
            LIMIT 1;
        """)
        row = cursor_odds.fetchone()
        conn_odds.close()
        if row:
            season, md = row
            print(f"Fallback selected unplayed: {season} Matchday {md}")
        else:
            print("No unplayed matchdays found in the system.")
            return
            
    print(f"Upcoming/Current Matchday: {season} Matchday {md}")
    
    # Check if we already predicted this matchday
    conn_ev = sqlite3.connect(DB_EV)
    cursor_ev = conn_ev.cursor()
    cursor_ev.execute("SELECT COUNT(*) FROM tracked_predictions WHERE season_name = ? AND match_day = ?;", (season, md))
    already_predicted = cursor_ev.fetchone()[0]
    conn_ev.close()
    
    if already_predicted > 0:
        print(f"Matchday {season} MD {md} is already predicted and tracked. Standing by for settlement...")
        return
        
    # Generate predictions
    conn_odds = sqlite3.connect(DB_ODDS)
    cursor_odds = conn_odds.cursor()
    cursor_odds.execute("""
        SELECT event_id, home_team, away_team 
        FROM event_details 
        WHERE season_name = ? AND match_day = ?;
    """, (season, md))
    fixtures = cursor_odds.fetchall()
    
    if not fixtures:
        print(f"No fixtures found for {season} Matchday {md} in vfl_odds.db.")
        conn_odds.close()
        return
        
    # Get current global stats
    conn_res = sqlite3.connect(DB_RESULTS)
    g_avg_home, g_avg_away, _ = compute_global_stats(conn_res, verbose=False)
    conn_res.close()
    
    candidates = []
    now_str = datetime.now().isoformat()
    
    for ev_id, home, away in fixtures:
        pred = predict_match(home, away, global_stats=(g_avg_home, g_avg_away))
        
        # Load odds for this fixture
        cursor_odds.execute("""
            SELECT market_name, specifiers, selection_name, odds 
            FROM deep_markets 
            WHERE event_id = ? AND market_name IN ('1x2', 'Over/Under', 'GG/NG', 'Double Chance');
        """, (ev_id,))
        odds_rows = cursor_odds.fetchall()
        
        # Build odds maps
        odds_map = {}
        for market, spec, sel, odds in odds_rows:
            if market not in odds_map:
                odds_map[market] = {}
            s = spec or ""
            if s not in odds_map[market]:
                odds_map[market][s] = {}
            odds_map[market][s][sel] = odds
            
        def get_odds_list(mkt, spec, sels):
            try:
                return [odds_map[mkt][spec][sel] for sel in sels if sel in odds_map[mkt][spec]]
            except KeyError:
                return []
                
        # 1. Evaluate Over 1.5
        try:
            odds_o15 = odds_map['Over/Under']['total=1.5']['Over 1.5']
            all_o15 = get_odds_list('Over/Under', 'total=1.5', ['Over 1.5', 'Under 1.5'])
            ev_o15 = calculate_ev(odds_o15, pred['prob_o15'], all_o15)
            candidates.append({
                'ev_id': ev_id, 'home': home, 'away': away,
                'market': 'Over 1.5', 'selection': 'Over 1.5',
                'odds': odds_o15, 'our_prob': pred['prob_o15'],
                'ev_pct': ev_o15['ev_pct'], 'kelly': ev_o15['kelly']
            })
        except KeyError:
            pass
            
        # 2. Evaluate Over 2.5
        try:
            odds_o25 = odds_map['Over/Under']['total=2.5']['Over 2.5']
            all_o25 = get_odds_list('Over/Under', 'total=2.5', ['Over 2.5', 'Under 2.5'])
            ev_o25 = calculate_ev(odds_o25, pred['prob_o25'], all_o25)
            candidates.append({
                'ev_id': ev_id, 'home': home, 'away': away,
                'market': 'Over 2.5', 'selection': 'Over 2.5',
                'odds': odds_o25, 'our_prob': pred['prob_o25'],
                'ev_pct': ev_o25['ev_pct'], 'kelly': ev_o25['kelly']
            })
        except KeyError:
            pass
            
        # 3. Evaluate GG
        try:
            odds_gg = odds_map['GG/NG']['']['Yes']
            all_gg = get_odds_list('GG/NG', '', ['Yes', 'No'])
            ev_gg = calculate_ev(odds_gg, pred['prob_gg'], all_gg)
            candidates.append({
                'ev_id': ev_id, 'home': home, 'away': away,
                'market': 'GG', 'selection': 'Yes',
                'odds': odds_gg, 'our_prob': pred['prob_gg'],
                'ev_pct': ev_gg['ev_pct'], 'kelly': ev_gg['kelly']
            })
        except KeyError:
            pass
            
        # 4. Evaluate Double Chance
        dc_selections = [
            ('1 X', 'Double Chance (1 X)', pred['prob_home'] + pred['prob_draw']),
            ('1 2', 'Double Chance (1 2)', pred['prob_home'] + pred['prob_away']),
            ('X 2', 'Double Chance (X 2)', pred['prob_draw'] + pred['prob_away'])
        ]
        for sel_code, mkt_name, prob_val in dc_selections:
            try:
                odds_dc = odds_map['Double Chance'][''][sel_code]
                all_dc = get_odds_list('Double Chance', '', ['1 X', '1 2', 'X 2'])
                ev_dc = calculate_ev(odds_dc, prob_val, all_dc)
                candidates.append({
                    'ev_id': ev_id, 'home': home, 'away': away,
                    'market': mkt_name, 'selection': sel_code,
                    'odds': odds_dc, 'our_prob': prob_val,
                    'ev_pct': ev_dc['ev_pct'], 'kelly': ev_dc['kelly']
                })
            except KeyError:
                pass
                
    conn_odds.close()
    
    # Save EV calculation to market_ev for EVERY evaluated market
    conn_ev = sqlite3.connect(DB_EV)
    cursor_ev = conn_ev.cursor()
    for c in candidates:
        cursor_ev.execute("""
            INSERT INTO market_ev (
                match_id, season_name, match_day, home_team, away_team,
                market, market_odds, fair_odds, our_prob, ev_pct, kelly_pct, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            c['ev_id'], season, md, c['home'], c['away'],
            c['market'], c['odds'], 1.0 / c['our_prob'] if c['our_prob'] > 0 else 0.0,
            c['our_prob'], c['ev_pct'], c['kelly'], now_str
        ))
        
    # Apply filter: only keep picks where adjusted EV >= 10.0%
    valid_picks = [c for c in candidates if c['ev_pct'] >= 10.0]
    
    # Select up to 3 BEST picks based on highest confidence (our_prob)
    best_3_picks = sorted(valid_picks, key=lambda x: x['our_prob'], reverse=True)[:3]
    
    saved_count = 0
    if len(best_3_picks) > 0:
        for pick in best_3_picks:
            cursor_ev.execute("""
                INSERT INTO tracked_predictions (
                    match_id, season_name, match_day, home_team, away_team,
                    market, predicted, odds, confidence, status, tracked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?);
            """, (
                pick['ev_id'], season, md, pick['home'], pick['away'],
                pick['market'], pick['selection'], pick['odds'], pick['our_prob'], now_str
            ))
            print(f"🚀 LIVE Tracked Best Pick: {season} MD {md} | {pick['home']} vs {pick['away']} | Market: {pick['market']} | Odds: {pick['odds']} | Conf: {pick['our_prob']:.1%} | EV: {pick['ev_pct']:.1f}%")
            saved_count += 1
            
    conn_ev.commit()
    conn_ev.close()
    print(f"Cycle completed. Saved {saved_count} best live predictions as PENDING.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VFL 30-Matchday Tracker and Live Prediction System")
    parser.add_argument("--sim", action="store_true", help="Run historical simulation mode")
    parser.add_argument("--season", type=str, default="VFLM 5115", help="Season to simulate (default: VFLM 5115)")
    parser.add_argument("--live", action="store_true", help="Run in continuous live mode")
    args = parser.parse_args()
    
    if args.sim:
        run_30md_simulation(season_name=args.season)
    elif args.live:
        print("Starting continuous live tracker loop (press Ctrl+C to stop)...")
        while True:
            try:
                run_live_tracker()
            except Exception as e:
                print(f"⚠️ Live Loop Error: {e}")
            time.sleep(120) # Loop every 2 minutes
    else:
        # Default behavior: run a single live tracker check/cycle
        run_live_tracker()
