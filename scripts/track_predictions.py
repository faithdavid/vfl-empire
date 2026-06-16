#!/usr/bin/env python3
"""
VFL EV Engine - Live Prediction Tracking and Settlement
"""

import os
import sys
import sqlite3
import urllib.request
import json
from datetime import datetime

# Import components from ev_engine
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from ev_engine import (
    DB_RESULTS, DB_ODDS, DB_EV,
    predict_match, calculate_ev, init_db
)

def fetch_live_fixtures_and_odds():
    """
    Simulates fetching live fixtures and odds from MSport API / Akamai.
    Falls back to querying the latest upcoming fixtures in vfl_odds.db (e.g. Season 5116)
    that are not yet played/settled in vfl_results.db results table.
    """
    print("Fetching current live fixtures and odds...")
    
    conn_odds = sqlite3.connect(DB_ODDS)
    cursor_odds = conn_odds.cursor()
    
    # Find all event_details for matches that do not yet have results in results.db
    # We can attach results.db to do this cleanly
    cursor_odds.execute(f"ATTACH DATABASE '{DB_RESULTS}' AS results_db;")
    
    cursor_odds.execute("""
        SELECT d.event_id, d.season_name, d.match_day, d.home_team, d.away_team
        FROM event_details d
        LEFT JOIN results_db.results r 
            ON d.season_name = r.season_name 
            AND d.match_day = r.match_day 
            AND d.home_team = r.home_team 
            AND d.away_team = r.away_team
        WHERE r.event_id IS NULL;
    """)
    upcoming_fixtures = cursor_odds.fetchall()
    
    if not upcoming_fixtures:
        print("No upcoming/unplayed fixtures found in the database. Using season 5115 matchday 30 as simulated live matchday.")
        cursor_odds.execute("""
            SELECT event_id, season_name, match_day, home_team, away_team
            FROM event_details
            WHERE season_name = 'VFLM 5115' AND match_day = 30;
        """)
        upcoming_fixtures = cursor_odds.fetchall()
        
    fixtures_data = []
    for event_id, season, md, home, away in upcoming_fixtures:
        # Fetch odds for this event
        cursor_odds.execute("""
            SELECT market_name, specifiers, selection_name, odds 
            FROM deep_markets 
            WHERE event_id = ? AND market_name IN ('1x2', 'Over/Under', 'GG/NG');
        """, (event_id,))
        odds_rows = cursor_odds.fetchall()
        
        # Build odds structure
        odds_map = {}
        for market, spec, sel, odds in odds_rows:
            if market not in odds_map:
                odds_map[market] = {}
            s = spec or ""
            if s not in odds_map[market]:
                odds_map[market][s] = {}
            odds_map[market][s][sel] = odds
            
        fixtures_data.append({
            'event_id': event_id,
            'season_name': season,
            'match_day': md,
            'home_team': home,
            'away_team': away,
            'odds': odds_map
        })
        
    conn_odds.close()
    print(f"Retrieved {len(fixtures_data)} live fixtures with odds.")
    return fixtures_data

def track_live_predictions():
    """
    Predict upcoming matches, evaluate EV, and track bets in tracked_predictions as PENDING.
    """
    init_db()
    fixtures = fetch_live_fixtures_and_odds()
    
    conn_ev = sqlite3.connect(DB_EV)
    cursor_ev = conn_ev.cursor()
    
    # We load global stats to predict matches
    conn_res = sqlite3.connect(DB_RESULTS)
    cursor_res = conn_res.cursor()
    cursor_res.execute("SELECT AVG(home_goals), AVG(away_goals) FROM results WHERE home_goals IS NOT NULL;")
    g_avg_home, g_avg_away = cursor_res.fetchone()
    conn_res.close()
    
    print("\n--- Evaluating Live Predictions for +EV ---")
    
    now_str = datetime.now().isoformat()
    tracked_count = 0
    
    for f in fixtures:
        event_id = f['event_id']
        season = f['season_name']
        md = f['match_day']
        home = f['home_team']
        away = f['away_team']
        odds_map = f['odds']
        
        # Predict match probabilities
        pred = predict_match(home, away, global_stats=(g_avg_home, g_avg_away))
        
        # Build target market list to evaluate
        markets_to_evaluate = [
            ('Home', '1x2', '', 'Home', pred['prob_home']),
            ('Draw', '1x2', '', 'Draw', pred['prob_draw']),
            ('Away', '1x2', '', 'Away', pred['prob_away']),
            ('Over 1.5', 'Over/Under', 'total=1.5', 'Over 1.5', pred['prob_o15']),
            ('Over 2.5', 'Over/Under', 'total=2.5', 'Over 2.5', pred['prob_o25']),
            ('Over 3.5', 'Over/Under', 'total=3.5', 'Over 3.5', pred['prob_o35']),
            ('GG', 'GG/NG', '', 'Yes', pred['prob_gg']),
        ]
        
        for bet_name, mkt_name, spec, sel_name, our_prob in markets_to_evaluate:
            try:
                target_odds = odds_map[mkt_name][spec][sel_name]
                
                # Retrieve all odds for that market to strip overround
                if mkt_name == '1x2':
                    all_odds = [odds_map['1x2'][''][s] for s in ['Home', 'Draw', 'Away'] if s in odds_map['1x2']['']]
                elif mkt_name == 'Over/Under':
                    all_odds = [odds_map['Over/Under'][spec][s] for s in [f'Over {spec.split("=")[1]}', f'Under {spec.split("=")[1]}'] if s in odds_map['Over/Under'][spec]]
                elif mkt_name == 'GG/NG':
                    all_odds = [odds_map['GG/NG'][''][s] for s in ['Yes', 'No'] if s in odds_map['GG/NG']['']]
                else:
                    all_odds = []
                    
                ev_res = calculate_ev(target_odds, our_prob, all_odds)
                
                # Save EV calculation to market_ev for EVERY evaluated market
                cursor_ev.execute("""
                    INSERT INTO market_ev (
                        match_id, season_name, match_day, home_team, away_team,
                        market, market_odds, fair_odds, our_prob, ev_pct, kelly_pct, computed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    event_id, season, md, home, away,
                    bet_name, target_odds, ev_res['fair_odds'], our_prob, ev_res['ev_pct'], ev_res['kelly'], now_str
                ))
                
                # Only keep picks where adjusted EV >= 10.0%
                if ev_res['ev_pct'] >= 10.0:
                    # Check if already tracked to avoid duplicate tracking
                    cursor_ev.execute("""
                        SELECT id FROM tracked_predictions 
                        WHERE match_id = ? AND market = ?;
                    """, (event_id, bet_name))
                    if cursor_ev.fetchone() is None:
                        cursor_ev.execute("""
                            INSERT INTO tracked_predictions (
                                match_id, season_name, match_day, home_team, away_team,
                                market, predicted, odds, confidence, status, tracked_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?);
                        """, (
                            event_id, season, md, home, away,
                            bet_name, sel_name, target_odds, our_prob, now_str
                        ))
                        print(f"Tracked +EV Bet (EV >= 10%): {season} MD {md} - {home} vs {away} | Market: {bet_name} | Odds: {target_odds} | Prob: {our_prob:.2%} | EV: {ev_res['ev_pct']:.1f}%")
                        tracked_count += 1
            except KeyError:
                continue
                
    conn_ev.commit()
    conn_ev.close()
    print(f"Tracking complete. {tracked_count} new +EV predictions tracked as PENDING.")

def settle_predictions():
    """
    Settle PENDING predictions by checking results database.
    """
    init_db()
    conn_ev = sqlite3.connect(DB_EV)
    cursor_ev = conn_ev.cursor()
    
    cursor_ev.execute("""
        SELECT id, season_name, match_day, home_team, away_team, market, odds, confidence
        FROM tracked_predictions 
        WHERE status = 'PENDING';
    """)
    pending_bets = cursor_ev.fetchall()
    
    if not pending_bets:
        print("No PENDING predictions found to settle.")
        conn_ev.close()
        return
        
    print(f"Checking results for {len(pending_bets)} pending predictions...")
    
    conn_res = sqlite3.connect(DB_RESULTS)
    cursor_res = conn_res.cursor()
    
    settled_count = 0
    now_str = datetime.now().isoformat()
    
    for b_id, season, md, home, away, market, odds, conf in pending_bets:
        # Look up result
        cursor_res.execute("""
            SELECT home_goals, away_goals 
            FROM results 
            WHERE season_name = ? AND match_day = ? AND home_team = ? AND away_team = ?;
        """, (season, md, home, away))
        res_row = cursor_res.fetchone()
        
        if res_row is not None:
            h_goals, a_goals = res_row
            actual_res_str = f"{h_goals}-{a_goals}"
            
            # Check if prediction won
            is_correct = 0
            if market == 'Home' and h_goals > a_goals:
                is_correct = 1
            elif market == 'Draw' and h_goals == a_goals:
                is_correct = 1
            elif market == 'Away' and h_goals < a_goals:
                is_correct = 1
            elif market == 'Over 1.5' and h_goals + a_goals >= 2:
                is_correct = 1
            elif market == 'Over 2.5' and h_goals + a_goals >= 3:
                is_correct = 1
            elif market == 'Over 3.5' and h_goals + a_goals >= 4:
                is_correct = 1
            elif market == 'GG' and h_goals > 0 and a_goals > 0:
                is_correct = 1
                
            cursor_ev.execute("""
                UPDATE tracked_predictions
                SET status = 'SETTLED', actual_result = ?, correct = ?, settled_at = ?
                WHERE id = ?;
            """, (actual_res_str, is_correct, now_str, b_id))
            
            status_str = "CORRECT" if is_correct == 1 else "INCORRECT"
            print(f"Settled {season} MD {md} {home} vs {away} ({actual_res_str}) | Bet: {market} | Result: {status_str}")
            settled_count += 1
            
    conn_res.close()
    conn_ev.commit()
    
    # Print statistics
    cursor_ev.execute("SELECT COUNT(*) FROM tracked_predictions WHERE status = 'SETTLED';")
    total_settled = cursor_ev.fetchone()[0]
    
    cursor_ev.execute("SELECT COUNT(*) FROM tracked_predictions WHERE status = 'SETTLED' AND correct = 1;")
    total_correct = cursor_ev.fetchone()[0]
    
    if total_settled > 0:
        accuracy = (total_correct / total_settled) * 100.0
        print("\n--- Running Accuracy Stats ---")
        print(f"Total Settled Predictions: {total_settled}")
        print(f"Correct Predictions:       {total_correct}")
        print(f"Overall Accuracy:          {accuracy:.2f}%")
        print("-------------------------------\n")
    else:
        print("No predictions have been settled yet.")
        
    conn_ev.close()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--settle":
        settle_predictions()
    else:
        # Default behavior: track live predictions
        track_live_predictions()
