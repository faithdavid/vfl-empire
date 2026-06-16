"""Prediction Engine Service (port 8002) — Oracle scoring + Rich ML Ensemble."""
import asyncio
import json
import logging
import os
import sys
import time
import pickle
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

import pandas as pd
import numpy as np
import xgboost as xgb
import lightgbm as lgb

from fastapi import FastAPI, BackgroundTasks, Query, HTTPException
import uvicorn

# Setup paths
PROJECT_DIR = Path(__file__).parents[2]
sys.path.insert(0, str(PROJECT_DIR / "services"))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from common.msport_client import get_event_list, get_match_day_info
from common.db_manager import get_db
from dynamic_team_classifier import DynamicTeamClassifier, _normalize_team
from sequence_oracle import find_sequence_clones, get_team_sequence
from feature_builder import build_live_fixture_features, get_league_features

logger = logging.getLogger("[PREDICTOR]")
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")

DATA_DIR = os.path.expanduser("~/faith-workspace/vfl-complete-data")
SIGNALS_DIR = os.path.join(DATA_DIR, "signals")
os.makedirs(SIGNALS_DIR, exist_ok=True)

# In-memory prediction cache
_latest_predictions = {"matchdays": [], "summary": {}}

# Models dir
MODELS_DIR = PROJECT_DIR / "models"
_models_loaded = False
_xgb_models = {}
_lgb_models = {}
_iso_models = {}
_feature_names = []

MARKETS = {
    'over_15': 'Over 1.5 Goals',
    'under_35': 'Under 3.5 Goals',
    'gg': 'Goal-Goal (BTTS Yes)',
    'home_win': 'Home Win',
    'draw': 'Draw',
    'away_win': 'Away Win',
    'over_25': 'Over 2.5 Goals',
    'under_25': 'Under 2.5 Goals',
}

def load_models():
    """Load all per-market XGBoost, LightGBM, and Isotonic models."""
    global _models_loaded, _xgb_models, _lgb_models, _iso_models, _feature_names
    if _models_loaded:
        return
    try:
        features_path = MODELS_DIR / "model_features.json"
        if not features_path.exists():
            logger.warning("model_features.json not found. ML models unavailable.")
            return
            
        with open(features_path) as f:
            features_info = json.load(f)
            _feature_names = features_info.get("features", [])
            
        for key in MARKETS.keys():
            xgb_path = MODELS_DIR / f"xgb_{key}.json"
            lgb_path = MODELS_DIR / f"lgb_{key}.txt"
            iso_path = MODELS_DIR / f"iso_{key}.pkl"
            
            if xgb_path.exists() and lgb_path.exists() and iso_path.exists():
                # Load XGBoost
                xgb_model = xgb.XGBClassifier()
                xgb_model.load_model(str(xgb_path))
                _xgb_models[key] = xgb_model
                
                # Load LightGBM
                lgb_model = lgb.Booster(model_file=str(lgb_path))
                _lgb_models[key] = lgb_model
                
                # Load Isotonic
                with open(iso_path, "rb") as f:
                    _iso_models[key] = pickle.load(f)
                    
        _models_loaded = True
        logger.info(f"Successfully loaded ML models for {list(_xgb_models.keys())}")
    except Exception as e:
        logger.error(f"Failed to load ML models: {e}", exc_info=True)

def score_fixture_ml(
    home: str,
    away: str,
    matchday_id: int,
    matchday_number: int,
    season_name: str,
    event_id: Optional[str] = None,
    odds_map: Dict = None,
) -> Dict[str, Tuple[float, float]]:
    """
    Predict probability and calibrated confidence for all markets using ML models.
    Returns: Dict of market_key -> (calibrated_prob, EV)
    """
    load_models()
    if not _models_loaded or not _xgb_models:
        return {}
        
    try:
        # Build features for this live fixture
        feat = build_live_fixture_features(
            home=home,
            away=away,
            matchday_id=matchday_id,
            matchday_number=matchday_number,
            season_name=season_name,
            event_id=event_id,
        )
        
        # Override odds from local API odds_map if available and richer
        if odds_map:
            # Map standard keys
            for k, val in odds_map.items():
                feat_key = f"odds_{k}"
                if feat_key in feat:
                    feat[feat_key] = val
                impl_key = f"impl_{k}"
                if impl_key in feat:
                    feat[impl_key] = round(1.0 / max(val, 1.01), 3)
                    
        # Construct single-row DataFrame
        df_row = pd.DataFrame([feat])
        X = df_row[_feature_names].fillna(0).values
        
        predictions = {}
        for key, display_name in MARKETS.items():
            if key not in _xgb_models or key not in _lgb_models or key not in _iso_models:
                continue
                
            xgb_p = float(_xgb_models[key].predict_proba(X)[0, 1])
            lgb_p = float(_lgb_models[key].predict(X)[0])
            ensemble_p = (xgb_p + lgb_p) / 2
            
            # Calibrate
            cal_p = float(_iso_models[key].transform([ensemble_p])[0])
            
            # Calculate EV
            # Map key to odds in odds_map or features
            odds = 0.0
            if odds_map:
                if key == 'over_15': odds = odds_map.get('over_1.5', 0)
                elif key == 'under_35': odds = odds_map.get('under_3.5', 0)
                elif key == 'gg': odds = odds_map.get('gg', 0)
                elif key == 'home_win': odds = odds_map.get('home_win', 0)
                elif key == 'draw': odds = odds_map.get('draw', 0)
                elif key == 'away_win': odds = odds_map.get('away_win', 0)
                elif key == 'over_25': odds = odds_map.get('over_2.5', 0)
                elif key == 'under_25': odds = odds_map.get('under_2.5', 0)
                
            if odds <= 0:
                odds = feat.get(f"odds_{key}", 1.0)
                
            ev = cal_p * odds - 1.0
            predictions[display_name] = (cal_p, ev)
            
        return predictions
    except Exception as e:
        logger.error(f"ML Scoring failed for {home} vs {away}: {e}")
        return {}

# ─── Prediction Context & Postgres Logging ────────────────────────────────────

def log_to_postgres(matchday_data: dict):
    """Log prediction results to Postgres vfl_predictions table."""
    try:
        season = matchday_data.get("season", "VFLM")
        md_num = matchday_data.get("matchday", 0)
        
        with get_db() as cur:
            for fixture in matchday_data.get("fixtures", []):
                home = fixture.get("home")
                away = fixture.get("away")
                
                for p in fixture.get("predictions", []):
                    # Only insert high-quality data
                    if p["confidence"] < 30: 
                        continue
                    
                    cur.execute(
                        """
                        INSERT INTO vfl_predictions 
                        (timestamp, iso_time, season, match_day, home_team, away_team, prediction, confidence, odds, engine, tier_home, tier_away, metadata, predicted_score, pick_1x2)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            time.time(), datetime.now().isoformat(), season, md_num, 
                            home, away, p["market"], p["confidence"], p["odds"], "ensemble-ml-v1",
                            fixture.get("home_tier"), fixture.get("away_tier"),
                            json.dumps({"strength": p["strength"], "ev": p["expected_value"]}),
                            fixture.get("predicted_score"), fixture.get("pick_1x2")
                        )
                    )
        logger.info(f"Logged MD {md_num} predictions to Postgres")
    except Exception as e:
        logger.error(f"Failed to log to Postgres: {e}", exc_info=True)


async def predict_fixtures() -> int:
    """Run prediction on all upcoming fixtures."""
    logger.info("Running prediction engine using ML models...")
    raw_data = await asyncio.get_event_loop().run_in_executor(None, get_event_list)
    if not raw_data:
        logger.warning("No fixtures from API")
        return 0

    matchday_map = {}
    
    # Pre-load all model files
    load_models()
    
    for md_group in raw_data:
        md_num = md_group.get("matchDay") or md_group.get("round", 0)
        season = md_group.get("seasonName", "VFLM")
        fixtures_raw = md_group.get("events") or md_group.get("fixtures") or []
        
        if not fixtures_raw:
            continue
        if md_num not in matchday_map:
            matchday_map[md_num] = {"season": season, "matchday": md_num, "fixtures": []}
            
        # Get matchday_id from DB
        matchday_id = 0
        try:
            with get_db() as cur:
                cur.execute("""
                    SELECT m.id FROM vfl_matchdays m
                    JOIN vfl_seasons s ON m.season_id = s.id
                    WHERE s.season_name = %s AND m.matchday_number = %s
                    ORDER BY m.id DESC LIMIT 1
                """, (season, md_num))
                row = cur.fetchone()
                if row:
                    matchday_id = row[0]
        except Exception:
            pass
            
        for f in fixtures_raw:
            home = (f.get("homeTeam") or "").strip()
            away = (f.get("awayTeam") or "").strip()
            eid = f.get("eventId") or ""
            
            # Parse markets / odds
            odds_map = {}
            for mkt in f.get("markets") or []:
                mkt_name = mkt.get("name", "")
                for out in mkt.get("outcomes") or []:
                    desc = out.get("description", "")
                    od_str = out.get("odds", "0")
                    try:
                        od = float(od_str)
                    except (ValueError, TypeError):
                        od = 0
                    
                    if mkt_name in ("1x2", "Match Result"):
                        if desc == "Home": odds_map["home_win"] = od
                        elif desc == "Draw": odds_map["draw"] = od
                        elif desc == "Away": odds_map["away_win"] = od
                    elif "Over/Under" in mkt_name or "Over Under" in mkt_name:
                        if "Over" in desc and "1.5" in desc: odds_map["over_1.5"] = od
                        elif "Under" in desc and "1.5" in desc: odds_map["under_1.5"] = od
                        elif "Over" in desc and "2.5" in desc: odds_map["over_2.5"] = od
                        elif "Under" in desc and "2.5" in desc: odds_map["under_2.5"] = od
                        elif "Over" in desc and "3.5" in desc: odds_map["over_3.5"] = od
                        elif "Under" in desc and "3.5" in desc: odds_map["under_3.5"] = od
                    elif "Both" in mkt_name or "GG" in mkt_name or "NG" in mkt_name:
                        if "Yes" in desc or "GG" in desc: odds_map["gg"] = od
                        elif "No" in desc or "NG" in desc: odds_map["ng"] = od

            # Score using ML models
            ml_predictions = score_fixture_ml(
                home=home,
                away=away,
                matchday_id=matchday_id,
                matchday_number=md_num,
                season_name=season,
                event_id=eid,
                odds_map=odds_map,
            )
            
            # Formulate the predictions list
            predictions_list = []
            for market_display, (prob, ev) in ml_predictions.items():
                conf = round(prob * 100)
                # Map market name to odds in odds_map
                odds = 1.0
                if "Over 1.5" in market_display: odds = odds_map.get("over_1.5", 1.0)
                elif "Under 3.5" in market_display: odds = odds_map.get("under_3.5", 1.0)
                elif "Goal-Goal" in market_display: odds = odds_map.get("gg", 1.0)
                elif "Home Win" in market_display: odds = odds_map.get("home_win", 1.0)
                elif "Draw" in market_display: odds = odds_map.get("draw", 1.0)
                elif "Away Win" in market_display: odds = odds_map.get("away_win", 1.0)
                elif "Over 2.5" in market_display: odds = odds_map.get("over_2.5", 1.0)
                elif "Under 2.5" in market_display: odds = odds_map.get("under_2.5", 1.0)
                
                strength = "STRONG" if conf >= 80 else "MODERATE" if conf >= 65 else "WEAK"
                predictions_list.append({
                    "market": market_display,
                    "odds": odds,
                    "confidence": conf,
                    "expected_value": round(ev, 4),
                    "strength": strength,
                })
                
            # Predicted scoreline using Home Win, Draw, Away Win probabilities
            h_win_p = ml_predictions.get("Home Win", (0.45, 0))[0]
            draw_p = ml_predictions.get("Draw", (0.24, 0))[0]
            a_win_p = ml_predictions.get("Away Win", (0.31, 0))[0]
            
            pick_1x2 = "1" if h_win_p > a_win_p and h_win_p > draw_p else "2" if a_win_p > h_win_p and a_win_p > draw_p else "X"
            
            # Simple projected goals logic based on Over 2.5 and GG
            gg_p = ml_predictions.get("Goal-Goal (BTTS Yes)", (0.49, 0))[0]
            o25_p = ml_predictions.get("Over 2.5 Goals", (0.48, 0))[0]
            
            if o25_p >= 0.6:
                if pick_1x2 == "1": pred_h, pred_a = 2, 1 if gg_p >= 0.5 else 0
                elif pick_1x2 == "2": pred_h, pred_a = 1 if gg_p >= 0.5 else 0, 2
                else: pred_h, pred_a = 2, 2
            else:
                if pick_1x2 == "1": pred_h, pred_a = 1, 0
                elif pick_1x2 == "2": pred_h, pred_a = 0, 1
                else: pred_h, pred_a = 1, 1
                
            fixture = {
                "event_id": eid,
                "home": home,
                "away": away,
                "home_tier": "mid", # simplified tier
                "away_tier": "mid",
                "predicted_score": f"{pred_h}-{pred_a}",
                "pick_1x2": pick_1x2,
                "intel_summary": "ML Ensemble Scored",
                "sequence_summary": "Rich features leveraged",
                "odds": odds_map,
                "predictions": sorted(predictions_list, key=lambda x: x["expected_value"], reverse=True),
                "season_id": season,
            }
            matchday_map[md_num]["fixtures"].append(fixture)

    # Build output
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline": "rich-ml-ensemble-v1",
        "matchdays": sorted(matchday_map.values(), key=lambda x: x["matchday"]),
    }

    # Summary
    total = sum(len(md["fixtures"]) for md in output["matchdays"])
    strong = sum(1 for md in output["matchdays"] for f in md["fixtures"] for p in f["predictions"] if p["strength"] == "STRONG")
    moderate = sum(1 for md in output["matchdays"] for f in md["fixtures"] for p in f["predictions"] if p["strength"] == "MODERATE")
    output["summary"] = {
        "total_matchdays": len(output["matchdays"]),
        "total_fixtures": total,
        "strong_predictions": strong,
        "moderate_predictions": moderate,
    }

    # Save to memory cache
    global _latest_predictions
    _latest_predictions = output

    # Write to predictions_latest.json
    service_path = os.path.join(SIGNALS_DIR, "predictions_latest.json")
    with open(service_path, "w") as f:
        json.dump(output, f, indent=2)

    # Log to Postgres
    for md in output.get("matchdays", []):
        log_to_postgres(md)

    logger.info(f"Saved ML predictions: {total} fixtures, {strong} STRONG, {moderate} MODERATE")
    return len(output["matchdays"])


# ── FastAPI App ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Rich ML Prediction Engine starting on :8002")
    load_models()
    yield
    logger.info("Rich ML Prediction Engine shutting down")

app = FastAPI(title="VFL Prediction Engine", version="2.0.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {
        "service": "predictor",
        "status": "ok",
        "models_loaded": _models_loaded,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/predict")
async def predict():
    fixtures_predicted = await predict_fixtures()
    return {"status": "success", "message": f"Prediction run complete. Predicted {fixtures_predicted} fixtures."}

@app.get("/predictions/latest")
async def get_latest_predictions():
    if _latest_predictions.get("matchdays"):
        return _latest_predictions
    path = os.path.join(SIGNALS_DIR, "predictions_latest.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"status": "no_predictions_yet"}

def main():
    uvicorn.run(app, host="0.0.0.0", port=8002, log_level="info")

if __name__ == "__main__":
    main()
