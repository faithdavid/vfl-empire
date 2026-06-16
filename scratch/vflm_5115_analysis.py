import os
import sys
import sqlite3
import json
import math

SCRIPTS_DIR = "/home/ubuntu/faith-workspace/vfl-empire/scripts"
sys.path.append(SCRIPTS_DIR)

from ev_engine import load_bias_adjustments, poisson_pmf
from track_30_md import compute_historical_strengths

DB_RESULTS = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db"
DB_ODDS = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_odds.db"

biases = load_bias_adjustments()

def predict_match_local(home_team, away_team, strengths, g_stats):
    g_avg_home, g_avg_away = g_stats
    h_strengths = strengths.get(home_team, {'home_attack': 1.0, 'home_defense': 1.0, 'away_attack': 1.0, 'away_defense': 1.0})
    a_strengths = strengths.get(away_team, {'home_attack': 1.0, 'home_defense': 1.0, 'away_attack': 1.0, 'away_defense': 1.0})
    
    lambda_home = h_strengths['home_attack'] * a_strengths['away_defense'] * g_avg_home
    lambda_away = a_strengths['away_attack'] * h_strengths['home_defense'] * g_avg_away
    
    home_goal_biases = biases.get("team_bias_home_goals", {})
    if home_team in home_goal_biases:
        lambda_home += home_goal_biases[home_team]
        
    away_goal_biases = biases.get("team_bias_away_goals", {})
    if away_team in away_goal_biases:
        lambda_away += away_goal_biases[away_team]
        
    lambda_home = max(0.01, lambda_home)
    lambda_away = max(0.01, lambda_away)
    
    matrix = [[0.0 for _ in range(11)] for _ in range(11)]
    for h in range(11):
        for a in range(11):
            matrix[h][a] = poisson_pmf(h, lambda_home) * poisson_pmf(a, lambda_away)
            
    total_prob_sum = sum(sum(row) for row in matrix)
    if total_prob_sum > 0:
        matrix = [[matrix[h][a] / total_prob_sum for a in range(11)] for h in range(11)]
        
    prob_o15 = sum(matrix[h][a] for h in range(11) for a in range(11) if h + a >= 2)
    prob_o25 = sum(matrix[h][a] for h in range(11) for a in range(11) if h + a >= 3)
    prob_u35 = sum(matrix[h][a] for h in range(11) for a in range(11) if h + a <= 3)
    prob_gg = sum(matrix[h][a] for h in range(11) for a in range(11) if h > 0 and a > 0)
    prob_home = sum(matrix[h][a] for h in range(11) for a in range(11) if h > a)
    prob_draw = sum(matrix[h][a] for h in range(11) for a in range(11) if h == a)
    prob_away = sum(matrix[h][a] for h in range(11) for a in range(11) if h < a)
    
    o25_biases = biases.get("team_bias_o25", {})
    prob_o25 += o25_biases.get(home_team, 0.0)
    prob_o25 += o25_biases.get(away_team, 0.0)
    prob_o25 = max(0.0, min(prob_o25, 1.0))
    
    gg_biases = biases.get("team_bias_gg", {})
    prob_gg += gg_biases.get(home_team, 0.0)
    prob_gg += gg_biases.get(away_team, 0.0)
    prob_gg = max(0.0, min(prob_gg, 1.0))
    
    return {
        'prob_o15': prob_o15,
        'prob_o25': prob_o25,
        'prob_u35': prob_u35,
        'prob_gg': prob_gg,
        'prob_home': prob_home,
        'prob_draw': prob_draw,
        'prob_away': prob_away,
        'prob_dc1x': prob_home + prob_draw,
        'prob_dcx2': prob_draw + prob_away
    }

def run_analysis():
    conn_odds = sqlite3.connect(DB_ODDS)
    cursor_odds = conn_odds.cursor()
    
    conn_res = sqlite3.connect(DB_RESULTS)
    cursor_res = conn_res.cursor()
    
    # DISTINCT event_id to prevent duplicates!
    cursor_odds.execute("""
        SELECT event_id, match_day, home_team, away_team 
        FROM event_details 
        WHERE season_name = 'VFLM 5115'
        GROUP BY event_id
        ORDER BY match_day ASC;
    """)
    fixtures = cursor_odds.fetchall()
    
    md_fixtures = {}
    for ev_id, md, home, away in fixtures:
        if md not in md_fixtures:
            md_fixtures[md] = []
        md_fixtures[md].append((ev_id, home, away))
        
    print(f"Loaded {len(fixtures)} distinct fixtures across {len(md_fixtures)} matchdays.")
    
    all_legs = []
    
    for md in sorted(md_fixtures.keys()):
        strengths, g_stats = compute_historical_strengths("VFLM 5115", md)
        for ev_id, home, away in md_fixtures[md]:
            cursor_res.execute("""
                SELECT home_goals, away_goals 
                FROM results 
                WHERE season_name = 'VFLM 5115' AND match_day = ? AND home_team = ? AND away_team = ?;
            """, (md, home, away))
            res = cursor_res.fetchone()
            if not res:
                continue
            h_g, a_g = res
            
            pred = predict_match_local(home, away, strengths, g_stats)
            
            cursor_odds.execute("""
                SELECT market_name, specifiers, selection_name, MAX(odds) 
                FROM deep_markets 
                WHERE event_id = ?
                GROUP BY market_name, specifiers, selection_name;
            """, (ev_id,))
            odds_rows = cursor_odds.fetchall()
            
            odds_map = {}
            for market, spec, sel, odds in odds_rows:
                if market not in odds_map:
                    odds_map[market] = {}
                s = spec or ""
                if s not in odds_map[market]:
                    odds_map[market][s] = {}
                odds_map[market][s][sel] = odds
                
            # Over 1.5
            try:
                o15_odds = odds_map['Over/Under']['total=1.5']['Over 1.5']
                all_legs.append({
                    'md': md, 'home': home, 'away': away, 'ev_id': ev_id,
                    'market': 'Over 1.5', 'selection': 'Over 1.5',
                    'odds': o15_odds, 'prob': pred['prob_o15'],
                    'hit': 1 if (h_g + a_g >= 2) else 0
                })
            except KeyError:
                pass
                
            # Under 3.5
            try:
                u35_odds = odds_map['Over/Under']['total=3.5']['Under 3.5']
                all_legs.append({
                    'md': md, 'home': home, 'away': away, 'ev_id': ev_id,
                    'market': 'Under 3.5', 'selection': 'Under 3.5',
                    'odds': u35_odds, 'prob': pred['prob_u35'],
                    'hit': 1 if (h_g + a_g <= 3) else 0
                })
            except KeyError:
                pass
                
            # Double Chance 1X
            try:
                dc1x_odds = odds_map['Double Chance']['']['1 X']
                all_legs.append({
                    'md': md, 'home': home, 'away': away, 'ev_id': ev_id,
                    'market': 'Double Chance 1X', 'selection': '1 X',
                    'odds': dc1x_odds, 'prob': pred['prob_dc1x'],
                    'hit': 1 if (h_g >= a_g) else 0
                })
            except KeyError:
                pass
                
            # Double Chance X2
            try:
                dcx2_odds = odds_map['Double Chance']['']['X 2']
                all_legs.append({
                    'md': md, 'home': home, 'away': away, 'ev_id': ev_id,
                    'market': 'Double Chance X2', 'selection': 'X 2',
                    'odds': dcx2_odds, 'prob': pred['prob_dcx2'],
                    'hit': 1 if (h_g <= a_g) else 0
                })
            except KeyError:
                pass
                
            # Home Win
            try:
                home_odds = odds_map['1x2']['']['Home']
                all_legs.append({
                    'md': md, 'home': home, 'away': away, 'ev_id': ev_id,
                    'market': 'Home Win', 'selection': 'Home',
                    'odds': home_odds, 'prob': pred['prob_home'],
                    'hit': 1 if (h_g > a_g) else 0
                })
            except KeyError:
                pass
                
            # Over 2.5 (Brighton)
            try:
                o25_odds = odds_map['Over/Under']['total=2.5']['Over 2.5']
                all_legs.append({
                    'md': md, 'home': home, 'away': away, 'ev_id': ev_id,
                    'market': 'Over 2.5', 'selection': 'Over 2.5',
                    'odds': o25_odds, 'prob': pred['prob_o25'],
                    'hit': 1 if (h_g + a_g >= 3) else 0
                })
            except KeyError:
                pass

    conn_odds.close()
    conn_res.close()
    
    with open('/home/ubuntu/faith-workspace/vfl-empire/scratch/vflm_5115_legs.json', 'w') as f:
        json.dump(all_legs, f, indent=2)
        
    print(f"Saved {len(all_legs)} de-duplicated individual legs to JSON.")

if __name__ == "__main__":
    run_analysis()
