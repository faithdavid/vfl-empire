#!/usr/bin/env python3
"""VFL Empire Orchestrator — Synced to MSport Live Clock."""
import time, requests, logging, sys, os, subprocess
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
try:
    from hermes_notifier import notify
except ImportError:
    def notify(msg): print(f"NOTIFY: {msg}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ORCHESTRATOR")

SERVICES = {
    "ingester": "http://localhost:8001",
    "predictor": "http://localhost:8002",
    "betting": "http://localhost:8003",
    "settlement": "http://localhost:8004",
}

# State to prevent double processing
last_processed_md = -1
last_settled_md = -1

def get_msport_state():
    """Fetch current matchday info from Ingester (which proxies MSport)."""
    try:
        # Trigger ingestion to keep status fresh and avoid deadlocks
        try:
            requests.post(f"{SERVICES['ingester']}/ingest/season", timeout=3)
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Failed to trigger ingestion in get_msport_state: {e}")
            
        resp = requests.get(f"{SERVICES['ingester']}/ingest/status", timeout=5)
        data = resp.json()
        return data
    except Exception as e:
        logger.error(f"Failed to get MSport state: {e}")
        return None

def run_recalibration():
    """Refreshes team form and market clusters from latest live data."""
    try:
        logger.info("Running Live Recalibration (Form + Clusters)...")
        # 1. Refresh Rapid Form
        subprocess.run(["python3", "/home/ubuntu/faith-workspace/vfl-empire/scripts/vfl_rapid_form_refresh.py", "--once"], check=True)
        # 2. Recalibrate Clusters
        subprocess.run(["python3", "/home/ubuntu/faith-workspace/vfl-empire/scripts/recalibrate_odds_clusters.py"], check=True)
        logger.info("Recalibration complete.")
    except Exception as e:
        logger.error(f"Recalibration failed: {e}")

def run_prediction_and_bet_cycle(md_num):
    """Execute the core prediction and betting logic for the upcoming matchday."""
    global last_processed_md
    if last_processed_md == md_num:
        return
    
    logger.info(f"--- STARTING PREDICTION/BET CYCLE FOR MD {md_num} ---")
    
    try:
        # 0. Recalibrate (Ensure form and clusters are fresh)
        run_recalibration()

        # 1. Ingest (Upcoming Fixtures + Odds)
        requests.post(f"{SERVICES['ingester']}/ingest/season", timeout=10)
        time.sleep(5)
        
        # 2. Predict
        requests.post(f"{SERVICES['predictor']}/predict", timeout=10)
        time.sleep(5)
        
        # 3. Bet
        requests.post(f"{SERVICES['betting']}/evaluate", timeout=120)
        place_resp = requests.post(f"{SERVICES['betting']}/place", timeout=180)
        place_data = place_resp.json()
        logger.info(f"Placement Result: {place_data.get('status')}")
        
        # 4. Notify Discord Forecast (C-states layout)
        try:
            subprocess.run(["python3", "/home/ubuntu/faith-workspace/vfl-empire/scripts/vfl_discord_predictions.py"], check=True)
            logger.info("Discord C-States Forecast sent successfully.")
        except Exception as e:
            logger.error(f"Discord C-States Forecast failed: {e}")
        
        last_processed_md = md_num
    except Exception as e:
        logger.error(f"Prediction/Bet cycle failed: {e}")

def run_settlement_cycle(md_num):
    """Execute settlement for the completed matchday."""
    global last_settled_md
    if last_settled_md == md_num:
        return
    
    logger.info(f"--- STARTING SETTLEMENT CYCLE FOR MD {md_num} ---")
    
    try:
        # Trigger Ingester to get results
        requests.post(f"{SERVICES['ingester']}/ingest/season", timeout=10)
        time.sleep(10)
        
        # Settle
        resp = requests.post(f"{SERVICES['settlement']}/settle", timeout=120)
        data = resp.json()
        settled_count = data.get('settled', 0)
        profit = data.get('total_profit', 0)
        
        if settled_count > 0:
            notify(f"💰 **MD {md_num} Settled**: {settled_count} bets closed. Profit: ₦{profit:.2f}")
        
        last_settled_md = md_num
    except Exception as e:
        logger.error(f"Settlement failed: {e}")

def main():
    logger.info("VFL Empire Orchestrator [LIVE SYNC MODE] started.")
    notify("🚀 **VFL Orchestrator Online**: Synced to MSport Live Clock.")
    
    while True:
        state = get_msport_state()
        if not state:
            time.sleep(10)
            continue
            
        current_md = state.get("current_matchday", 0)
        # MSport status logic
        # We want to place bets for the NEXT matchday when the CURRENT one is playing or just finished.
        # But get_match_day_info usually returns the 'active' matchday.
        
        # Let's use a simpler approach: 
        # If current_md is N, we ensure N is settled, and we prepare for N+1.
        
        # 1. Check if we need to settle current_md
        # (Wait at least 3 mins into the matchday to settle)
        run_settlement_cycle(current_md)
        
        # 2. Check if we need to predict/bet for current_md + 1
        # Actually, the API returns the matchday that is 'upcoming' or 'current'.
        # If status is 'MATCH', current_md is playing.
        # If status is 'NOT_STARTED', current_md is about to start.
        
        # Let's just follow the matchday sequence.
        # We always want to have predictions for the NEXT matchday.
        run_prediction_and_bet_cycle(current_md + 1)
        
        time.sleep(30) # Poll every 30 seconds

if __name__ == "__main__":
    main()
