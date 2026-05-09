#!/usr/bin/env python3
"""
VFL Neural Pattern Learner — Walk-Forward Unsupervised Learning
=============================================================

Builds a proper softmax regression model from scratch using numpy.
Engineers rich features from odds data, learns patterns progressively
through walk-forward validation across ALL historical seasons.

No sklearn, no pandas, no tensor — just numpy and math.
"""

import numpy as np
import sqlite3, json
from collections import defaultdict, Counter

np.random.seed(42)

# ============================================================
# FEATURE ENGINEERING
# ============================================================

def engineer_features(oh, od, oa, home_team=None, away_team=None, 
                      team_home_stats=None, team_away_stats=None, 
                      md=15, season_stage=0.5):
    """
    Build rich feature vector from odds and context.
    
    Returns numpy array of features.
    """
    # Vig-free implied probabilities
    inv_h = 1.0 / oh
    inv_d = 1.0 / od
    inv_a = 1.0 / oa
    total_inv = inv_h + inv_d + inv_a
    
    p_h = inv_h / total_inv  # Vig-free home prob
    p_d = inv_d / total_inv  # Vig-free draw prob  
    p_a = inv_a / total_inv  # Vig-free away prob
    
    # Core features (9)
    f = [
        p_h,                    # 0: Home implied prob
        p_d,                    # 1: Draw implied prob
        p_a,                    # 2: Away implied prob
        oh / (oh + od + oa),    # 3: Normalized home odds
        od / (oh + od + oa),    # 4: Normalized draw odds
        oa / (oh + od + oa),    # 5: Normalized away odds
        np.log(oh / od),        # 6: Log odds ratio home/draw
        np.log(oh / oa),        # 7: Log odds ratio home/away
        np.log(od / oa),        # 8: Log odds ratio draw/away
    ]
    
    # Derived features (4)
    f.extend([
        p_h - p_a,              # 9: Home edge (signed)
        p_d - 0.5 * (p_h + p_a),# 10: Draw attraction (positive = draw favored)
        max(oh, od, oa) - min(oh, od, oa),  # 11: Odds spread (uncertainty)
        od if od > 4.0 else -od,# 12: Draw odds signal (high = draw unlikely)
    ])
    
    # Season context (2)
    f.extend([
        md / 30.0,              # 13: Matchday (normalized 0-1)
        season_stage,           # 14: Season stage (normalized)
    ])
    
    # Team stats if available (6)
    if team_home_stats and home_team in team_home_stats:
        hst = team_home_stats[home_team]
        total_h = sum(hst.values())
        if total_h > 0:
            f.extend([
                hst['H'] / total_h,  # 15: Home team home win rate
                hst['D'] / total_h,  # 16: Home team home draw rate
                hst['A'] / total_h,  # 17: Home team home loss rate
            ])
        else:
            f.extend([0.44, 0.25, 0.31])  # League averages
    else:
        f.extend([0.44, 0.25, 0.31])
    
    if team_away_stats and away_team in team_away_stats:
        ast = team_away_stats[away_team]
        total_a = sum(ast.values())
        if total_a > 0:
            f.extend([
                ast['H'] / total_a,  # 18: Away team away loss rate
                ast['D'] / total_a,  # 19: Away team away draw rate
                ast['A'] / total_a,  # 20: Away team away win rate
            ])
        else:
            f.extend([0.44, 0.25, 0.31])
    else:
        f.extend([0.44, 0.25, 0.31])
    
    return np.array(f, dtype=np.float64)


# ============================================================
# SOFTMAX REGRESSION (from scratch)
# ============================================================

class SoftmaxRegression:
    """
    Multi-class logistic regression with softmax output.
    
    Learns P(H), P(D), P(A) from feature vectors.
    Uses gradient descent with L2 regularization.
    """
    
    def __init__(self, n_features, n_classes=3, learning_rate=0.01, 
                 reg_lambda=0.01, epochs=500, batch_size=64):
        self.n_features = n_features
        self.n_classes = n_classes
        self.lr = learning_rate
        self.reg_lambda = reg_lambda
        self.epochs = epochs
        self.batch_size = batch_size
        self.n_trained = 0
        
        # Initialize weights: [n_features x n_classes]
        # Xavier initialization
        scale = np.sqrt(2.0 / (n_features + n_classes))
        self.W = np.random.randn(n_features, n_classes) * scale
        self.b = np.zeros(n_classes)
        
        # Training history
        self.loss_history = []
        
    def softmax(self, logits):
        """Numerically stable softmax."""
        shifted = logits - np.max(logits, axis=1, keepdims=True)
        exp = np.exp(shifted)
        return exp / np.sum(exp, axis=1, keepdims=True)
    
    def predict_proba(self, X):
        """Predict class probabilities for feature matrix X."""
        logits = X @ self.W + self.b
        return self.softmax(logits)
    
    def predict(self, X):
        """Predict class (0=H, 1=D, 2=A)."""
        proba = self.predict_proba(X)
        return np.argmax(proba, axis=1), proba
    
    def compute_loss(self, X, y_onehot):
        """Cross-entropy loss with L2 regularization."""
        proba = self.predict_proba(X)
        # Cross-entropy
        ce_loss = -np.mean(np.sum(y_onehot * np.log(proba + 1e-15), axis=1))
        # L2 regularization
        reg_loss = 0.5 * self.reg_lambda * np.sum(self.W * self.W)
        return ce_loss + reg_loss
    
    def train(self, X, y, verbose=False):
        """
        Train on feature matrix X and one-hot labels y.
        Uses mini-batch gradient descent.
        """
        n_samples = X.shape[0]
        if n_samples < 3:
            return  # Not enough data
        
        # Convert to one-hot if needed
        if len(y.shape) == 1:
            y_onehot = np.zeros((n_samples, self.n_classes))
            y_onehot[np.arange(n_samples), y] = 1
        else:
            y_onehot = y
        
        # Adaptive learning rate based on data size
        actual_lr = self.lr * min(1.0, n_samples / 100)
        
        for epoch in range(self.epochs):
            # Shuffle
            idx = np.random.permutation(n_samples)
            X_shuffled = X[idx]
            y_shuffled = y_onehot[idx]
            
            # Mini-batch training
            for start in range(0, n_samples, self.batch_size):
                end = min(start + self.batch_size, n_samples)
                X_batch = X_shuffled[start:end]
                y_batch = y_shuffled[start:end]
                
                # Forward pass
                proba = self.predict_proba(X_batch)
                
                # Gradient
                error = proba - y_batch  # [batch x n_classes]
                grad_W = (X_batch.T @ error) / X_batch.shape[0] + self.reg_lambda * self.W
                grad_b = np.mean(error, axis=0)
                
                # Update
                self.W -= actual_lr * grad_W
                self.b -= actual_lr * grad_b
            
            # Track loss every 50 epochs
            if verbose and (epoch + 1) % 50 == 0:
                loss = self.compute_loss(X, y_onehot)
                self.loss_history.append((epoch, loss))
        
        self.n_trained += n_samples


# ============================================================
# ONLINE UPDATING — Team Stats Tracker
# ============================================================

class TeamStatsTracker:
    """Tracks per-team home and away performance over time."""
    
    def __init__(self):
        self.home_stats = defaultdict(lambda: Counter())
        self.away_stats = defaultdict(lambda: Counter())
    
    def update(self, home, away, outcome):
        """Record a match outcome for both teams."""
        self.home_stats[home][outcome] += 1
        self.away_stats[away][outcome] += 1
    
    def get_home_rates(self, team):
        """Get home outcome rates for a team."""
        s = self.home_stats.get(team, Counter())
        total = sum(s.values())
        if total == 0:
            return None
        return {'H': s['H']/total, 'D': s['D']/total, 'A': s['A']/total}
    
    def get_away_rates(self, team):
        """Get away outcome rates for a team."""
        s = self.away_stats.get(team, Counter())
        total = sum(s.values())
        if total == 0:
            return None
        return {'H': s['H']/total, 'D': s['D']/total, 'A': s['A']/total}


# ============================================================
# MAIN WALK-FORWARD PIPELINE
# ============================================================

def load_all_data():
    """Load all matches with odds + outcomes from all sources."""
    all_matches = []
    
    def norm_team(t):
        if not t: return ''
        return t.strip().title()
    
    def norm_outcome(o):
        o = str(o).upper().strip()
        if o in ('HOME', 'H', '1'): return 0  # H
        if o in ('DRAW', 'D', 'X'): return 1  # D
        if o in ('AWAY', 'A', '2'): return 2  # A
        return None
    
    # Source 1: History DB
    conn = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT season, day, home, away, oh, od, oa, outcome
        FROM matches 
        WHERE oh IS NOT NULL AND od IS NOT NULL AND oa IS NOT NULL
          AND outcome IS NOT NULL AND outcome != ''
          AND oh > 0 AND od > 0 AND oa > 0
        ORDER BY season, day
    """)
    for r in cur.fetchall():
        outcome = norm_outcome(r['outcome'])
        if outcome is None: continue
        all_matches.append({
            'season': r['season'],
            'md': r['day'],
            'home': norm_team(r['home']),
            'away': norm_team(r['away']),
            'odds_h': float(r['oh']),
            'odds_d': float(r['od']),
            'odds_a': float(r['oa']),
            'outcome': outcome,  # 0=H, 1=D, 2=A
        })
    conn.close()
    
    # Source 2: Sovereign DB (deduplicated)
    conn2 = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/sovereign.db')
    conn2.row_factory = sqlite3.Row
    cur2 = conn2.cursor()
    cur2.execute("""
        SELECT season_id, match_day, home_team, away_team, odds_h, odds_d, odds_a, outcome
        FROM master_ledger 
        WHERE odds_h IS NOT NULL AND odds_d IS NOT NULL AND odds_a IS NOT NULL
          AND outcome IS NOT NULL AND outcome != ''
          AND odds_h > 0 AND odds_d > 0 AND odds_a > 0
    """)
    existing = set()
    for m in all_matches:
        existing.add((m['season'], m['md'], m['home'], m['away']))
    
    for r in cur2.fetchall():
        outcome = norm_outcome(r['outcome'])
        if outcome is None: continue
        home = norm_team(r['home_team'])
        away = norm_team(r['away_team'])
        key = (r['season_id'], r['match_day'], home, away)
        if key not in existing:
            all_matches.append({
                'season': r['season_id'],
                'md': r['match_day'],
                'home': home,
                'away': away,
                'odds_h': float(r['odds_h']),
                'odds_d': float(r['odds_d']),
                'odds_a': float(r['odds_a']),
                'outcome': outcome,
            })
    conn2.close()
    
    return all_matches


print("=" * 80)
print("VFL NEURAL PATTERN LEARNER — Walk-Forward Unsupervised Learning")
print("=" * 80)

# Load data
all_matches = load_all_data()
print(f"\nLoaded {len(all_matches)} matches with odds + outcomes")

# Group by season
def season_sort_key(s):
    parts = str(s).replace('vf:season:', '').split('_')
    return int(parts[0])

season_matches = defaultdict(list)
for m in all_matches:
    season_matches[m['season']].append(m)

sorted_seasons = sorted(season_matches.keys(), key=season_sort_key)
ignored = [s for s in sorted_seasons if len(season_matches[s]) < 10]
sorted_seasons = [s for s in sorted_seasons if len(season_matches[s]) >= 10]

print(f"Seasons (min 10 matches): {len(sorted_seasons)} of {len(season_matches)} total")
print(f"Ignored small seasons: {len(ignored)}")

# ============================================================
# WALK-FORWARD TEST
# ============================================================

# Feature dimension (we'll know after first match)
sample_match = all_matches[0]
team_stats = TeamStatsTracker()
n_features = len(engineer_features(
    sample_match['odds_h'], sample_match['odds_d'], sample_match['odds_a'],
    sample_match['home'], sample_match['away'],
    team_stats.home_stats, team_stats.away_stats,
    sample_match['md'], 0.5
))
print(f"Feature dimension: {n_features}")

# Initialize model
model = SoftmaxRegression(
    n_features=n_features,
    learning_rate=0.05,
    reg_lambda=0.005,
    epochs=300,
    batch_size=32
)

# Walk-forward
season_results = []

# Train on first season
first_season = sorted_seasons[0]
first_matches = season_matches[first_season]
first_features = []
first_labels = []
for m in first_matches:
    f = engineer_features(m['odds_h'], m['odds_d'], m['odds_a'],
                          m['home'], m['away'],
                          team_stats.home_stats, team_stats.away_stats,
                          m['md'], 0.5)
    first_features.append(f)
    first_labels.append(m['outcome'])
    team_stats.update(m['home'], m['away'], m['outcome'])

X_first = np.array(first_features, dtype=np.float64)
y_first = np.array(first_labels, dtype=np.int64)
model.train(X_first, y_first, verbose=False)
print(f"\nTrained on first season ({first_season}): {len(first_matches)} matches")

print(f"\n{'=' * 90}")
print(f"{'SEASON':30s} | {'MATCHES':7s} | {'ACC':6s} | {'HOME':6s} | {'DRAW':6s} | {'AWAY':6s} | {'LOSS':8s} | {'TREND'}")
print(f"{'=' * 90}")

all_predictions = []
all_actuals = []

for season in sorted_seasons[1:]:
    matches = season_matches[season]
    
    # Feature engineering
    X_test = []
    y_test = []
    
    for m in matches:
        f = engineer_features(m['odds_h'], m['odds_d'], m['odds_a'],
                              m['home'], m['away'],
                              team_stats.home_stats, team_stats.away_stats,
                              m['md'], 0.5)
        X_test.append(f)
        y_test.append(m['outcome'])
    
    X_test = np.array(X_test, dtype=np.float64)
    y_test = np.array(y_test, dtype=np.int64)
    
    # Predict blind
    preds, probas = model.predict(X_test)
    
    # Evaluate
    correct = np.sum(preds == y_test)
    total = len(y_test)
    acc = correct / total * 100
    
    # Per-class accuracy
    class_correct = {}
    for c in range(3):
        mask = y_test == c
        if np.sum(mask) > 0:
            class_correct[c] = np.sum(preds[mask] == y_test[mask]) / np.sum(mask) * 100
    
    # Cross-entropy loss
    y_onehot = np.zeros((total, 3))
    y_onehot[np.arange(total), y_test] = 1
    probas_clipped = np.clip(probas, 1e-15, 1 - 1e-15)
    ce_loss = -np.mean(np.sum(y_onehot * np.log(probas_clipped), axis=1))
    
    all_predictions.extend(preds.tolist())
    all_actuals.extend(y_test.tolist())
    
    # Now train on this season's data (after prediction — no peeking)
    X_train = np.array([engineer_features(m['odds_h'], m['odds_d'], m['odds_a'],
                                          m['home'], m['away'],
                                          team_stats.home_stats, team_stats.away_stats,
                                          m['md'], 0.5) for m in matches], dtype=np.float64)
    y_train = np.array([m['outcome'] for m in matches], dtype=np.int64)
    
    # Update team stats BEFORE training (so model sees them next time)
    for m in matches:
        team_stats.update(m['home'], m['away'], m['outcome'])
    
    model.train(X_train, y_train, verbose=False)
    
    trend = ''
    season_results.append({
        'season': season, 'acc': acc, 'total': total, 'correct': correct,
        'home_acc': class_correct.get(0, 0), 'draw_acc': class_correct.get(1, 0),
        'away_acc': class_correct.get(2, 0), 'loss': ce_loss
    })
    
    bar = '█' * int(acc / 4) + '░' * max(0, 25 - int(acc / 4))
    HA = f"{class_correct.get(0,0):5.1f}%"
    DA = f"{class_correct.get(1,0):5.1f}%"
    AA = f"{class_correct.get(2,0):5.1f}%"
    
    print(f"{str(season)[-25:]:30s} | {total:3d}/{total:3d} | {acc:5.1f}% {bar} | {HA} | {DA} | {AA} | {ce_loss:6.4f} |")

# Summary
print(f"\n{'=' * 80}")
print(f"FINAL RESULTS — {len(season_results)} seasons, walk-forward")
print(f"{'=' * 80}")

total_correct = sum(r['correct'] for r in season_results)
total_matches = sum(r['total'] for r in season_results)
overall_acc = total_correct / total_matches * 100

first_acc = season_results[0]['acc']
last_acc = season_results[-1]['acc']
first_5 = np.mean([r['acc'] for r in season_results[:5]])
last_5 = np.mean([r['acc'] for r in season_results[-5:]])

print(f"\n  Overall accuracy:        {total_correct}/{total_matches} = {overall_acc:.2f}%")
print(f"  First season:           {first_acc:.2f}%")
print(f"  Last season:            {last_acc:.2f}%")
print(f"  Improvement (1st→last): {last_acc - first_acc:+.2f}pp")
print(f"  First 5 seasons avg:    {first_5:.2f}%")
print(f"  Last 5 seasons avg:     {last_5:.2f}%")
print(f"  Net progression:        {last_5 - first_5:+.2f}pp")

# Confusion matrix
print(f"\n  Confusion Matrix (All Predictions):")
print(f"  {'':20s} {'Pred H':8s} {'Pred D':8s} {'Pred A':8s}")
cm = np.zeros((3, 3), dtype=int)
for a, p in zip(all_actuals, all_predictions):
    cm[a, p] += 1
outcome_names = ['H', 'D', 'A']
for i, name in enumerate(outcome_names):
    print(f"  {'Actual ' + name:20s} {cm[i,0]:4d}     {cm[i,1]:4d}     {cm[i,2]:4d}")

# Per-class accuracy
print(f"\n  Per-class accuracy:")
for i, name in enumerate(outcome_names):
    total_cls = np.sum(cm[i, :])
    correct_cls = cm[i, i]
    prec = cm[:, i][i] / max(np.sum(cm[:, i]), 1)
    print(f"    {name:6s}: {correct_cls}/{total_cls} = {correct_cls/max(total_cls,1)*100:.1f}% (precision: {prec*100:.1f}%)")

# Top features (weight magnitude)
feature_names = [
    'p_home', 'p_draw', 'p_away', 'norm_oh', 'norm_od', 'norm_oa',
    'log_oh_od', 'log_oh_oa', 'log_od_oa', 'home_edge', 'draw_attract',
    'odds_spread', 'draw_odds_sig', 'md_norm', 'season_stage',
    'team_home_win', 'team_home_draw', 'team_home_loss',
    'team_away_loss', 'team_away_draw', 'team_away_win'
]

feature_importance = np.sum(np.abs(model.W), axis=1)
top_features = sorted(zip(feature_importance, feature_names), reverse=True)[:10]
print(f"\n  Top learned features (by weight magnitude):")
for imp, name in top_features:
    print(f"    {name:20s}: {imp:.4f}")
