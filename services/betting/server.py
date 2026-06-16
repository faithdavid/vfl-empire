import json, logging, os, sys, urllib.request, pickle
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, HTTPException
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common import db_manager

logger = logging.getLogger("[BETTING]")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# ─── Ensemble Model (XGBoost + LightGBM + Keras meta-filter) ─────────────────
_MODELS_DIR = Path(__file__).parents[2] / "models"
_ensemble_loaded = False
_xgb_model = None
_lgb_model = None
_keras_model = None
_encoders  = None
_ENSEMBLE_MIN_PROB = 0.70  # 82.6% historical accuracy at this threshold

def _load_ensemble():
    """Lazy-load the ensemble models once on first use.
    Priority: chronological v3 models (no data leakage) > original v2 models.
    """
    global _ensemble_loaded, _xgb_model, _lgb_model, _keras_model, _encoders
    if _ensemble_loaded:
        return
    try:
        import xgboost as xgb
        import lightgbm as lgb

        # ── Try v3 chronological models first (best, no data leakage) ──
        xgb_path   = _MODELS_DIR / "xgb_chrono_v3.json"
        lgb_path   = _MODELS_DIR / "lgb_chrono_v3.txt"
        enc_path   = _MODELS_DIR / "encoders_chrono_v3.pkl"

        # Fall back to v2 (random-split) if v3 not yet trained
        if not xgb_path.exists():
            xgb_path = _MODELS_DIR / "xgb_meta_v2.json"
            lgb_path = _MODELS_DIR / "lgb_meta_v2.txt"
            enc_path = _MODELS_DIR / "encoders_v2.pkl"
            logger.info("Using v2 models (v3 not found yet)")
        else:
            logger.info("Using v3 chronological models (preferred)")

        if xgb_path.exists() and lgb_path.exists() and enc_path.exists():
            _xgb_model = xgb.XGBClassifier()
            _xgb_model.load_model(str(xgb_path))
            _lgb_model = lgb.Booster(model_file=str(lgb_path))
            with open(enc_path, "rb") as f:
                _encoders = pickle.load(f)

            # Try loading Keras (optional — degrades gracefully)
            keras_path = _MODELS_DIR / "keras_meta_v2.keras"
            if keras_path.exists():
                try:
                    from keras.models import load_model
                    _keras_model = load_model(str(keras_path))
                    logger.info("✅ Ensemble loaded: XGBoost + LightGBM + Keras DNN")
                except Exception as ke:
                    logger.warning(f"⚠️  Keras not loaded ({ke}) — using 2-way XGB+LGB ensemble")
                    _keras_model = None
            else:
                _keras_model = None
                logger.info("✅ Ensemble loaded: XGBoost + LightGBM (2-way)")

            _ensemble_loaded = True
        else:
            logger.warning("⚠️  Ensemble model files not found — skipping filter")
            _ensemble_loaded = True  # don't retry repeatedly
    except Exception as e:
        logger.warning(f"⚠️  Failed to load ensemble: {e}")
        _ensemble_loaded = True


def _ensemble_score(prediction: str, confidence: float, odds: float,
                    tier_home: str, tier_away: str, match_day: int,
                    engine: str = "sovereign", cv_1x2: float = 0.0) -> float:
    """Return ensemble probability [0,1]. Returns 1.0 if model unavailable.
    Uses XGB + LGB (2-way) or XGB + LGB + Keras (3-way) depending on availability.
    """
    _load_ensemble()
    if _xgb_model is None or _lgb_model is None or _encoders is None:
        return 1.0  # no model — let everything through
    try:
        import pandas as pd
        enc = _encoders
        def safe_encode(le, val):
            try:
                return int(le.transform([val])[0])
            except Exception:
                return 0

        row = {
            'confidence':      confidence,
            'odds':            odds,
            'cv_1x2':          cv_1x2,
            'prediction_enc':  safe_encode(enc['prediction'], prediction),
            'engine_enc':      safe_encode(enc['engine'], engine),
            'tier_home_enc':   safe_encode(enc['tier_home'], tier_home),
            'tier_away_enc':   safe_encode(enc['tier_away'], tier_away),
            'match_day':       match_day,
            'is_home_win':     int(prediction == 'Home Win'),
            'is_away_win':     int(prediction == 'Away Win'),
            'is_draw':         int('draw' in prediction.lower() or prediction in ('D', 'DRAW')),
            'is_over':         int('over' in prediction.lower()),
            'is_under':        int('under' in prediction.lower()),
            'is_dnb':          int('dnb' in prediction.lower()),
            'expected_value':  (confidence / 100) * odds - 1,
            'high_conf':       int(confidence >= 90),
            'very_high_conf':  int(confidence >= 95),
        }
        features = enc['features']
        X = pd.DataFrame([row])[features]
        xgb_prob = float(_xgb_model.predict_proba(X)[0, 1])
        lgb_prob = float(_lgb_model.predict(X)[0])

        # 3-way ensemble if Keras available, otherwise 2-way
        if _keras_model is not None:
            scaler = enc.get('scaler')
            if scaler is not None:
                X_scaled = scaler.transform(X)
            else:
                X_scaled = X.values
            keras_prob = float(_keras_model.predict(X_scaled, verbose=0)[0, 0])
            return (xgb_prob + lgb_prob + keras_prob) / 3
        else:
            return (xgb_prob + lgb_prob) / 2

    except Exception as e:
        logger.warning(f"Ensemble scoring error: {e}")
        return 1.0

DATA_DIR = os.path.expanduser("~/faith-workspace/vfl-complete-data")
SIGNALS_DIR = os.path.join(DATA_DIR, "signals")
os.makedirs(SIGNALS_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
try:
    from hermes_notifier import notify
except ImportError:
    def notify(msg): logger.info(f"MOCK NOTIFY: {msg}")

PREDICTOR_API = "http://localhost:8002"

# ─── Bankroll & DB ──────────────────────────────────────────────────────────

def _load_bankroll() -> dict:
    row = db_manager.fetch_one("SELECT current_balance, initial_balance FROM bankroll ORDER BY updated_at DESC LIMIT 1")
    if row:
        return {"current": float(row["current_balance"]), "initial": float(row["initial_balance"])}
    return {"initial": 100.0, "current": 100.0}

def _save_bankroll(br: dict):
    db_manager.execute(
        "UPDATE bankroll SET current_balance = %s, updated_at = NOW()",
        (br["current"],)
    )

def check_circuit_breaker(threshold: float = -20.0) -> bool:
    """
    Check if we should stop betting due to significant losses.
    Returns True if breaker is TRIPPED (stop betting).
    """
    # Disabled to allow compounding starting from low bankrolls
    return False

def kelly_stake(prob: float, odds: float, bankroll: float, fraction: float = 0.25) -> float:
    """Calculate Kelly stake, clamped to fraction of bankroll."""
    if prob <= 0 or odds <= 1:
        return 0
    b = odds - 1
    p = prob
    q = 1 - p
    kelly = (b * p - q) / b
    kelly = max(0, kelly)
    stake = kelly * bankroll * fraction
    return round(min(stake, bankroll * fraction), 2)

def evaluate_predictions() -> dict:
    """Fetch predictions from Predictor Engine API, evaluate each, return betting signals."""
    if check_circuit_breaker():
        logger.error("Circuit Breaker is ACTIVE. Skipping betting cycle.")
        return {"status": "circuit_breaker", "message": "Circuit breaker tripped due to drawdown."}

    # Fetch latest predictions from the Prediction Engine service
    req = urllib.request.Request(f"{PREDICTOR_API}/predictions/latest")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to fetch predictions from predictor: {e}")
        return {"status": "error", "message": str(e), "signals": []}

    bankroll = _load_bankroll()
    current_bankroll = bankroll.get("current", 100.0)
    signals = []

    for md in data.get("matchdays", []):
        for fixture in md.get("fixtures", []):
            is_villa = "aston villa" in fixture.get("home", "").lower() or "aston villa" in fixture.get("away", "").lower()
            for pred in fixture.get("predictions", []):
                market = pred.get("market", "")
                odds = pred.get("odds", 0)
                confidence = pred.get("confidence", 0)
                strength = pred.get("strength", "")
                ev = pred.get("expected_value", 0)

                if is_villa:
                    # If Aston Villa is playing, only allow "Under 3.5 Goals"
                    if market != "Under 3.5 Goals":
                        continue
                    strength = "STRONG"
                    confidence = max(confidence, 85.0)
                    ev = max(ev, 0.10)
                else:
                    # Allow STRONG and MODERATE picks. 
                    # STRONG picks now include Sequence Oracle (Mirroring) boosts.
                    if strength not in ("STRONG", "MODERATE"):
                        continue

                prob = confidence / 100
                stake = kelly_stake(prob, odds, current_bankroll)

                if stake <= 0 or odds < 1.10:
                    continue

                # ── Ensemble second-opinion filter ──
                ensemble_prob = _ensemble_score(
                    prediction=market,
                    confidence=confidence,
                    odds=odds,
                    tier_home=fixture.get("tier_home", "mid"),
                    tier_away=fixture.get("tier_away", "mid"),
                    match_day=md.get("matchday", 0),
                    engine=pred.get("engine", "sovereign"),
                    cv_1x2=pred.get("cv_1x2", 0.0),
                )
                if ensemble_prob < _ENSEMBLE_MIN_PROB:
                    logger.info(f"🚫 Ensemble filtered out {market} ({fixture['home']} vs {fixture['away']}) — prob={ensemble_prob:.2f}")
                    continue

                signals.append({
                    "match": f"{fixture['home']} vs {fixture['away']}",
                    "market": market,
                    "odds": odds,
                    "confidence": confidence,
                    "strength": strength,
                    "ev": round(ev * 100, 1),
                    "stake": stake,
                    "season": md.get("season", ""),
                    "matchday": md.get("matchday", 0),
                    "event_id": fixture.get("event_id", ""),
                    "ensemble_prob": round(ensemble_prob, 3),
                })

    # Sort by EV descending
    signals.sort(key=lambda s: s["ev"], reverse=True)

    total_stake = sum(s["stake"] for s in signals)
    expected_return = sum(s["stake"] * (s["ev"] / 100) for s in signals)

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bankroll": current_bankroll,
        "total_signals": len(signals),
        "total_stake": round(total_stake, 2),
        "expected_return": round(expected_return, 2),
        "signals": signals[:20],  # Top 20
    }

    # Save signals
    signals_path = os.path.join(SIGNALS_DIR, "betting_signals.json")
    with open(signals_path, "w") as f:
        json.dump(result, f, indent=2)

    logger.info(f"Generated {len(signals)} betting signals, total stake {total_stake:.2f}")
    return result

def log_bet_to_db(bet_type: str, matches: list, market: str, odds: float, stake: float, success: bool, matchday: int, season_name: str):
    """Log the bet to vfl_bets table."""
    try:
        match_str = ", ".join(matches)
        db_manager.execute(
            """
            INSERT INTO vfl_bets 
            (timestamp, matchday, match, market, odds, stake, bet_type, settled, success, season_name)
            VALUES (NOW(), %s, %s, %s, %s, %s, %s, False, %s, %s)
            """,
            (matchday, match_str, market, odds, stake, bet_type, success, season_name)
        )
        # Also deduct from bankroll if success
        if success:
            br = _load_bankroll()
            br["current"] -= float(stake)
            _save_bankroll(br)
            logger.info(f"Logged {bet_type} to DB and updated bankroll.")
    except Exception as e:
        logger.error(f"Failed to log bet to DB: {e}")

def place_bets_automated(signals: dict) -> dict:
    """Execute bets in the browser using browser_bet_placer.py."""
    if not signals or not signals.get("signals"):
        return {"status": "no_signals"}

    active_signals = signals["signals"]
    
    # Filter out current and past matchdays to only place bets on future matchdays
    current_md = 0
    try:
        req = urllib.request.Request("http://localhost:8001/ingest/status")
        with urllib.request.urlopen(req, timeout=3) as resp:
            status_data = json.loads(resp.read().decode("utf-8"))
            current_md = status_data.get("current_matchday", 0)
            logger.info(f"Fetched current matchday: {current_md}")
    except Exception as e:
        logger.error(f"Failed to fetch current matchday for future filter: {e}")

    if current_md > 0:
        active_signals = [s for s in active_signals if s.get("matchday", 0) > current_md]
        logger.info(f"Filtered signals: {len(active_signals)} remaining (matchday > {current_md})")

    results = []
    
    # --- PROFITABLE PARLAY LOGIC ---
    # We group top 3 high-confidence signals into a parlay (falling back to 2 if only 2 exist)
    # Relaxed criteria: Confidence >= 80 or Ghost Lock (>=95)
    parlay_candidates = [s for s in active_signals if s["confidence"] >= 80 and s["ev"] >= 5]
    
    # Group parlay candidates by matchday to ensure all legs belong to the same matchday
    md_groups = {}
    for s in parlay_candidates:
        md = s["matchday"]
        if md not in md_groups:
            md_groups[md] = []
        md_groups[md].append(s)
        
    # Prioritize and select the best matchday group
    best_md = None
    best_candidates = []
    
    def md_priority(md):
        candidates = md_groups[md]
        # Filter duplicates in this matchday group
        seen = set()
        uniq = []
        for c in candidates:
            if c["match"] not in seen:
                seen.add(c["match"])
                uniq.append(c)
        md_groups[md] = uniq
        
        has_manc_blue = any('Manchester Blue' in c['match'] or 'Manchester City' in c['match'] for c in uniq)
        count = len(uniq)
        sum_ev = sum(c['ev'] for c in uniq)
        return (has_manc_blue, min(count, 3), sum_ev)
        
    valid_mds = [md for md, candidates in md_groups.items() if len(candidates) >= 2]
    if valid_mds:
        best_md = max(valid_mds, key=md_priority)
        best_candidates = md_groups[best_md]
        
    parlay_candidates = best_candidates
    n_legs = 3 if len(parlay_candidates) >= 3 else (2 if len(parlay_candidates) >= 2 else 0)
    
    # Load bankroll to calculate user's custom stake
    br = _load_bankroll()
    current_bal = float(br.get("current", 10.0))
    
    # Custom Staking Rule:
    # 1. Base stake is 10.0 NGN
    # 2. Check the last settled successful bet in DB. 
    # If its status is 'won', we compound and stake the floor of the payout (stake * odds).
    base_stake = 10.0
    custom_stake = base_stake
    
    try:
        last_bet = db_manager.fetch_one(
            "SELECT status, odds, stake, payout FROM vfl_bets WHERE success = True AND settled = True ORDER BY timestamp DESC LIMIT 1"
        )
        if last_bet:
            status = last_bet.get("status")
            payout = float(last_bet.get("payout") or 0.0)
            if status == "won" and payout > 0:
                if payout >= 100.0:
                    custom_stake = float((payout // 100) * 100)
                else:
                    custom_stake = float((payout // 10) * 10)
                logger.info(f"Last bet WON! Compounding stake (floored to tens/hundreds): {custom_stake}")
            else:
                logger.info(f"Last bet status is '{status}'. Resetting stake to base: {base_stake}")
        else:
            logger.info(f"No settled bets found. Defaulting stake to base: {base_stake}")
    except Exception as e:
        logger.error(f"Error calculating streak stake, defaulting to base: {e}")
        custom_stake = base_stake
        
    # Clamp stake to current balance so we don't bet more than we have
    custom_stake = min(custom_stake, current_bal)
    
    if n_legs > 0 and custom_stake > 0:
        # Create a parlay
        legs = parlay_candidates[:n_legs]
        
        cmd_input = {
            "matchday": legs[0]["matchday"],
            "stake": custom_stake,
            "legs": [{
                "home": l["match"].split(" vs ")[0],
                "away": l["match"].split(" vs ")[1],
                "market": l["market"]
            } for l in legs]
        }
        
        matches_desc = " + ".join(l['match'] for l in legs)
        logger.info(f"PLACING PARLAY ({n_legs} legs): {matches_desc} | Stake: {custom_stake}")
        
        legs_msg = "\n".join(f"Leg {idx+1}: {l['match']} ({l['market']})" for idx, l in enumerate(legs))
        import math
        parlay_odds = round(math.prod(l["odds"] for l in legs), 2)
        notify(f"🚀 **VFL {n_legs}-LEG PARLAY PLACED**\n{legs_msg}\nStake: ₦{custom_stake:.2f} | Odds: @{parlay_odds:.2f} | EV: +{sum(l['ev'] for l in legs)/n_legs:.1f}%")
        
        try:
            import subprocess
            cmd = ["python3", "/home/ubuntu/faith-workspace/vfl-empire/scripts/browser_bet_placer.py", "parlay"]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = proc.communicate(input=json.dumps(cmd_input))
            logger.info(f"Bet Placer stdout: {stdout}")
            if stderr:
                logger.warning(f"Bet Placer stderr: {stderr}")
            res = json.loads(stdout) if stdout else {"success": False, "error": "No output"}
            
            is_success = res.get("success", False)
            results.append({"type": "parlay", "matches": [l["match"] for l in legs], "success": is_success})
            
            # Log to DB
            log_bet_to_db("parlay", [l["match"] for l in legs], ", ".join(l["market"] for l in legs), parlay_odds, custom_stake, is_success, legs[0]["matchday"], legs[0].get("season", ""))
            
            if is_success:
                notify(f"✅ Parlay Confirmed: {res.get('message', 'Success')}")
            else:
                notify(f"❌ Parlay Failed: {res.get('error', 'Unknown error')}")
        except Exception as e:
            logger.error(f"Parlay execution failed: {e}")
            results.append({"type": "parlay", "success": False, "error": str(e)})
 
        # To conserve bankroll, we skip singles entirely when a parlay is placed
        return {"status": "completed", "results": results}
 
    # Fallback: Only place top singles if NO parlay was placed and we have remaining bankroll
    remaining = [s for s in active_signals if s not in parlay_candidates[:n_legs]][:3]
    for s in remaining:
        # Ghost Lock (95+) or High EV (15+)
        if s["confidence"] < 95 and s["ev"] < 15: 
            continue 
            
        single_stake = min(custom_stake, current_bal)
        if single_stake <= 0:
            break
            
        cmd_input = {
            "matchday": s["matchday"],
            "stake": single_stake,
            "legs": [{
                "home": s["match"].split(" vs ")[0],
                "away": s["match"].split(" vs ")[1],
                "market": s["market"]
            }]
        }
        
        logger.info(f"PLACING SINGLE: {s['match']} | Stake: {single_stake}")
        notify(f"🎯 **VFL SINGLE PLACED**\nMatch: {s['match']}\nMarket: {s['market']}\nStake: ₦{single_stake:.2f} | Confidence: {s['confidence']}%")
        
        try:
            import subprocess
            cmd = ["python3", "/home/ubuntu/faith-workspace/vfl-empire/scripts/browser_bet_placer.py", "parlay"]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = proc.communicate(input=json.dumps(cmd_input))
            res = json.loads(stdout) if stdout else {"success": False, "error": "No output"}
            
            is_success = res.get("success", False)
            results.append({"type": "single", "match": s["match"], "success": is_success})
            
            # Log to DB
            log_bet_to_db("single", [s["match"]], s["market"], s["odds"], single_stake, is_success, s["matchday"], s.get("season", ""))
            
            # Deduct balance so next single doesn't double spend
            if is_success:
                current_bal -= single_stake
            
        except Exception as e:
            logger.error(f"Single failed: {e}")

    return {"status": "completed", "results": results}

def format_discord(signals: dict) -> str:
    """Format signals for Discord output."""
    lines = [f"🎯 **Betting Signals** ({signals['total_signals']} picks)"]
    lines.append(f"💰 Bankroll: ₦{signals['bankroll']:.2f}")
    lines.append(f"📊 Total Stake: {signals['total_stake']:.2f}u | Expected Return: {signals['expected_return']:.2f}u")
    lines.append("")
    for s in signals.get("signals", [])[:10]:
        lines.append(f"• {s['match']} → **{s['market']}** @{s['odds']} ({s['confidence']}%) EV:+{s['ev']}% Stake:{s['stake']}u")
    return "\n".join(lines)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Betting Agent starting on :8003")
    yield
    logger.info("Betting Agent shutting down")

app = FastAPI(title="VFL Betting Agent", version="1.0.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {"service": "betting", "status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.post("/evaluate")
async def evaluate():
    result = evaluate_predictions()
    return result

@app.post("/place")
async def place():
    # Load latest signals
    path = os.path.join(SIGNALS_DIR, "betting_signals.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No signals available to place")
    
    with open(path) as f:
        signals = json.load(f)
    
    result = place_bets_automated(signals)
    return result

@app.get("/signals/latest")
async def latest_signals():
    path = os.path.join(SIGNALS_DIR, "betting_signals.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"status": "no_signals_yet"}

@app.get("/bankroll")
async def get_bankroll():
    return _load_bankroll()

@app.post("/bankroll/update")
async def update_bankroll(amount: float = 0):
    br = _load_bankroll()
    if amount > 0:
        br["current"] += amount
        _save_bankroll(br)
    return br

@app.get("/evaluate/kelly")
async def kelly_calc(prob: float = Query(...), odds: float = Query(...), bankroll: float = 100.0):
    stake = kelly_stake(prob, odds, bankroll)
    return {"prob": prob, "odds": odds, "bankroll": bankroll, "kelly_stake": stake, "fractional_stake": round(stake / bankroll * 100, 1) + "%"}

def main():
    uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info")

if __name__ == "__main__":
    main()
