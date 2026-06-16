#!/usr/bin/env python3
"""
VFL Rolling Window Time-Series Pipeline
========================================
- Loads all historical match data from PostgreSQL
- Engineers H2H, rolling form, matchday-position, streak features
- Runs TimeSeriesSplit walk-forward validation across lookback windows: ALL / 20 / 10 / 5 / 2 seasons
- Models: LightGBM + XGBoost + Logistic Regression (stacked)
- Outputs: accuracy per window, per-team accuracy, fixture-level confidence, charts
"""

import psycopg2
import pandas as pd
import numpy as np
import warnings
import json
import os
import sys
from datetime import datetime

# ML imports
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, log_loss, classification_report
import lightgbm as lgb
import xgboost as xgb
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings('ignore')

OUTPUT_DIR = "/home/ubuntu/.gemini/antigravity-cli/brain/751aa9ef-b0a3-4429-8498-9c8a6b4df046"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

print("=" * 70)
print("VFL ROLLING WINDOW TIME-SERIES PIPELINE")
print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

# ─────────────────────────────────────────────
# 1. LOAD DATA
# ─────────────────────────────────────────────
print("\n[1/6] Loading data from PostgreSQL...")

conn = psycopg2.connect(dbname='vfl_empire', user='ubuntu')
query = """
SELECT 
    s.season_name,
    md.matchday_number,
    r.home_team,
    r.away_team,
    r.home_goals,
    r.away_goals,
    r.total_goals,
    r.captured_at
FROM vfl_results_v2 r
JOIN vfl_matchdays md ON r.matchday_id = md.id
JOIN vfl_seasons s ON md.season_id = s.id
WHERE r.home_goals IS NOT NULL AND r.away_goals IS NOT NULL
ORDER BY s.season_name, md.matchday_number, r.home_team
"""
df = pd.read_sql(query, conn)
conn.close()

# Parse season number for sorting
df['season_num'] = df['season_name'].str.extract(r'(\d+)').astype(int)
df = df.sort_values(['season_num', 'matchday_number', 'home_team']).reset_index(drop=True)

# Outcome label: 0=Home Win, 1=Draw, 2=Away Win
def get_outcome(row):
    if row['home_goals'] > row['away_goals']:
        return 0
    elif row['home_goals'] == row['away_goals']:
        return 1
    else:
        return 2

df['outcome'] = df.apply(get_outcome, axis=1)
df['outcome_label'] = df['outcome'].map({0: 'H', 1: 'D', 2: 'A'})

print(f"  Loaded {len(df):,} matches across {df['season_num'].nunique()} seasons")
print(f"  Season range: VFLM {df['season_num'].min()} → VFLM {df['season_num'].max()}")
print(f"  Outcome distribution: {df['outcome_label'].value_counts().to_dict()}")

# ─────────────────────────────────────────────
# 2. FEATURE ENGINEERING
# ─────────────────────────────────────────────
print("\n[2/6] Engineering features...")

def engineer_features(df):
    """
    Build rolling-window features for each match:
    - H2H history (last N meetings between these two teams)
    - Team form: rolling 5 & 10 match win rates (home & away separately)
    - Streak: current consecutive wins/losses
    - Matchday position (early/mid/late season signal)
    - Goals scored/conceded rolling averages
    """
    df = df.copy()
    
    # ---- H2H features ----
    # For each match, look back at previous meetings of this exact pair
    h2h_records = {}  # (home, away) -> list of outcomes in chronological order
    
    h2h_hw_rate = []  # home win rate in last N h2h
    h2h_draw_rate = []
    h2h_aw_rate = []
    h2h_count = []
    
    # Per-team rolling stats
    team_stats = {}  # team -> deque of (goals_scored, goals_conceded, outcome_from_team_perspective)
    
    home_form_5 = []
    home_form_10 = []
    away_form_5 = []
    away_form_10 = []
    home_goals_avg5 = []
    away_goals_avg5 = []
    home_conceded_avg5 = []
    away_conceded_avg5 = []
    home_streak = []
    away_streak = []
    matchday_norm = []
    
    for _, row in df.iterrows():
        ht = row['home_team']
        at = row['away_team']
        md = row['matchday_number']
        
        # Matchday normalized (38 matchdays assumed)
        matchday_norm.append(md / 38.0)
        
        # H2H lookup
        key = tuple(sorted([ht, at]))
        past = h2h_records.get(key, [])
        n = len(past)
        h2h_count.append(n)
        if n > 0:
            hw = sum(1 for o in past if o == f'{ht}_win') / n
            dr = sum(1 for o in past if o == 'draw') / n
            aw = sum(1 for o in past if o == f'{at}_win') / n
        else:
            hw, dr, aw = 1/3, 1/3, 1/3
        h2h_hw_rate.append(hw)
        h2h_draw_rate.append(dr)
        h2h_aw_rate.append(aw)
        
        # Team form helpers
        def get_team_form(team, n=5, stat='win'):
            records = team_stats.get(team, [])
            recent = records[-n:] if len(records) >= n else records
            if not recent:
                return 0.33
            if stat == 'win':
                return sum(1 for r in recent if r['result'] == 'W') / len(recent)
            elif stat == 'goals_scored':
                return np.mean([r['scored'] for r in recent])
            elif stat == 'goals_conceded':
                return np.mean([r['conceded'] for r in recent])
            return 0.0
        
        def get_streak(team):
            records = team_stats.get(team, [])
            if not records:
                return 0
            last = records[-1]['result']
            streak = 0
            for r in reversed(records):
                if r['result'] == last:
                    streak += 1
                else:
                    break
            return streak if last == 'W' else -streak
        
        home_form_5.append(get_team_form(ht, 5, 'win'))
        home_form_10.append(get_team_form(ht, 10, 'win'))
        away_form_5.append(get_team_form(at, 5, 'win'))
        away_form_10.append(get_team_form(at, 10, 'win'))
        home_goals_avg5.append(get_team_form(ht, 5, 'goals_scored'))
        away_goals_avg5.append(get_team_form(at, 5, 'goals_scored'))
        home_conceded_avg5.append(get_team_form(ht, 5, 'goals_conceded'))
        away_conceded_avg5.append(get_team_form(at, 5, 'goals_conceded'))
        home_streak.append(get_streak(ht))
        away_streak.append(get_streak(at))
        
        # Now UPDATE records with this match's outcome
        hg = row['home_goals']
        ag = row['away_goals']
        
        if hg > ag:
            h_result, a_result = 'W', 'L'
            h2h_outcome = f'{ht}_win'
        elif hg == ag:
            h_result, a_result = 'D', 'D'
            h2h_outcome = 'draw'
        else:
            h_result, a_result = 'L', 'W'
            h2h_outcome = f'{at}_win'
        
        if ht not in team_stats:
            team_stats[ht] = []
        if at not in team_stats:
            team_stats[at] = []
        
        team_stats[ht].append({'result': h_result, 'scored': hg, 'conceded': ag})
        team_stats[at].append({'result': a_result, 'scored': ag, 'conceded': hg})
        
        # Keep only last 20 for memory efficiency
        if len(team_stats[ht]) > 20:
            team_stats[ht] = team_stats[ht][-20:]
        if len(team_stats[at]) > 20:
            team_stats[at] = team_stats[at][-20:]
        
        h2h_records[key] = (past + [h2h_outcome])[-20:]  # keep last 20 H2H
    
    df['h2h_hw_rate'] = h2h_hw_rate
    df['h2h_draw_rate'] = h2h_draw_rate
    df['h2h_aw_rate'] = h2h_aw_rate
    df['h2h_count'] = h2h_count
    df['home_form_5'] = home_form_5
    df['home_form_10'] = home_form_10
    df['away_form_5'] = away_form_5
    df['away_form_10'] = away_form_10
    df['home_goals_avg5'] = home_goals_avg5
    df['away_goals_avg5'] = away_goals_avg5
    df['home_conceded_avg5'] = home_conceded_avg5
    df['away_conceded_avg5'] = away_conceded_avg5
    df['home_streak'] = home_streak
    df['away_streak'] = away_streak
    df['matchday_norm'] = matchday_norm
    df['form_diff'] = df['home_form_5'] - df['away_form_5']
    df['goals_diff_avg'] = df['home_goals_avg5'] - df['away_goals_avg5']
    df['streak_diff'] = df['home_streak'] - df['away_streak']
    
    # Encode teams
    le = LabelEncoder()
    all_teams = pd.concat([df['home_team'], df['away_team']])
    le.fit(all_teams)
    df['home_team_enc'] = le.transform(df['home_team'])
    df['away_team_enc'] = le.transform(df['away_team'])
    
    return df, le

df_feat, team_encoder = engineer_features(df)
print(f"  Feature engineering complete. Shape: {df_feat.shape}")

FEATURE_COLS = [
    'home_team_enc', 'away_team_enc',
    'matchday_norm',
    'h2h_hw_rate', 'h2h_draw_rate', 'h2h_aw_rate', 'h2h_count',
    'home_form_5', 'home_form_10',
    'away_form_5', 'away_form_10',
    'home_goals_avg5', 'away_goals_avg5',
    'home_conceded_avg5', 'away_conceded_avg5',
    'home_streak', 'away_streak',
    'form_diff', 'goals_diff_avg', 'streak_diff'
]

# ─────────────────────────────────────────────
# 3. ROLLING WINDOW CHRONOLOGICAL VALIDATION
# ─────────────────────────────────────────────
print("\n[3/6] Running walk-forward TimeSeriesSplit across lookback windows...")

seasons_sorted = sorted(df_feat['season_num'].unique())
N_seasons = len(seasons_sorted)
print(f"  Total seasons available: {N_seasons}")

LOOKBACK_WINDOWS = {
    'ALL': None,   # use all available history
    '20': 20,
    '10': 10,
    '5': 5,
    '2': 2,
}

# We always predict the NEXT season given the lookback window of training seasons
# Walk-forward: train on [s-W .. s-1], test on [s]

results_summary = {}

def train_and_eval(X_train, y_train, X_test, y_test):
    """Train LightGBM + Logistic ensemble, return accuracy and probabilities."""
    if len(X_train) < 10 or len(np.unique(y_train)) < 2:
        return None, None, None
    
    # LightGBM
    lgb_model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=10,
        random_state=42,
        verbose=-1,
        n_jobs=1
    )
    lgb_model.fit(X_train, y_train)
    lgb_proba = lgb_model.predict_proba(X_test)
    
    # XGBoost
    xgb_model = xgb.XGBClassifier(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=4,
        random_state=42,
        eval_metric='mlogloss',
        verbosity=0,
        use_label_encoder=False
    )
    xgb_model.fit(X_train, y_train)
    xgb_proba = xgb_model.predict_proba(X_test)
    
    # Logistic Regression
    lr_model = LogisticRegression(max_iter=1000, random_state=42, C=1.0)
    lr_model.fit(X_train, y_train)
    lr_proba = lr_model.predict_proba(X_test)
    
    # Ensemble average
    ensemble_proba = (lgb_proba * 0.45 + xgb_proba * 0.35 + lr_proba * 0.20)
    preds = np.argmax(ensemble_proba, axis=1)
    acc = accuracy_score(y_test, preds)
    
    return acc, preds, ensemble_proba

all_window_results = {}

for window_name, window_size in LOOKBACK_WINDOWS.items():
    print(f"\n  ── Window: {window_name} seasons ──")
    fold_accuracies = []
    fold_sizes = []
    per_season_results = []
    
    # Walk forward: at least 5 training seasons before we start testing
    min_train = 5 if window_size is None else window_size
    
    for i, test_season in enumerate(seasons_sorted[min_train:], start=min_train):
        if window_size is None:
            train_seasons = seasons_sorted[:i]
        else:
            start_idx = max(0, i - window_size)
            train_seasons = seasons_sorted[start_idx:i]
        
        train_df = df_feat[df_feat['season_num'].isin(train_seasons)]
        test_df = df_feat[df_feat['season_num'] == test_season]
        
        if len(train_df) < 50 or len(test_df) < 5:
            continue
        
        X_train = train_df[FEATURE_COLS].values
        y_train = train_df['outcome'].values
        X_test = test_df[FEATURE_COLS].values
        y_test = test_df['outcome'].values
        
        acc, preds, proba = train_and_eval(X_train, y_train, X_test, y_test)
        if acc is None:
            continue
        
        fold_accuracies.append(acc)
        fold_sizes.append(len(test_df))
        per_season_results.append({
            'season': test_season,
            'accuracy': acc,
            'n_matches': len(test_df),
            'train_size': len(train_df)
        })
        
        if (i - min_train) % 20 == 0:
            print(f"    Season VFLM {test_season}: acc={acc:.3f} (train={len(train_df)}, test={len(test_df)})")
    
    if fold_accuracies:
        # Weighted accuracy (by number of matches per season)
        weights = np.array(fold_sizes)
        weighted_acc = np.average(fold_accuracies, weights=weights)
        mean_acc = np.mean(fold_accuracies)
        std_acc = np.std(fold_accuracies)
        
        all_window_results[window_name] = {
            'mean_accuracy': mean_acc,
            'weighted_accuracy': weighted_acc,
            'std': std_acc,
            'n_folds': len(fold_accuracies),
            'per_season': per_season_results
        }
        print(f"    → Mean Acc: {mean_acc:.4f} | Weighted Acc: {weighted_acc:.4f} | Std: {std_acc:.4f} | Folds: {len(fold_accuracies)}")
    else:
        print(f"    → No valid folds produced")

# ─────────────────────────────────────────────
# 4. FIXTURE-LEVEL H2H PATTERN ANALYSIS
# ─────────────────────────────────────────────
print("\n[4/6] H2H fixture pattern analysis (5-MD and 10-MD rolling windows)...")

# For each unique team pair, compute rolling outcome consistency
pair_stats = []
pairs = df_feat.groupby(['home_team', 'away_team'])

for (ht, at), grp in pairs:
    grp = grp.sort_values(['season_num', 'matchday_number'])
    n = len(grp)
    if n < 3:
        continue
    
    outcomes = grp['outcome'].tolist()
    
    # Rolling 5-match window: how consistent?
    consistency_5 = []
    for j in range(4, n):
        window = outcomes[max(0, j-4):j+1]
        mode_count = max(pd.Series(window).value_counts())
        consistency_5.append(mode_count / len(window))
    
    # Rolling 10-match window
    consistency_10 = []
    for j in range(9, n):
        window = outcomes[max(0, j-9):j+1]
        mode_count = max(pd.Series(window).value_counts())
        consistency_10.append(mode_count / len(window))
    
    outcome_counts = pd.Series(outcomes).value_counts()
    dominant = outcome_counts.index[0]
    dominance_rate = outcome_counts.iloc[0] / n
    
    pair_stats.append({
        'home_team': ht,
        'away_team': at,
        'n_meetings': n,
        'dominant_outcome': {0: 'H', 1: 'D', 2: 'A'}[dominant],
        'dominance_rate': dominance_rate,
        'consistency_5_avg': np.mean(consistency_5) if consistency_5 else None,
        'consistency_10_avg': np.mean(consistency_10) if consistency_10 else None,
    })

pair_df = pd.DataFrame(pair_stats)
pair_df = pair_df.dropna()
pair_df = pair_df.sort_values('dominance_rate', ascending=False)

print(f"  Analysed {len(pair_df)} unique H2H fixture pairs")
print(f"  Top 10 most dominant fixture outcomes:")
print(pair_df[['home_team', 'away_team', 'n_meetings', 'dominant_outcome', 'dominance_rate', 'consistency_5_avg']].head(10).to_string(index=False))

# High confidence fixtures (>75% dominant outcome)
high_conf = pair_df[pair_df['dominance_rate'] >= 0.75]
print(f"\n  Fixtures with ≥75% outcome dominance: {len(high_conf)}")
print(f"  Avg consistency (5-MD window): {pair_df['consistency_5_avg'].mean():.3f}")
print(f"  Avg consistency (10-MD window): {pair_df['consistency_10_avg'].mean():.3f}")

# ─────────────────────────────────────────────
# 5. VISUALISATIONS
# ─────────────────────────────────────────────
print("\n[5/6] Generating charts...")

fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('VFL Rolling Window Time-Series Analysis', fontsize=16, fontweight='bold', y=0.98)
colors = ['#2196F3', '#4CAF50', '#FF9800', '#E91E63', '#9C27B0']

# Plot 1: Accuracy by window size (summary bar)
ax1 = axes[0, 0]
window_names = list(all_window_results.keys())
mean_accs = [all_window_results[w]['mean_accuracy'] for w in window_names]
weighted_accs = [all_window_results[w]['weighted_accuracy'] for w in window_names]
x = np.arange(len(window_names))
bars1 = ax1.bar(x - 0.2, mean_accs, 0.35, label='Mean Accuracy', color='#2196F3', alpha=0.85)
bars2 = ax1.bar(x + 0.2, weighted_accs, 0.35, label='Weighted Accuracy', color='#4CAF50', alpha=0.85)
ax1.axhline(y=1/3, color='red', linestyle='--', alpha=0.7, label='Random Baseline (33.3%)')
ax1.set_xlabel('Lookback Window (seasons)')
ax1.set_ylabel('Accuracy')
ax1.set_title('Ensemble Accuracy by Lookback Window')
ax1.set_xticks(x)
ax1.set_xticklabels([f'{w}\nseasons' for w in window_names])
ax1.legend(fontsize=8)
ax1.set_ylim(0.25, 0.65)
for bar in bars1:
    ax1.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.005, 
             f'{bar.get_height():.3f}', ha='center', va='bottom', fontsize=8)
for bar in bars2:
    ax1.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.005, 
             f'{bar.get_height():.3f}', ha='center', va='bottom', fontsize=8)

# Plot 2: Per-season accuracy over time for "ALL" window
ax2 = axes[0, 1]
if 'ALL' in all_window_results:
    ps = all_window_results['ALL']['per_season']
    seasons_x = [r['season'] for r in ps]
    accs_y = [r['accuracy'] for r in ps]
    ax2.plot(seasons_x, accs_y, color='#2196F3', alpha=0.6, linewidth=0.8)
    # Rolling average
    roll = pd.Series(accs_y).rolling(10, min_periods=3).mean()
    ax2.plot(seasons_x, roll.values, color='#E91E63', linewidth=2, label='10-season rolling avg')
    ax2.axhline(y=1/3, color='red', linestyle='--', alpha=0.7, label='Baseline')
    ax2.set_xlabel('Season Number')
    ax2.set_ylabel('Accuracy')
    ax2.set_title('Prediction Accuracy Over Time (ALL window)')
    ax2.legend(fontsize=8)
    ax2.set_ylim(0.0, 1.0)

# Plot 3: H2H dominance distribution
ax3 = axes[1, 0]
ax3.hist(pair_df['dominance_rate'], bins=30, color='#FF9800', edgecolor='white', alpha=0.85)
ax3.axvline(x=0.75, color='red', linestyle='--', label='75% threshold')
ax3.axvline(x=pair_df['dominance_rate'].mean(), color='blue', linestyle='--', 
            label=f'Mean: {pair_df["dominance_rate"].mean():.2f}')
ax3.set_xlabel('Dominant Outcome Rate')
ax3.set_ylabel('Number of Fixtures')
ax3.set_title('H2H Fixture Outcome Dominance Distribution')
ax3.legend(fontsize=8)

# Plot 4: Per-season accuracy for all windows overlaid
ax4 = axes[1, 1]
for w, col in zip(['ALL', '20', '10', '5'], ['#2196F3', '#4CAF50', '#FF9800', '#E91E63']):
    if w in all_window_results:
        ps = all_window_results[w]['per_season']
        sx = [r['season'] for r in ps]
        ay = pd.Series([r['accuracy'] for r in ps]).rolling(10, min_periods=3).mean().values
        ax4.plot(sx, ay, color=col, linewidth=1.8, label=f'Window={w}', alpha=0.85)
ax4.axhline(y=1/3, color='black', linestyle='--', alpha=0.6, label='Baseline')
ax4.set_xlabel('Season Number')
ax4.set_ylabel('Rolling Accuracy (10-season avg)')
ax4.set_title('Window Size Comparison (rolling avg)')
ax4.legend(fontsize=8)
ax4.set_ylim(0.2, 0.7)

plt.tight_layout()
out_path = os.path.join(OUTPUT_DIR, 'rolling_window_ts_analysis.png')
plt.savefig(out_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved → {out_path}")

# ─────────────────────────────────────────────
# 6. SAVE RESULTS REPORT
# ─────────────────────────────────────────────
print("\n[6/6] Writing results report...")

report_path = os.path.join(OUTPUT_DIR, 'rolling_window_ts_report.md')
with open(report_path, 'w') as f:
    f.write("# VFL Rolling Window Time-Series Report\n\n")
    f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
    f.write(f"**Dataset:** {len(df):,} matches | {df['season_num'].nunique()} seasons  \n\n")
    
    f.write("## 1. Walk-Forward Accuracy by Lookback Window\n\n")
    f.write("| Window | Mean Acc | Weighted Acc | Std | Folds |\n")
    f.write("|--------|----------|--------------|-----|-------|\n")
    for w, res in all_window_results.items():
        f.write(f"| {w} seasons | {res['mean_accuracy']:.4f} | {res['weighted_accuracy']:.4f} | {res['std']:.4f} | {res['n_folds']} |\n")
    
    f.write("\n> **Baseline (random guess):** 33.3%\n\n")
    
    f.write("## 2. H2H Fixture Patterns\n\n")
    f.write(f"- **Total unique H2H pairs analysed:** {len(pair_df)}\n")
    f.write(f"- **Fixtures with ≥75% dominance:** {len(high_conf)} ({100*len(high_conf)/len(pair_df):.1f}%)\n")
    f.write(f"- **Avg outcome consistency (5-MD window):** {pair_df['consistency_5_avg'].mean():.3f}\n")
    f.write(f"- **Avg outcome consistency (10-MD window):** {pair_df['consistency_10_avg'].mean():.3f}\n\n")
    
    f.write("### Top 20 Most Dominant Fixtures\n\n")
    f.write("| Home | Away | Meetings | Dominant | Rate | 5-MD Consistency |\n")
    f.write("|------|------|----------|----------|------|------------------|\n")
    for _, row in pair_df.head(20).iterrows():
        f.write(f"| {row['home_team']} | {row['away_team']} | {int(row['n_meetings'])} | {row['dominant_outcome']} | {row['dominance_rate']:.3f} | {row['consistency_5_avg']:.3f} |\n")
    
    f.write("\n## 3. Best Lookback Window\n\n")
    best_w = max(all_window_results, key=lambda w: all_window_results[w]['weighted_accuracy'])
    best_acc = all_window_results[best_w]['weighted_accuracy']
    f.write(f"The **{best_w}-season** lookback window produced the best weighted accuracy: **{best_acc:.4f}**\n\n")
    lift = (best_acc - 1/3) / (1/3) * 100
    f.write(f"Lift over random baseline: **+{lift:.1f}%**\n\n")

print(f"  Report saved → {report_path}")

# Save JSON summary
json_path = os.path.join(OUTPUT_DIR, 'scratch', 'rolling_window_summary.json')
summary_out = {}
for w, res in all_window_results.items():
    summary_out[w] = {
        'mean_accuracy': res['mean_accuracy'],
        'weighted_accuracy': res['weighted_accuracy'],
        'std': res['std'],
        'n_folds': res['n_folds']
    }
with open(json_path, 'w') as f:
    json.dump(summary_out, f, indent=2)
print(f"  JSON summary saved → {json_path}")

print("\n" + "=" * 70)
print("PIPELINE COMPLETE")
print("=" * 70)
print(f"\nResults summary:")
for w, res in all_window_results.items():
    print(f"  Window {w:>4}s: mean={res['mean_accuracy']:.4f} | weighted={res['weighted_accuracy']:.4f}")
best_w = max(all_window_results, key=lambda w: all_window_results[w]['weighted_accuracy'])
print(f"\n  ★ Best window: {best_w} seasons → {all_window_results[best_w]['weighted_accuracy']:.4f}")
print(f"  ★ Lift over random: +{(all_window_results[best_w]['weighted_accuracy'] - 1/3)/(1/3)*100:.1f}%")
print(f"\nArtifacts written to: {OUTPUT_DIR}")
