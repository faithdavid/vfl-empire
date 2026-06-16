import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
import xgboost as xgb
import lightgbm as lgb
from sklearn.metrics import accuracy_score

# Load data locally
DATA_PATH = '/home/ubuntu/faith-workspace/vfl-empire/data/vfl_training_data.csv'
df = pd.read_csv(DATA_PATH)
print(f'✅ Loaded {len(df):,} rows')

# Feature engineering (from notebook Cell 3)
le_pred = LabelEncoder()
le_engine = LabelEncoder()
le_tier_h = LabelEncoder()
le_tier_a = LabelEncoder()

df['prediction_enc'] = le_pred.fit_transform(df['prediction'].fillna('Unknown'))
df['engine_enc']     = le_engine.fit_transform(df['engine'].fillna('Unknown'))
df['tier_home_enc']  = le_tier_h.fit_transform(df['tier_home'].fillna('mid'))
df['tier_away_enc']  = le_tier_a.fit_transform(df['tier_away'].fillna('mid'))

df['is_home_win']   = (df['prediction'] == 'Home Win').astype(int)
df['is_away_win']   = (df['prediction'] == 'Away Win').astype(int)
df['is_draw']       = df['prediction'].str.contains('Draw|DRAW|D$', regex=True).astype(int)
df['is_over']       = df['prediction'].str.contains('Over', case=False).astype(int)
df['is_under']      = df['prediction'].str.contains('Under', case=False).astype(int)
df['is_dnb']        = df['prediction'].str.contains('DNB', case=False).astype(int)

df['odds'] = pd.to_numeric(df['odds'], errors='coerce').fillna(1.5)
df['confidence'] = pd.to_numeric(df['confidence'], errors='coerce').fillna(50)
df['cv_1x2'] = pd.to_numeric(df['cv_1x2'], errors='coerce').fillna(0)
df['expected_value'] = (df['confidence'] / 100) * df['odds'] - 1
df['high_conf'] = (df['confidence'] >= 90).astype(int)
df['very_high_conf'] = (df['confidence'] >= 95).astype(int)

FEATURES = ['confidence', 'odds', 'cv_1x2', 'prediction_enc', 'engine_enc',
            'tier_home_enc', 'tier_away_enc', 'match_day',
            'is_home_win', 'is_away_win', 'is_draw', 'is_over', 'is_under', 'is_dnb',
            'expected_value', 'high_conf', 'very_high_conf']

X = df[FEATURES]
y = df['label']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

# Train XGBoost on CPU
print('🚀 Training XGBoost...')
xgb_model = xgb.XGBClassifier(
    n_estimators=500,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=3,
    eval_metric='logloss',
    early_stopping_rounds=30,
    random_state=42,
    verbosity=0
)
xgb_model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=100)
xgb_preds = xgb_model.predict(X_test)
xgb_probs = xgb_model.predict_proba(X_test)[:, 1]
print(f'✅ XGBoost Test Accuracy: {accuracy_score(y_test, xgb_preds)*100:.2f}%')

# Train LightGBM on CPU
print('⚡ Training LightGBM...')
lgb_model = lgb.LGBMClassifier(
    n_estimators=500,
    max_depth=7,
    learning_rate=0.05,
    num_leaves=63,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_samples=20,
    random_state=42,
    verbose=-1
)
lgb_model.fit(
    X_train, y_train,
    eval_set=[(X_test, y_test)],
    callbacks=[lgb.early_stopping(30), lgb.log_evaluation(100)]
)
lgb_preds = lgb_model.predict(X_test)
lgb_probs = lgb_model.predict_proba(X_test)[:, 1]
print(f'✅ LightGBM Test Accuracy: {accuracy_score(y_test, lgb_preds)*100:.2f}%')

# Ensemble
ensemble_probs = (xgb_probs + lgb_probs) / 2
ensemble_preds = (ensemble_probs >= 0.5).astype(int)
print('=== 🏆 Ensemble Results ===')
print(f'Overall Accuracy: {accuracy_score(y_test, ensemble_preds)*100:.2f}%')

# High-Confidence Filter Performance
print('\n=== High-Confidence Filter Performance ===')
X_test_df = X_test.copy()
X_test_df['ensemble_prob'] = ensemble_probs
X_test_df['true_label'] = y_test.values

thresholds = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
for t in thresholds:
    mask = X_test_df['ensemble_prob'] >= t
    filtered = X_test_df[mask]
    if len(filtered) > 10:
        acc = accuracy_score(filtered['true_label'], (filtered['ensemble_prob'] >= 0.5).astype(int))
        kept_pct = 100 * len(filtered) / len(X_test_df)
        print(f'  Prob >= {t:.0%}: {acc*100:.1f}% acc | {len(filtered):,} bets kept ({kept_pct:.1f}%)')
