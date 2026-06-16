#!/usr/bin/env python3
"""
VFL EV Engine - Core Poisson Probability Engine
"""

import os
import sys
import math
import sqlite3
import argparse
import json
from datetime import datetime

# =====================================================================
# PART A: Database Connection & Setup
# =====================================================================
DB_RESULTS = os.path.expanduser("~/faith-workspace/vfl-complete-data/databases/vfl_results.db")
DB_ODDS = os.path.expanduser("~/faith-workspace/vfl-complete-data/databases/vfl_odds.db")
DB_EV = os.path.expanduser("~/faith-workspace/vfl-empire/databases/vfl_ev.db")

def init_db():
    """Create the vfl_ev.db database and tables if they do not exist."""
    db_dir = os.path.dirname(DB_EV)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        
    conn = sqlite3.connect(DB_EV)
    cursor = conn.cursor()
    
    # 1. team_strengths
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS team_strengths (
        team_name TEXT PRIMARY KEY,
        home_attack REAL,
        home_defense REAL,
        away_attack REAL,
        away_defense REAL,
        sample_size INTEGER,
        last_updated TEXT
    );
    """)
    
    # 2. match_predictions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS match_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_name TEXT,
        match_day INTEGER,
        home_team TEXT,
        away_team TEXT,
        lambda_home REAL,
        lambda_away REAL,
        prob_o15 REAL,
        prob_o25 REAL,
        prob_o35 REAL,
        prob_gg REAL,
        prob_home REAL,
        prob_draw REAL,
        prob_away REAL,
        computed_at TEXT
    );
    """)
    
    # 3. market_ev
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS market_ev (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT,
        season_name TEXT,
        match_day INTEGER,
        home_team TEXT,
        away_team TEXT,
        market TEXT,
        market_odds REAL,
        fair_odds REAL,
        our_prob REAL,
        ev_pct REAL,
        kelly_pct REAL,
        computed_at TEXT
    );
    """)
    
    # 4. tracked_predictions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tracked_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT,
        season_name TEXT,
        match_day INTEGER,
        home_team TEXT,
        away_team TEXT,
        market TEXT,
        predicted TEXT,
        odds REAL,
        confidence REAL,
        status TEXT DEFAULT 'PENDING',
        actual_result TEXT,
        correct INTEGER,
        tracked_at TEXT,
        settled_at TEXT
    );
    """)
    
    conn.commit()
    conn.close()

# =====================================================================
# PART B: Global Statistics
# =====================================================================
def compute_global_stats(conn=None, verbose=False):
    """
    Read ALL completed rows from vfl_results.db.
    Compute & return: avg_home_goals, avg_away_goals, total_matches
    """
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(DB_RESULTS)
        close_conn = True
        
    cursor = conn.cursor()
    cursor.execute("""
        SELECT home_goals, away_goals 
        FROM results 
        WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL;
    """)
    rows = cursor.fetchall()
    
    if close_conn:
        conn.close()
        
    total_matches = len(rows)
    if total_matches == 0:
        if verbose:
            print("No completed matches found in vfl_results.db.")
        return 0.0, 0.0, 0
        
    total_home_goals = sum(r[0] for r in rows)
    total_away_goals = sum(r[1] for r in rows)
    
    avg_home_goals = total_home_goals / total_matches
    avg_away_goals = total_away_goals / total_matches
    
    if verbose:
        print(f"--- Global Statistics ---")
        print(f"Total Completed Matches: {total_matches}")
        print(f"Average Home Goals: {avg_home_goals:.4f}")
        print(f"Average Away Goals: {avg_away_goals:.4f}")
        print(f"-------------------------")
    
    return avg_home_goals, avg_away_goals, total_matches

# =====================================================================
# PART C: Team Strengths
# =====================================================================
def build_team_strengths(conn_results=None, conn_ev=None):
    """
    For each of the 16 teams, compute:
    home_attack, home_defense, away_attack, away_defense.
    Store results in vfl_ev.db team_strengths table.
    """
    init_db()
    
    close_results = False
    if conn_results is None:
        conn_results = sqlite3.connect(DB_RESULTS)
        close_results = True
        
    close_ev = False
    if conn_ev is None:
        conn_ev = sqlite3.connect(DB_EV)
        close_ev = True
        
    # Get global averages first
    global_avg_home, global_avg_away, total_matches = compute_global_stats(conn_results, verbose=True)
    if total_matches == 0:
        return
        
    # Fetch all completed matches
    cursor_res = conn_results.cursor()
    cursor_res.execute("""
        SELECT home_team, away_team, home_goals, away_goals 
        FROM results 
        WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL;
    """)
    matches = cursor_res.fetchall()
    
    if close_results:
        conn_results.close()
        
    # Get all distinct teams
    teams = set()
    for m in matches:
        teams.add(m[0])
        teams.add(m[1])
        
    # Initialize team-specific accumulators
    # team -> {home_played, home_scored, home_conceded, away_played, away_scored, away_conceded}
    team_stats = {t: {
        'home_played': 0, 'home_scored': 0, 'home_conceded': 0,
        'away_played': 0, 'away_scored': 0, 'away_conceded': 0
    } for t in teams}
    
    for h_team, a_team, h_goals, a_goals in matches:
        team_stats[h_team]['home_played'] += 1
        team_stats[h_team]['home_scored'] += h_goals
        team_stats[h_team]['home_conceded'] += a_goals
        
        team_stats[a_team]['away_played'] += 1
        team_stats[a_team]['away_scored'] += a_goals
        team_stats[a_team]['away_conceded'] += h_goals

    cursor_ev = conn_ev.cursor()
    
    # Prepare update time
    now_str = datetime.now().isoformat()
    
    print("\n--- Team Strengths Built ---")
    print(f"{'Team Name':<20} | {'Home Att':<8} | {'Home Def':<8} | {'Away Att':<8} | {'Away Def':<8} | {'Sample'}")
    print("-" * 72)
    
    for team, stats in team_stats.items():
        h_played = stats['home_played']
        a_played = stats['away_played']
        sample_size = h_played + a_played
        
        avg_home_goals_scored = stats['home_scored'] / h_played if h_played > 0 else global_avg_home
        avg_home_goals_conceded = stats['home_conceded'] / h_played if h_played > 0 else global_avg_away
        avg_away_goals_scored = stats['away_scored'] / a_played if a_played > 0 else global_avg_away
        avg_away_goals_conceded = stats['away_conceded'] / a_played if a_played > 0 else global_avg_home
        
        home_attack = avg_home_goals_scored / global_avg_home
        home_defense = avg_home_goals_conceded / global_avg_away
        away_attack = avg_away_goals_scored / global_avg_away
        away_defense = avg_away_goals_conceded / global_avg_home
        
        # Save to database
        cursor_ev.execute("""
            INSERT OR REPLACE INTO team_strengths (
                team_name, home_attack, home_defense, away_attack, away_defense, sample_size, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (team, home_attack, home_defense, away_attack, away_defense, sample_size, now_str))
        
        print(f"{team:<20} | {home_attack:<8.4f} | {home_defense:<8.4f} | {away_attack:<8.4f} | {away_defense:<8.4f} | {sample_size}")
        
    conn_ev.commit()
    if close_ev:
        conn_ev.close()
        
    print("----------------------------\nTeam strengths have been stored successfully.")

# =====================================================================
# PART D: Poisson Prediction
# =====================================================================
def poisson_pmf(k, lam):
    """Poisson probability mass function."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam**k * math.exp(-lam)) / math.factorial(k)

def load_bias_adjustments():
    """Load bias adjustments from JSON file, with a robust fallback."""
    path = os.path.expanduser("~/faith-workspace/vfl-empire/data/bias_adjustments.json")
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            pass
            
    # Robust fallback matching requested JSON
    return {
      "team_bias_home_goals": {
        "Manchester Blue": 0.233,
        "Manchester Red": 0.174,
        "Liverpool": 0.195,
        "London Guns": 0.134,
        "Tottenham": -0.170,
        "Everton": -0.098
      },
      "team_bias_away_goals": {
        "Manchester Red": 0.122,
        "London Guns": 0.060,
        "Everton": -0.051
      },
      "team_bias_o25": {
        "Brighton": 0.078,
        "Crystal Palace": 0.059,
        "Wolverhampton": 0.040,
        "Bournemouth": -0.024
      },
      "team_bias_gg": {
        "Brighton": 0.073,
        "Wolverhampton": 0.064,
        "Crystal Palace": 0.057
      }
    }

def predict_match(home_team, away_team, season_name=None, match_day=None, conn_ev=None, precomputed_strengths=None, global_stats=None):
    """
    Predict a match using team strengths and Poisson distribution.
    If precomputed_strengths is provided, uses that (no lookahead bias).
    Otherwise, loads from vfl_ev.db.
    Applies team bias adjustments to expected goals and market probabilities.
    """
    if global_stats is None:
        # Load from results DB
        conn_results = sqlite3.connect(DB_RESULTS)
        global_avg_home, global_avg_away, _ = compute_global_stats(conn_results, verbose=False)
        conn_results.close()
    else:
        global_avg_home, global_avg_away = global_stats
        
    # Get strengths
    if precomputed_strengths is not None:
        h_strengths = precomputed_strengths.get(home_team, {'home_attack': 1.0, 'home_defense': 1.0, 'away_attack': 1.0, 'away_defense': 1.0})
        a_strengths = precomputed_strengths.get(away_team, {'home_attack': 1.0, 'home_defense': 1.0, 'away_attack': 1.0, 'away_defense': 1.0})
    else:
        # Load from EV DB
        close_ev = False
        if conn_ev is None:
            conn_ev = sqlite3.connect(DB_EV)
            close_ev = True
        
        cursor = conn_ev.cursor()
        cursor.execute("SELECT home_attack, home_defense, away_attack, away_defense FROM team_strengths WHERE team_name = ?;", (home_team,))
        row_h = cursor.fetchone()
        cursor.execute("SELECT home_attack, home_defense, away_attack, away_defense FROM team_strengths WHERE team_name = ?;", (away_team,))
        row_a = cursor.fetchone()
        
        if close_ev:
            conn_ev.close()
            
        if row_h:
            h_strengths = {'home_attack': row_h[0], 'home_defense': row_h[1], 'away_attack': row_h[2], 'away_defense': row_h[3]}
        else:
            h_strengths = {'home_attack': 1.0, 'home_defense': 1.0, 'away_attack': 1.0, 'away_defense': 1.0}
            
        if row_a:
            a_strengths = {'home_attack': row_a[0], 'home_defense': row_a[1], 'away_attack': row_a[2], 'away_defense': row_a[3]}
        else:
            a_strengths = {'home_attack': 1.0, 'home_defense': 1.0, 'away_attack': 1.0, 'away_defense': 1.0}

    # Calculate base Lambda
    lambda_home = h_strengths['home_attack'] * a_strengths['away_defense'] * global_avg_home
    lambda_away = a_strengths['away_attack'] * h_strengths['home_defense'] * global_avg_away
    
    # Load and apply team-specific expected goal biases
    biases = load_bias_adjustments()
    
    home_goal_biases = biases.get("team_bias_home_goals", {})
    if home_team in home_goal_biases:
        lambda_home += home_goal_biases[home_team]
        
    away_goal_biases = biases.get("team_bias_away_goals", {})
    if away_team in away_goal_biases:
        lambda_away += away_goal_biases[away_team]
        
    lambda_home = max(0.01, lambda_home)
    lambda_away = max(0.01, lambda_away)
    
    # Generate 11x11 probability matrix
    matrix = [[0.0 for _ in range(11)] for _ in range(11)]
    for h in range(11):
        for a in range(11):
            matrix[h][a] = poisson_pmf(h, lambda_home) * poisson_pmf(a, lambda_away)
            
    # Normalize the matrix to ensure sum is exactly 1.0
    total_prob_sum = sum(sum(row) for row in matrix)
    if total_prob_sum > 0:
        matrix = [[matrix[h][a] / total_prob_sum for a in range(11)] for h in range(11)]
        
    # Sum probabilities
    # Over 1.5: sum of goals >= 2
    prob_o15 = sum(matrix[h][a] for h in range(11) for a in range(11) if h + a >= 2)
    # Over 2.5: sum of goals >= 3
    prob_o25 = sum(matrix[h][a] for h in range(11) for a in range(11) if h + a >= 3)
    # Over 3.5: sum of goals >= 4
    prob_o35 = sum(matrix[h][a] for h in range(11) for a in range(11) if h + a >= 4)
    # GG (Both Teams to Score): both > 0
    prob_gg = sum(matrix[h][a] for h in range(11) for a in range(11) if h > 0 and a > 0)
    # Match Outcomes
    prob_home = sum(matrix[h][a] for h in range(11) for a in range(11) if h > a)
    prob_draw = sum(matrix[h][a] for h in range(11) for a in range(11) if h == a)
    prob_away = sum(matrix[h][a] for h in range(11) for a in range(11) if h < a)
    
    # Apply market-specific biases (O25 and GG)
    o25_biases = biases.get("team_bias_o25", {})
    prob_o25 += o25_biases.get(home_team, 0.0)
    prob_o25 += o25_biases.get(away_team, 0.0)
    prob_o25 = max(0.0, min(prob_o25, 1.0))
    
    gg_biases = biases.get("team_bias_gg", {})
    prob_gg += gg_biases.get(home_team, 0.0)
    prob_gg += gg_biases.get(away_team, 0.0)
    prob_gg = max(0.0, min(prob_gg, 1.0))
    
    pred_dict = {
        'home_team': home_team,
        'away_team': away_team,
        'lambda_home': lambda_home,
        'lambda_away': lambda_away,
        'prob_o15': prob_o15,
        'prob_o25': prob_o25,
        'prob_o35': prob_o35,
        'prob_gg': prob_gg,
        'prob_home': prob_home,
        'prob_draw': prob_draw,
        'prob_away': prob_away,
        'season_name': season_name,
        'match_day': match_day
    }
    
    # Store in match_predictions table if EV database is open/available
    if conn_ev is not None and season_name is not None and match_day is not None:
        cursor = conn_ev.cursor()
        cursor.execute("""
            INSERT INTO match_predictions (
                season_name, match_day, home_team, away_team,
                lambda_home, lambda_away, prob_o15, prob_o25, prob_o35,
                prob_gg, prob_home, prob_draw, prob_away, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            season_name, match_day, home_team, away_team,
            lambda_home, lambda_away, prob_o15, prob_o25, prob_o35,
            prob_gg, prob_home, prob_draw, prob_away, datetime.now().isoformat()
        ))
        conn_ev.commit()
        
    return pred_dict

# =====================================================================
# PART E: EV Calculation
# =====================================================================
def calculate_ev(market_odds, our_prob, market_all_odds=None):
    """
    Calculate Expected Value and Half-Kelly wager percentage.
    If market_all_odds is provided, strips house margin proportionally.
    """
    if market_odds <= 1.0 or our_prob <= 0.0:
        return {'fair_prob': 0.0, 'fair_odds': 0.0, 'ev': -1.0, 'ev_pct': -100.0, 'kelly': 0.0}
        
    # Strip house margin
    if market_all_odds and len(market_all_odds) > 0:
        overround = sum(1.0 / o for o in market_all_odds if o > 0)
        fair_prob = (1.0 / market_odds) / overround
    else:
        # Default fallback to 1.0 (no overround correction)
        fair_prob = 1.0 / market_odds
        
    fair_odds = 1.0 / fair_prob if fair_prob > 0 else 0.0
    
    # EV Calculation
    ev = (our_prob * market_odds) - 1.0
    ev_pct = ev * 100.0
    
    # Half-Kelly Calculation
    # Formula: Kelly = 0.5 * ((our_prob * (odds - 1) - (1 - our_prob)) / (odds - 1)) = 0.5 * (EV / (odds - 1))
    kelly = 0.5 * (ev / (market_odds - 1.0)) if market_odds > 1.0 else 0.0
    kelly = max(0.0, min(kelly, 0.15)) # Cap Kelly at 15% max, 0% min
    
    return {
        'fair_prob': fair_prob,
        'fair_odds': fair_odds,
        'ev': ev,
        'ev_pct': ev_pct,
        'kelly': kelly
    }

# =====================================================================
# PART F: CLI
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="VFL EV Engine Poisson Predictor")
    parser.add_argument("--build-strengths", action="store_true", help="Compute global stats and update team strengths table")
    parser.add_argument("--predict", metavar="MATCH", help="Predict a single match, e.g. 'Liverpool vs Chelsea'")
    parser.add_argument("--predict-md", nargs=2, metavar=("SEASON", "MD"), help="Predict all matches in a matchday, e.g. 'VFLM 5081' 28")
    
    args = parser.parse_args()
    
    if args.build_strengths:
        print("Building team strengths...")
        build_team_strengths()
        
    elif args.predict:
        if " vs " not in args.predict:
            print("Error: Format must be 'Home vs Away'")
            sys.exit(1)
        home, away = [team.strip() for team in args.predict.split(" vs ", 1)]
        print(f"Predicting match: {home} vs {away}...")
        pred = predict_match(home, away)
        
        print("\n=== Match Prediction ===")
        print(f"Fixture: {pred['home_team']} vs {pred['away_team']}")
        print(f"Lambda Home: {pred['lambda_home']:.4f} | Lambda Away: {pred['lambda_away']:.4f}")
        print("-" * 40)
        print(f"Home Win:  {pred['prob_home']*100:.2f}%")
        print(f"Draw:      {pred['prob_draw']*100:.2f}%")
        print(f"Away Win:  {pred['prob_away']*100:.2f}%")
        print(f"Both Score:{pred['prob_gg']*100:.2f}%")
        print(f"Over 1.5:  {pred['prob_o15']*100:.2f}%")
        print(f"Over 2.5:  {pred['prob_o25']*100:.2f}%")
        print(f"Over 3.5:  {pred['prob_o35']*100:.2f}%")
        print("========================\n")
        
    elif args.predict_md:
        season, md = args.predict_md[0], int(args.predict_md[1])
        print(f"Predicting all matches for {season} Matchday {md}...")
        
        # Connect to results DB to find fixtures on this matchday
        conn_res = sqlite3.connect(DB_RESULTS)
        cursor_res = conn_res.cursor()
        cursor_res.execute("""
            SELECT home_team, away_team 
            FROM results 
            WHERE season_name = ? AND match_day = ?;
        """, (season, md))
        fixtures = cursor_res.fetchall()
        
        if not fixtures:
            print(f"No fixtures found for {season} Matchday {md} in vfl_results.db.")
            conn_res.close()
            sys.exit(1)
            
        # Compute global stats once to show and avoid repeating
        g_avg_home, g_avg_away, _ = compute_global_stats(conn_res, verbose=True)
        conn_res.close()
        
        init_db()
        conn_ev = sqlite3.connect(DB_EV)
        
        print(f"Found {len(fixtures)} fixtures. Calculating...")
        for home, away in fixtures:
            pred = predict_match(home, away, season_name=season, match_day=md, conn_ev=conn_ev, global_stats=(g_avg_home, g_avg_away))
            print(f"Predicted: {home} vs {away}")
            print(f"  Outcomes: Home: {pred['prob_home']*100:.1f}%, Draw: {pred['prob_draw']*100:.1f}%, Away: {pred['prob_away']*100:.1f}%")
            print(f"  Goals:    O1.5: {pred['prob_o15']*100:.1f}%, O2.5: {pred['prob_o25']*100:.1f}%, O3.5: {pred['prob_o35']*100:.1f}%, GG: {pred['prob_gg']*100:.1f}%")
            
        conn_ev.close()
        print("Done. Predictions saved to vfl_ev.db.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
