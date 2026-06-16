#!/usr/bin/env python3
import pandas as pd
import numpy as np
from sklearn.tree import DecisionTreeClassifier
import json
import os

print("=== PHASE 2: ORACLE MINER ===")
print("Loading Unified Matrix...")
df = pd.read_parquet("/home/ubuntu/faith-workspace/vfl-empire/data/unified_ml_matrix.parquet")

features = [
    'day', 'prev_tension', 'archetype_goals',
    'h_rank', 'h_tier', 'h_quota', 'h_gd',
    'a_rank', 'a_tier', 'a_quota', 'a_gd',
    'poisson_hxG', 'poisson_axG',
    'odds_cluster', 'o15', 'o25', 'gg', 'u35'
]

X = df[features].copy()
y = df['target_1x2']

# Fill NA just in case
X = X.fillna(0)

print(f"Training on {len(X)} matches with {len(features)} structural features...")
print(f"Target distribution:\n{y.value_counts()}")

# We use DecisionTree to extract explicit IF/ELSE branches.
# We set max_depth to 15 to find deep deterministic pockets.
clf = DecisionTreeClassifier(max_depth=15, min_samples_leaf=4, random_state=42)
clf.fit(X, y)

tree = clf.tree_
found_locks = []

def extract_rules(tree, feature_names):
    left = tree.children_left
    right = tree.children_right
    threshold = tree.threshold
    features_idx = tree.feature
    value = tree.value

    def recurse(node, current_rule):
        if threshold[node] != -2:
            # Not a leaf
            f_name = feature_names[features_idx[node]]
            
            left_rule = current_rule + [f"{f_name} <= {threshold[node]:.2f}"]
            recurse(left[node], left_rule)
            
            right_rule = current_rule + [f"{f_name} > {threshold[node]:.2f}"]
            recurse(right[node], right_rule)
        else:
            # Leaf node
            samples = value[node][0]
            total_samples = np.sum(samples)
            if total_samples >= 4: # Minimum threshold
                max_class = np.argmax(samples)
                max_prob = samples[max_class] / total_samples
                
                # We want the highest purity nodes.
                if max_prob >= 0.90: 
                    outcome_map = {0: 'HOME_WIN', 1: 'DRAW', 2: 'AWAY_WIN'}
                    found_locks.append({
                        "outcome": outcome_map[max_class],
                        "probability": round(max_prob, 4),
                        "instances": int(total_samples),
                        "conditions": current_rule
                    })

    recurse(0, [])

extract_rules(tree, features)

# Sort by outcome type and probability
found_locks.sort(key=lambda x: (x['outcome'], -x['probability']))

out_path = "/home/ubuntu/faith-workspace/vfl-empire/data/deterministic_branches.json"
with open(out_path, 'w') as f:
    json.dump(found_locks, f, indent=4)

print(f"\nOracle Mining Complete!")
print(f"Total >=95% Deterministic Branches Discovered: {len(found_locks)}")

draws = sum(1 for l in found_locks if l['outcome'] == 'DRAW')
aways = sum(1 for l in found_locks if l['outcome'] == 'AWAY_WIN')
homes = sum(1 for l in found_locks if l['outcome'] == 'HOME_WIN')

print(f"  - 100% Home Wins: {homes}")
print(f"  - 100% Draws: {draws}")
print(f"  - 100% Away Wins: {aways}")
print(f"Rules exported to: {out_path}")

if len(found_locks) > 0:
    print("\nSample 100% DRAW Rule:")
    sample_draw = next((l for l in found_locks if l['outcome'] == 'DRAW'), None)
    if sample_draw:
        for c in sample_draw['conditions']:
            print(f"  AND {c}")
