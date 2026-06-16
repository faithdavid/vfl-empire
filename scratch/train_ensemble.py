import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import accuracy_score
import xgboost as xgb
import lightgbm as lgb
import pickle, json, os, shutil
from datetime import datetime

BASE_DIR = "/home/ubuntu/faith-workspace/vfl-empire"
MODELS_DIR = f"{BASE_DIR}/models"
DATA_PATH = f"{BASE_DIR}/data/vfl_training_data.csv"

def train_ensemble():
    print(f"🤖 Starting VFL Ensemble Training — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    if not os.path.exists(DATA_PATH):
        print(f"✗ Error: Training data not found at {DATA_PATH}")
        return
        
    df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(df):,} rows of training data.")

    # Back up existing models first
    os.makedirs(MODELS_DIR, exist_ok=True)
    for name in ["xgb_meta_v2.json", "lgb_meta_v2.txt", "encoders_v2.pkl", "training_summary_v2.json"]:
        p = os.path.join(MODELS_DIR, name)
        if os.path.exists(p):
            backup_path = p + ".bak"
            shutil.copy2(p, backup_path)
            print(f"  ✓ Backed up {name} to {name}.bak")

    # Feature engineering
    le_pred   = LabelEncoder()
    le_engine = LabelEncoder()
    le_tier_h = LabelEncoder()
    le_tier_a = LabelEncoder()

    df['prediction_enc'] = le_pred.fit_transform(df['prediction'].fillna('Unknown'))
    df['engine_enc']     = le_engine.fit_transform(df['engine'].fillna('Unknown'))
    df['tier_home_enc']  = le_tier_h.fit_transform(df['tier_home'].fillna('mid'))
    df['tier_away_enc']  = le_tier_a.fit_transform(df['tier_away'].fillna('mid'))

    df['is_home_win'] = (df['prediction'] == 'Home Win').astype(int)
    df['is_away_win'] = (df['prediction'] == 'Away Win').astype(int)
    df['is_draw']     = df['prediction'].str.contains('Draw|DRAW|D$', regex=True).astype(int)
    df['is_over']     = df['prediction'].str.contains('Over', case=False).astype(int)
    df['is_under']    = df['prediction'].str.contains('Under', case=False).astype(int)
    df['is_dnb']      = df['prediction'].str.contains('DNB', case=False).astype(int)

    df['odds']        = pd.to_numeric(df['odds'], errors='coerce').fillna(1.5)
    df['confidence']  = pd.to_numeric(df['confidence'], errors='coerce').fillna(50)
    df['cv_1x2']      = pd.to_numeric(df['cv_1x2'], errors='coerce').fillna(0)
    df['expected_value']   = (df['confidence'] / 100) * df['odds'] - 1
    df['high_conf']        = (df['confidence'] >= 90).astype(int)
    df['very_high_conf']   = (df['confidence'] >= 95).astype(int)

    FEATURES = ['confidence','odds','cv_1x2','prediction_enc','engine_enc',
                'tier_home_enc','tier_away_enc','match_day',
                'is_home_win','is_away_win','is_draw','is_over','is_under','is_dnb',
                'expected_value','high_conf','very_high_conf']

    X = df[FEATURES]
    y = df['label']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    print(f"Train size: {len(X_train):,} | Test size: {len(X_test):,}")

    # XGBoost
    print("Training XGBoost...")
    xgb_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
        tree_method='hist', random_state=42, verbosity=0,
        eval_metric='logloss', early_stopping_rounds=20
    )
    xgb_model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    xgb_probs = xgb_model.predict_proba(X_test)[:, 1]
    xgb_acc = accuracy_score(y_test, xgb_model.predict(X_test))
    print(f"XGBoost accuracy: {xgb_acc*100:.2f}%")

    # LightGBM
    print("Training LightGBM...")
    lgb_model = lgb.LGBMClassifier(
        n_estimators=300, max_depth=7, learning_rate=0.05,
        num_leaves=63, subsample=0.8, colsample_bytree=0.8,
        min_child_samples=20, random_state=42, verbose=-1
    )
    lgb_model.fit(X_train, y_train,
        eval_set=[(X_test, y_test)],
        callbacks=[lgb.early_stopping(20), lgb.log_evaluation(-1)])
    lgb_probs = lgb_model.predict_proba(X_test)[:, 1]
    lgb_acc = accuracy_score(y_test, lgb_model.predict(X_test))
    print(f"LightGBM accuracy: {lgb_acc*100:.2f}%")

    # Ensemble
    ensemble_probs = (xgb_probs + lgb_probs) / 2
    ensemble_preds = (ensemble_probs >= 0.5).astype(int)
    ensemble_acc = accuracy_score(y_test, ensemble_preds)
    print(f"Ensemble accuracy: {ensemble_acc*100:.2f}%")

    # High-confidence analysis
    print("\nHigh-confidence filter results:")
    for t in [0.60, 0.65, 0.70, 0.75, 0.80]:
        mask = ensemble_probs >= t
        if mask.sum() > 10:
            acc = accuracy_score(y_test[mask], ensemble_preds[mask])
            print(f"  Prob >= {t:.0%}: {acc*100:.1f}% acc on {mask.sum():,} bets ({100*mask.sum()/len(X_test):.1f}% kept)")

    # Save models
    print(f"\nSaving models to {MODELS_DIR}...")
    xgb_model.save_model(f'{MODELS_DIR}/xgb_meta_v2.json')
    lgb_model.booster_.save_model(f'{MODELS_DIR}/lgb_meta_v2.txt')
    with open(f'{MODELS_DIR}/encoders_v2.pkl', 'wb') as f:
        pickle.dump({'prediction': le_pred, 'engine': le_engine,
                     'tier_home': le_tier_h, 'tier_away': le_tier_a,
                     'features': FEATURES}, f)

    summary = {
        'xgb_accuracy': round(xgb_acc, 4),
        'lgb_accuracy': round(lgb_acc, 4),
        'ensemble_accuracy': round(ensemble_acc, 4),
        'training_rows': len(X_train),
        'test_rows': len(X_test),
        'features': FEATURES,
        'trained_at': datetime.now().isoformat()
    }
    with open(f'{MODELS_DIR}/training_summary_v2.json', 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"\n✅ All ensemble models saved to {MODELS_DIR}/")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    train_ensemble()
