import os
import sys
import sqlite3
import json
import math

DB_RESULTS = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db"
DB_ODDS = "/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_odds.db"
DB_EV = "/home/ubuntu/faith-workspace/vfl-empire/databases/vfl_ev.db"
BIAS_PATH = "/home/ubuntu/faith-workspace/vfl-empire/data/bias_adjustments.json"

# Load bias adjustments
with open(BIAS_PATH, 'r') as f:
    biases = json.load(f)

def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam**k * math.exp(-lam)) / math.factorial(k)

# Compute global stats over all results
conn_res = sqlite3.connect(DB_RESULTS)
cursor_res = conn_res.cursor()
cursor_res.execute("SELECT home_goals, away_goals FROM results WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL;")
rows = cursor_res.fetchall()
total_matches = len(rows)
global_avg_home = sum(r[0] for r in rows) / total_matches
global_avg_away = sum(r[1] for r in rows) / total_matches
print(f"Global Avg Home: {global_avg_home:.4f}, Away: {global_avg_away:.4f}, Matches: {total_matches}")

# Load current team strengths from vfl_ev.db
conn_ev = sqlite3.connect(DB_EV)
cursor_ev = conn_ev.cursor()
cursor_ev.execute("SELECT team_name, home_attack, home_defense, away_attack, away_defense FROM team_strengths;")
strengths = {}
for team, ha, hd, aa, ad in cursor_ev.fetchall():
    strengths[team] = {
        'home_attack': ha,
        'home_defense': hd,
        'away_attack': aa,
        'away_defense': ad
    }
conn_ev.close()

def predict_match(home_team, away_team):
    h_strengths = strengths.get(home_team, {'home_attack': 1.0, 'home_defense': 1.0, 'away_attack': 1.0, 'away_defense': 1.0})
    a_strengths = strengths.get(away_team, {'home_attack': 1.0, 'home_defense': 1.0, 'away_attack': 1.0, 'away_defense': 1.0})
    
    lambda_home = h_strengths['home_attack'] * a_strengths['away_defense'] * global_avg_home
    lambda_away = a_strengths['away_attack'] * h_strengths['home_defense'] * global_avg_away
    
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
    prob_o35 = sum(matrix[h][a] for h in range(11) for a in range(11) if h + a >= 4)
    prob_u35 = sum(matrix[h][a] for h in range(11) for a in range(11) if h + a <= 3)
    prob_gg = sum(matrix[h][a] for h in range(11) for a in range(11) if h > 0 and a > 0)
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
    
    return {
        'prob_o15': prob_o15,
        'prob_o25': prob_o25,
        'prob_o35': prob_o35,
        'prob_u35': prob_u35,
        'prob_gg': prob_gg,
        'prob_home': prob_home,
        'prob_draw': prob_draw,
        'prob_away': prob_away,
        'prob_dc1x': prob_home + prob_draw,
        'prob_dcx2': prob_draw + prob_away,
    }

# Compute Question 2 True Probabilities and historical hit rates
print("\n--- Question 2 Calculations ---")

# 1. Manchester Blue at home Over 1.5
mb_home_matches = [r for r in rows if r[2] == 'Manchester Blue'] if False else []
cursor_res.execute("SELECT home_goals, away_goals, home_team, away_team FROM results WHERE home_team='Manchester Blue';")
mb_home_rows = cursor_res.fetchall()
mb_home_o15_probs = []
mb_home_hits = 0
for h_g, a_g, h_t, a_t in mb_home_rows:
    pred = predict_match(h_t, a_t)
    mb_home_o15_probs.append(pred['prob_o15'])
    if h_g + a_g >= 2:
        mb_home_hits += 1
print(f"Manchester Blue home matches: {len(mb_home_rows)}")
print(f"Manchester Blue home Over 1.5 True Prob (mean): {sum(mb_home_o15_probs)/len(mb_home_o15_probs)*100:.2f}%")
print(f"Manchester Blue home Over 1.5 Actual Hit Rate: {mb_home_hits/len(mb_home_rows)*100:.2f}%")

# 2. Liverpool at home Over 1.5
cursor_res.execute("SELECT home_goals, away_goals, home_team, away_team FROM results WHERE home_team='Liverpool';")
liv_home_rows = cursor_res.fetchall()
liv_home_o15_probs = []
liv_home_hits = 0
for h_g, a_g, h_t, a_t in liv_home_rows:
    pred = predict_match(h_t, a_t)
    liv_home_o15_probs.append(pred['prob_o15'])
    if h_g + a_g >= 2:
        liv_home_hits += 1
print(f"Liverpool home matches: {len(liv_home_rows)}")
print(f"Liverpool home Over 1.5 True Prob (mean): {sum(liv_home_o15_probs)/len(liv_home_o15_probs)*100:.2f}%")
print(f"Liverpool home Over 1.5 Actual Hit Rate: {liv_home_hits/len(liv_home_rows)*100:.2f}%")

# 3. Brighton match Over 2.5
cursor_res.execute("SELECT home_goals, away_goals, home_team, away_team FROM results WHERE home_team='Brighton' OR away_team='Brighton';")
bri_rows = cursor_res.fetchall()
bri_o25_probs = []
bri_hits = 0
for h_g, a_g, h_t, a_t in bri_rows:
    pred = predict_match(h_t, a_t)
    bri_o25_probs.append(pred['prob_o25'])
    if h_g + a_g >= 3:
        bri_hits += 1
print(f"Brighton matches: {len(bri_rows)}")
print(f"Brighton Over 2.5 True Prob (mean): {sum(bri_o25_probs)/len(bri_o25_probs)*100:.2f}%")
print(f"Brighton Over 2.5 Actual Hit Rate: {bri_hits/len(bri_rows)*100:.2f}%")

# 4. Man Red Over 1.5 (any venue)
cursor_res.execute("SELECT home_goals, away_goals, home_team, away_team FROM results WHERE home_team='Manchester Red' OR away_team='Manchester Red';")
mr_rows = cursor_res.fetchall()
mr_o15_probs = []
mr_hits = 0
for h_g, a_g, h_t, a_t in mr_rows:
    pred = predict_match(h_t, a_t)
    mr_o15_probs.append(pred['prob_o15'])
    if h_g + a_g >= 2:
        mr_hits += 1
print(f"Manchester Red matches: {len(mr_rows)}")
print(f"Manchester Red Over 1.5 True Prob (mean): {sum(mr_o15_probs)/len(mr_o15_probs)*100:.2f}%")
print(f"Manchester Red Over 1.5 Actual Hit Rate: {mr_hits/len(mr_rows)*100:.2f}%")

conn_res.close()
