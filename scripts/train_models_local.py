import sys
import pickle
import json
import logging
from pathlib import Path
import pandas as pd
import numpy as np
import xgboost as xgb
import lightgbm as lgb
from sklearn.metrics import accuracy_score, roc_auc_score, brier_score_loss
from sklearn.isotonic import IsotonicRegression
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [TRAINER] %(message)s")
log = logging.getLogger("trainer")

# Define project paths
PROJECT_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_DIR / "services"))
from common.db_manager import get_db

DATA_PATH = PROJECT_DIR / "data" / "vfl_rich_features.csv"
MODELS_DIR = PROJECT_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Features list
FEATURES = [
    # League table — home
    'home_rank', 'home_points', 'home_played',
    'home_goals_per_game', 'home_goals_against_per_game', 'home_goal_diff_per_game',
    'home_win_rate', 'home_draw_rate', 'home_form_score', 'home_points_per_game',
    # League table — away
    'away_rank', 'away_points', 'away_played',
    'away_goals_per_game', 'away_goals_against_per_game', 'away_goal_diff_per_game',
    'away_win_rate', 'away_draw_rate', 'away_form_score', 'away_points_per_game',
    # Differentials
    'rank_diff', 'points_diff', 'form_diff', 'goals_diff', 'expected_total_goals',
    # H2H
    'h2h_count', 'h2h_home_win_rate', 'h2h_draw_rate', 'h2h_away_win_rate',
    'h2h_avg_goals', 'h2h_std_goals',
    'h2h_over_15_rate', 'h2h_over_25_rate', 'h2h_over_35_rate',
    'h2h_under_25_rate', 'h2h_under_35_rate',
    'h2h_gg_rate', 'h2h_ng_rate', 'h2h_data_quality',
    # Season regime
    'season_avg_goals', 'season_over_15_rate', 'season_over_25_rate',
    'season_over_35_rate', 'season_under_35_rate', 'season_gg_rate',
    # Odds / implied probs
    'odds_home', 'odds_draw', 'odds_away',
    'odds_over_15', 'odds_under_35', 'odds_over_25', 'odds_gg',
    'impl_home', 'impl_draw', 'impl_away',
    'impl_over_15', 'impl_under_35', 'impl_over_25', 'impl_gg',
    # Context
    'matchday',
]

MARKETS = {
    'over_15': 'target_over_15',
    'under_35': 'target_under_35',
    'gg': 'target_gg',
    'home_win': 'target_home_win',
    'draw': 'target_draw',
    'away_win': 'target_away_win',
    'over_25': 'target_over_25',
    'under_25': 'target_under_25',
}

def train_market_model(df, features, target_col, market_name):
    log.info(f"Training: {market_name.upper()} -> {target_col}")
    
    # Filter rows
    mask = df[target_col].notna() & df[features].notna().all(axis=1)
    X = df.loc[mask, features].fillna(0).values
    y = df.loc[mask, target_col].values.astype(int)
    
    if len(X) < 500:
        log.warning(f"Skipping {market_name} - only {len(X)} rows")
        return None
        
    log.info(f"  Rows: {len(X):,} | Positive rate: {y.mean():.1%}")
    
    # Train / Val Split (last 20% validation)
    split = int(len(X) * 0.80)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]
    
    # XGBoost
    xgb_model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric='logloss',
        early_stopping_rounds=20
    )
    xgb_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    xgb_p = xgb_model.predict_proba(X_val)[:, 1]
    
    # LightGBM
    lgb_model = lgb.LGBMClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        verbose=-1
    )
    lgb_model.fit(X_train, y_train)
    lgb_p = lgb_model.predict_proba(X_val)[:, 1]
    
    # Ensemble
    ens_p = (xgb_p + lgb_p) / 2
    acc = accuracy_score(y_val, ens_p >= 0.5)
    auc = roc_auc_score(y_val, ens_p)
    log.info(f"  Ensemble: Acc={acc:.3f} | AUC={auc:.3f}")
    
    # Calibration
    iso = IsotonicRegression(out_of_bounds='clip')
    iso.fit(ens_p, y_val)
    
    return {
        'xgb': xgb_model,
        'lgb': lgb_model,
        'iso': iso,
        'val_acc': acc,
        'val_auc': auc,
        'train_rows': len(X_train),
    }

def main():
    if not DATA_PATH.exists():
        log.error(f"Training data not found at {DATA_PATH}. Run feature_builder.py first.")
        sys.exit(1)
        
    df = pd.read_csv(DATA_PATH)
    log.info(f"Loaded training data: {len(df):,} rows")
    
    # Filter features to those present in DataFrame
    avail_features = [f for f in FEATURES if f in df.columns]
    log.info(f"Using {len(avail_features)} of {len(FEATURES)} features")
    
    summary = {}
    for market_name, target_col in MARKETS.items():
        if target_col not in df.columns:
            log.warning(f"Target column {target_col} not in dataset. Skipping.")
            continue
            
        res = train_market_model(df, avail_features, target_col, market_name)
        if res:
            # Save XGBoost
            xgb_path = MODELS_DIR / f"xgb_{market_name}.json"
            res['xgb'].save_model(str(xgb_path))
            
            # Save LightGBM
            lgb_path = MODELS_DIR / f"lgb_{market_name}.txt"
            res['lgb'].booster_.save_model(str(lgb_path))
            
            # Save Isotonic calibrator
            iso_path = MODELS_DIR / f"iso_{market_name}.pkl"
            with open(iso_path, 'wb') as f:
                pickle.dump(res['iso'], f)
                
            summary[market_name] = {
                'val_acc': round(float(res['val_acc']), 4),
                'val_auc': round(float(res['val_auc']), 4),
                'train_rows': res['train_rows'],
                'xgb_path': str(xgb_path),
                'lgb_path': str(lgb_path),
                'iso_path': str(iso_path),
            }
            
    # Save features list
    with open(MODELS_DIR / "model_features.json", "w") as f:
        json.dump({"features": avail_features, "markets": list(summary.keys())}, f, indent=2)
        
    # Save summary
    with open(MODELS_DIR / "training_summary_rich.json", "w") as f:
        json.dump(summary, f, indent=2)
        
    log.info("=== LOCAL TRAINING COMPLETE ===")
    for m, s in summary.items():
        log.info(f"  {m:12s}: Acc={s['val_acc']:.3f} | AUC={s['val_auc']:.3f}")

if __name__ == "__main__":
    main()
