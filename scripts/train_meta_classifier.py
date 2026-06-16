import os, sys, json, time
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
import lightgbm as lgb
import xgboost as xgb
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services"))
from common.db_manager import get_db

def load_data():
    print("Fetching settled predictions from Postgres...")
    query = """
        SELECT id, season, match_day, home_team, away_team, prediction, confidence, odds, 
               tier_home, tier_away, predicted_score, result 
        FROM vfl_predictions 
        WHERE settled = 1 AND result IN ('won', 'lost')
    """
    with get_db() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        
    cols = ['id', 'season', 'match_day', 'home_team', 'away_team', 'prediction', 'confidence', 'odds',
            'tier_home', 'tier_away', 'predicted_score', 'result']
    df = pd.DataFrame(rows, columns=cols)
    print(f"Loaded {len(df)} rows.")
    return df

def feature_engineering(df):
    print("Engineering features...")
    df = df.copy()
    
    # Target: 1 if won, 0 if lost
    df['target'] = (df['result'] == 'won').astype(int)
    
    # Process predicted score
    def parse_score(score_str):
        if not score_str or ':' not in str(score_str):
            return 0.0, 0.0, 0.0
        try:
            h, a = map(float, str(score_str).split(':'))
            return h, a, h + a
        except:
            return 0.0, 0.0, 0.0
            
    parsed = df['predicted_score'].apply(parse_score)
    df['pred_h_goals'] = [p[0] for p in parsed]
    df['pred_a_goals'] = [p[1] for p in parsed]
    df['pred_total_goals'] = [p[2] for p in parsed]
    
    # Process categorical variables
    encoders = {}
    for col in ['prediction', 'tier_home', 'tier_away']:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col].astype(str))
        encoders[col] = le
        
    features = ['match_day', 'prediction', 'confidence', 'odds', 'tier_home', 'tier_away', 
                'pred_h_goals', 'pred_a_goals', 'pred_total_goals']
    
    return df, features, encoders

def train_model():
    df = load_data()
    if len(df) < 100:
        print("Not enough data to train.")
        return
        
    df, features, encoders = feature_engineering(df)
    
    X = df[features]
    y = df['target']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print("Training LightGBM Meta-Classifier...")
    model = lgb.LGBMClassifier(n_estimators=150, max_depth=6, learning_rate=0.05, random_state=42)
    model.fit(X_train, y_train)
    
    # Evaluate
    train_acc = model.score(X_train, y_train)
    test_acc = model.score(X_test, y_test)
    
    # Get predictions and probabilities
    test_probs = model.predict_proba(X_test)[:, 1]
    
    # High confidence filters (e.g. only predict 'Win' if probability >= 0.8)
    high_conf_idx = test_probs >= 0.75
    high_conf_acc = np.mean(y_test[high_conf_idx] == 1) if np.sum(high_conf_idx) > 0 else 0.0
    
    print("\n=== Meta-Classifier Performance ===")
    print(f"Overall Train Accuracy: {train_acc:.2%}")
    print(f"Overall Test Accuracy:  {test_acc:.2%}")
    print(f"High-Confidence Filter (Prob >= 75%) Accuracy: {high_conf_acc:.2%}")
    print(f"Filtered out {100 - (np.sum(high_conf_idx) / len(y_test) * 100):.1f}% of predictions to keep win rate high.")
    
    # Save the model files
    os.makedirs('models', exist_ok=True)
    model.booster_.save_model('models/meta_classifier.txt')
    print("Model saved to models/meta_classifier.txt")
    
if __name__ == "__main__":
    train_model()
