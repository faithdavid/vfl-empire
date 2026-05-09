#!/usr/bin/env python3
"""
VFL Engine Reverse-Engineering — Bayesian Network Structure Learning
====================================================================

Based on the Hattrick paper methodology (Constantinou et al., 2025):
Uses Bayesian Network Structure Learning to discover the VFL engine's
hidden parameter dependencies from observed data.

The engine is a weighted PRNG. The Bayesian network learns the 
WEIGHTING COEFFICIENTS (probability distributions) that the engine
uses to generate outcomes.

Key difference from my previous attempts:
  - NOT predicting outcomes directly
  - INSTEAD: learning the engine's underlying probability distribution
  - The BN structure reveals HOW the engine combines parameters
  - Walk-forward validates: does the discovered structure persist?
"""

import numpy as np
import pandas as pd
import sqlite3, json, warnings
from collections import defaultdict, Counter
from pgmpy.models import DiscreteBayesianNetwork
from pgmpy.estimators import HillClimbSearch, MaximumLikelihoodEstimator, BayesianEstimator
from pgmpy.parameter_estimator import DiscreteBayesianEstimator, DiscreteMLE
from pgmpy.inference import VariableElimination

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# DATA LOADING
# ============================================================

def load_all_matches():
    """Load all matches with odds + outcomes."""
    rows = []
    
    def norm_team(t):
        if not t: return ''
        return t.strip().title()
    
    def outcome_code(o):
        o = str(o).upper().strip()
        if o in ('HOME', 'H', '1'): return 'H'
        if o in ('DRAW', 'D', 'X'): return 'D'
        if o in ('AWAY', 'A', '2'): return 'A'
        return None
    
    conn = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')
    cur = conn.cursor()
    cur.execute("""
        SELECT season, day, home, away, oh, od, oa, outcome, h, a
        FROM matches 
        WHERE oh IS NOT NULL AND od IS NOT NULL AND oa IS NOT NULL
          AND outcome IS NOT NULL AND outcome != ''
          AND oh > 0 AND od > 0 AND oa > 0
        ORDER BY season, day
    """)
    for r in cur.fetchall():
        oc = outcome_code(r[7])
        if oc is None: continue
        rows.append({
            'season': r[0], 'md': r[1],
            'home': norm_team(r[2]), 'away': norm_team(r[3]),
            'oh': float(r[4]), 'od': float(r[5]), 'oa': float(r[6]),
            'outcome': oc,
            'h_goals': r[8], 'a_goals': r[9],
        })
    conn.close()
    
    conn2 = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/sovereign.db')
    cur2 = conn2.cursor()
    cur2.execute("""
        SELECT season_id, match_day, home_team, away_team, odds_h, odds_d, odds_a, outcome
        FROM master_ledger 
        WHERE odds_h IS NOT NULL AND odds_d IS NOT NULL AND odds_a IS NOT NULL
          AND outcome IS NOT NULL AND outcome != ''
          AND odds_h > 0 AND odds_d > 0 AND odds_a > 0
    """)
    existing = set()
    for m in rows:
        existing.add((m['season'], m['md'], m['home'], m['away']))
    for r in cur2.fetchall():
        oc = outcome_code(r[7])
        if oc is None: continue
        home = norm_team(r[2]); away = norm_team(r[3])
        key = (r[0], r[1], home, away)
        if key not in existing:
            rows.append({
                'season': r[0], 'md': r[1],
                'home': home, 'away': away,
                'oh': float(r[4]), 'od': float(r[5]), 'oa': float(r[6]),
                'outcome': oc, 'h_goals': None, 'a_goals': None,
            })
    conn2.close()
    
    return rows


# ============================================================
# ENGINEERING DISCRETE VARIABLES (for Bayesian Network)
# ============================================================

def discretize_variables(matches):
    """
    Convert continuous match data into DISCRETE variables
    suitable for Bayesian Network structure learning.
    
    These variables represent the engine's HIDDEN PARAMETERS:
    - Team strength tier
    - Odds favorite type
    - Market confidence level
    - Draw propensity
    - Home advantage strength
    - Matchday phase
    - Outcome (target)
    """
    df_list = []
    
    # First pass: compute team strength from odds
    team_avg_odds = defaultdict(list)
    for m in matches:
        team_avg_odds[m['home']].append(m['oh'])
        team_avg_odds[m['away']].append(m['oa'])
    
    team_strength = {}
    for team, odds_list in team_avg_odds.items():
        avg_odds = np.mean(odds_list)
        if avg_odds < 1.8: team_strength[team] = 'ELITE'
        elif avg_odds < 2.5: team_strength[team] = 'STRONG'
        elif avg_odds < 3.5: team_strength[team] = 'MID'
        elif avg_odds < 5.0: team_strength[team] = 'WEAK'
        else: team_strength[team] = 'UNDER'
    
    # Second pass: create discrete features per match
    season_order = {}
    season_counter = 0
    prev_season = None
    
    for m in matches:
        oh, od, oa = m['oh'], m['od'], m['oa']
        
        # Vig-free implied probabilities
        total_inv = 1/oh + 1/od + 1/oa
        p_h, p_d, p_a = 1/oh/total_inv, 1/od/total_inv, 1/oa/total_inv
        
        # === DISCRETE VARIABLES ===
        
        # 1. Odds Favorite Type (what the engine's "base" is)
        min_odds = min(oh, od, oa)
        if min_odds == oh: fav = 'HOME_FAV'
        elif min_odds == od: fav = 'DRAW_FAV'
        else: fav = 'AWAY_FAV'
        
        # 2. Favorite Strength (how confident the market is)
        fav_prob = max(p_h, p_d, p_a)
        if fav_prob >= 0.60: strength = 'HEAVY'
        elif fav_prob >= 0.50: strength = 'CLEAR'
        elif fav_prob >= 0.40: strength = 'SLIGHT'
        else: strength = 'TOSS_UP'
        
        # 3. Draw Attractiveness (engine's draw probability)
        draw_ratio = p_d / ((p_h + p_a) / 2)
        if draw_ratio >= 1.15: draw_z = 'HIGH_DRAW'
        elif draw_ratio >= 0.90: draw_z = 'NORM_DRAW'
        else: draw_z = 'LOW_DRAW'
        
        # 4. Home Edge (engine's home advantage parameter)
        home_edge = p_h - p_a
        if home_edge >= 0.10: hedge = 'STRONG_HOME'
        elif home_edge >= -0.05: hedge = 'BALANCED'
        else: hedge = 'STRONG_AWAY'
        
        # 5. Competition Tightness (how close the match is expected to be)
        spread = max(oh, od, oa) - min(oh, od, oa)
        if spread < 1.5: tightness = 'TIGHT'
        elif spread < 3.0: tightness = 'MODERATE'
        else: tightness = 'ONE_SIDED'
        
        # 6. Home Team Strength (engine's team rating)
        home_tier = team_strength.get(m['home'], 'MID')
        away_tier = team_strength.get(m['away'], 'MID')
        
        # 7. Tier Matchup Type (engine's matchup weighting)  
        tiers = {'ELITE': 4, 'STRONG': 3, 'MID': 2, 'WEAK': 1, 'UNDER': 0}
        tier_gap = tiers.get(home_tier, 2) - tiers.get(away_tier, 2)
        if tier_gap >= 2: matchup = 'DOMINANT_HOME'
        elif tier_gap >= 1: matchup = 'FAV_HOME'
        elif tier_gap >= -1: matchup = 'BALANCED'
        elif tier_gap >= -2: matchup = 'FAV_AWAY'
        else: matchup = 'DOMINANT_AWAY'
        
        # 8. Matchday Phase (engine's state parameter)
        md = m['md'] or 15
        if md <= 10: md_phase = 'EARLY'
        elif md <= 20: md_phase = 'MID'
        else: md_phase = 'LATE'
        
        # 9. Outcome (target)
        target = m['outcome']
        
        # 10. Season progression
        if m['season'] != prev_season:
            season_counter += 1
            prev_season = m['season']
        season_order[m['season']] = season_counter
        
        df_list.append({
            'fav_type': fav,
            'fav_strength': strength,
            'draw_zone': draw_z,
            'home_edge': hedge,
            'tightness': tightness,
            'home_tier': home_tier,
            'away_tier': away_tier,
            'matchup': matchup,
            'md_phase': md_phase,
            'outcome': target,
            'season': m['season'],
            'season_num': season_counter,
        })
    
    df = pd.DataFrame(df_list)
    return df


# ============================================================
# BAYESIAN NETWORK: STRUCTURE LEARNING + WALK-FORWARD
# ============================================================

print("=" * 85)
print("VFL ENGINE REVERSE-ENGINEERING")
print("Bayesian Network Structure Learning (Hattrick Paper Method)")
print("=" * 85)

# Load and discretize
matches = load_all_matches()
print(f"\nLoaded {len(matches)} matches")

df = discretize_variables(matches)
print(f"Discretized into {df.shape[0]} rows × {df.shape[1]} columns")
print(f"\nVariable distributions:")
for col in ['fav_type', 'fav_strength', 'draw_zone', 'home_edge', 'matchup', 'md_phase']:
    print(f"  {col}: {dict(df[col].value_counts().to_dict())}")

# ============================================================
# WALK-FORWARD BAYESIAN LEARNING
# ============================================================

# Columns to use in the BN (exclude season identifiers)
bn_cols = ['fav_type', 'fav_strength', 'draw_zone', 'home_edge', 
           'tightness', 'matchup', 'md_phase', 'outcome']

# Track accuracy per season
results = []

# Walk-forward by season number
season_nums = sorted(df['season_num'].unique())
print(f"\nSeasons: {len(season_nums)}")

for i, test_season in enumerate(season_nums[1:], 1):
    # Training data: ALL seasons before this one
    train_df = df[df['season_num'] < test_season]
    # Test data: THIS season (blind)
    test_df = df[df['season_num'] == test_season]
    
    if len(train_df) < 50 or len(test_df) < 5:
        continue
    
    # --- STRUCTURE LEARNING ---
    # Learn the Bayesian Network structure from training data
    # This discovers the engine's parameter dependencies automatically
    
    hc = HillClimbSearch(train_df[bn_cols])
    
    # Use BIC score to find the best structure
    # (Lower BIC = better fit without overfitting)
    best_model = hc.estimate(scoring_method='bic-d', max_indegree=3, max_iter=10000)
    
    # Create Bayesian Network with learned structure
    model = DiscreteBayesianNetwork(best_model.edges())
    
    # --- PARAMETER LEARNING ---
    # Learn the Conditional Probability Distributions (CPDs)
    # These ARE the engine's weighting coefficients
    
    model.fit(train_df[bn_cols], estimator=DiscreteBayesianEstimator(prior_type='BDeu', equivalent_sample_size=10))
    
    # --- INFERENCE on test data ---
    try:
        infer = VariableElimination(model)
        
        correct = 0
        outcome_probs = []
        
        for _, row in test_df.iterrows():
            evidence = {col: row[col] for col in bn_cols if col != 'outcome'}
            
            try:
                query = infer.query(['outcome'], evidence=evidence)
                pred = query.values.argmax()
                pred_outcome = ['H', 'D', 'A'][pred]
                prob = query.values[pred]
                
                if pred_outcome == row['outcome']:
                    correct += 1
                
                outcome_probs.append({
                    'predicted': pred_outcome,
                    'probability': float(prob),
                    'actual': row['outcome'],
                    'correct': pred_outcome == row['outcome'],
                })
            except:
                continue
        
        total = len(outcome_probs)
        acc = correct / total * 100 if total else 0
        
        # Record structure edges for analysis
        edges = list(model.edges())
        
        results.append({
            'season': test_season,
            'total': total,
            'correct': correct,
            'accuracy': acc,
            'n_edges': len(edges),
            'train_size': len(train_df),
        })
        
        bar = '█' * int(acc / 4) + '░' * max(0, 25 - int(acc / 4))
        print(f"  Season {i:2d}/{len(season_nums)-1} | Train:{len(train_df):4d} | Test:{total:4d} | Acc:{acc:5.1f}% {bar} | Edges:{len(edges):3d} | Structure:{edges[:4]}...")
    
    except Exception as e:
        print(f"  Season {i:2d}: Inference failed - {str(e)[:60]}")
        continue

# ============================================================
# REPORT
# ============================================================
print(f"\n{'='*85}")
print(f"BAYESIAN NETWORK RESULTS — {len(results)} seasons")
print(f"{'='*85}")

if results:
    total_correct = sum(r['correct'] for r in results)
    total_matches = sum(r['total'] for r in results)
    overall = total_correct / total_matches * 100
    first = results[0]['accuracy']
    last = results[-1]['accuracy']
    
    print(f"\n  Overall accuracy:   {total_correct}/{total_matches} = {overall:.2f}%")
    print(f"  First season:       {first:.2f}%")
    print(f"  Last season:        {last:.2f}%")
    print(f"  Improvement:        {last - first:+.2f}pp")
    
    # What structure did the FINAL model learn?
    print(f"\n  Learned Bayesian Network Structure (final season):")
    edges = list(results[-1].get('edges', [])) if 'edges' in results[-1] else []
    
    # Learn the final full model to inspect
    final_train = df[df['season_num'] < max(season_nums)]
    hc = HillClimbSearch(final_train[bn_cols])
    final_model = hc.estimate(scoring_method='bic-d', max_indegree=4)
    
    print(f"\n  Variable dependencies discovered (engine parameters):")
    edges_by_target = defaultdict(list)
    for a, b in final_model.edges():
        edges_by_target[b].append(a)
    
    for target, parents in sorted(edges_by_target.items()):
        print(f"    {target} ← {', '.join(parents)}")
    
    # CPDs for outcome
    model_final = DiscreteBayesianNetwork(final_model.edges())
    model_final.fit(final_train[bn_cols], estimator=DiscreteBayesianEstimator(prior_type='BDeu', equivalent_sample_size=10))
    
    print(f"\n  Outcome CPD (engine's weighting coefficients):")
    try:
        infer = VariableElimination(model_final)
        
        # Show how outcome probability changes with key variables
        print(f"\n  Effect of DRAW_ZONE on outcome:")
        for dz in ['HIGH_DRAW', 'NORM_DRAW', 'LOW_DRAW']:
            q = infer.query(['outcome'], evidence={'draw_zone': dz})
            print(f"    draw_zone={dz:12s} → H:{q.values[0]:.3f} D:{q.values[1]:.3f} A:{q.values[2]:.3f}")
        
        print(f"\n  Effect of FAV_TYPE on outcome:")
        for ft in ['HOME_FAV', 'DRAW_FAV', 'AWAY_FAV']:
            q = infer.query(['outcome'], evidence={'fav_type': ft})
            print(f"    fav_type={ft:10s} → H:{q.values[0]:.3f} D:{q.values[1]:.3f} A:{q.values[2]:.3f}")
        
        print(f"\n  Effect of MATCHUP on outcome:")
        for mu in ['DOMINANT_HOME', 'BALANCED', 'DOMINANT_AWAY']:
            q = infer.query(['outcome'], evidence={'matchup': mu})
            print(f"    matchup={mu:15s} → H:{q.values[0]:.3f} D:{q.values[1]:.3f} A:{q.values[2]:.3f}")
        
    except Exception as e:
        print(f"    Inference failed: {e}")

else:
    print("\n  No seasons completed successfully.")

# Save everything
with open('/tmp/bayesian_engine_results.json', 'w') as f:
    json.dump({
        'results': results,
        'structure_edges': list(final_model.edges()) if 'final_model' in dir() else [],
    }, f, indent=2, default=str)

print(f"\nResults saved to /tmp/bayesian_engine_results.json")
