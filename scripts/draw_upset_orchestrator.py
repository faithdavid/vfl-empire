#!/usr/bin/env python3
"""
draw_upset_orchestrator.py — Specialized High-Odds Engine.
Targets Draw Magnets and Underdog Spikes using chronological data.
"""

import json, sys, os, subprocess, time, logging
from pathlib import Path
from datetime import datetime, timezone

# Add paths
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
SERVICES_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/services")
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SERVICES_DIR))

try:
    from common.db_manager import get_db
    from msport_api import get_standings, get_current_match_day_info
except ImportError:
    print("❌ Critical Imports failed.")
    sys.exit(1)

# Config
BASE_STAKE = 10.0 # Small stake for high-odds outcomes
MAX_STAKE = 25.0
SERVICE_FEE = 0.10
DATA_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data/signals")
STATE_FILE = DATA_DIR / "draw_upset_state.json"
PREDICTIONS_FILE = DATA_DIR / "predictions_latest.json"
BET_PLACER = SCRIPTS_DIR / "browser_bet_placer.py"

# Identified Draw Magnets (Fixture-specific, 39-season verified)
DRAW_MAGNETS = [
    ("Everton", "Brighton"), ("Fulham", "Leeds"), ("Crystal Palace", "Liverpool"),
    ("Newcastle", "Liverpool"), ("Manchester Red", "Aston Villa"), ("West Ham", "Everton"),
    ("Brighton", "Tottenham"), ("Manchester Blue", "Chelsea"), ("Leeds", "Newcastle")
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DRAW_ORCHESTRATOR")

class DrawUpsetManager:
    def __init__(self):
        self.state = self._load_state()

    def _load_state(self):
        if STATE_FILE.exists():
            with open(STATE_FILE) as f: return json.load(f)
        return {"history": [], "active_bets": [], "total_profit": 0.0}

    def _save_state(self):
        with open(STATE_FILE, "w") as f: json.dump(self.state, f, indent=2)

    def get_upcoming_traps(self, predictions):
        """Find matches that fit the Elite Trap or Underdog Spike pattern."""
        traps = []
        
        # Get current standings
        standings = get_standings()
        
        # Robust Fallback: If current standings are empty, use the latest completed season
        if not standings or not standings.get("standings"):
            logger.info("   ⚠️ Current season standings empty. Fetching latest completed season as fallback...")
            try:
                from msport_api import get_season_list
                seasons = get_season_list()
                if seasons:
                    # Filter for seasons that have matchday data and sort by time
                    valid = [s for s in seasons if s.get("matchDay")]
                    valid.sort(key=lambda s: s.get("startTime", 0), reverse=True)
                    if valid:
                        fallback_sid = valid[0]["seasonId"]
                        fallback_md = max(valid[0]["matchDay"])
                        logger.info(f"   📋 Fallback to {valid[0].get('seasonName')} MD {fallback_md}")
                        standings = get_standings(season_id=fallback_sid, match_day=fallback_md)
            except Exception as e:
                logger.error(f"   ❌ Fallback failed: {e}")

        if not standings or not standings.get("standings"):
            logger.warning("   ❌ Could not resolve any standings for rank analysis.")
            return []
        
        # Build rank map
        ranks = {t["teamName"]: t["rank"] for t in standings.get("standings", [])}
        
        for md in predictions:
            md_num = md.get("matchday")
            for f in md.get("fixtures", []):
                h, a = f["home"], f["away"]
                hr, ar = ranks.get(h, 10), ranks.get(a, 10)
                
                # Pattern 1: Draw Magnet Fixture
                if (h, a) in DRAW_MAGNETS or (a, h) in DRAW_MAGNETS:
                    traps.append({"home": h, "away": a, "md": md_num, "type": "MAGNET", "market": "Draw", "odds": 3.2})
                
                # Pattern 2: High-Draw Trap (Rank 1-4 vs Rank 8-12)
                elif (hr <= 4 and 8 <= ar <= 12) or (ar <= 4 and 8 <= hr <= 12):
                    traps.append({"home": h, "away": a, "md": md_num, "type": "TRAP", "market": "Draw", "odds": 3.1})

                # Pattern 3: Underdog Spike (Rank 13-16 vs Rank 1-4)
                elif (hr >= 13 and ar <= 4) or (ar >= 13 and hr <= 4):
                    underdog = h if hr >= 13 else a
                    market = "Home" if underdog == h else "Away"
                    traps.append({"home": h, "away": a, "md": md_num, "type": "SPIKE", "market": market, "odds": 4.5})
                    
        return traps

    def place_value_bet(self, trap):
        """Place a small value bet on the identified trap."""
        input_data = {
            "home": trap["home"], "away": trap["away"],
            "market": trap["market"], "stake": BASE_STAKE, "matchday": trap["md"]
        }
        cmd = [sys.executable, str(BET_PLACER), "bet", json.dumps(input_data)]
        logger.info(f"🎯 Placing {trap['type']} Bet: {trap['home']} vs {trap['away']} ({trap['market']}) @{trap['odds']}")
        
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            logger.info(f"   [BET_PLACER_STDOUT]: {res.stdout.strip()}")
            if res.stderr:
                logger.error(f"   [BET_PLACER_STDERR]: {res.stderr.strip()}")
                
            if "successfully" in res.stdout.lower():
                self.state["active_bets"].append({
                    "home": trap["home"], "away": trap["away"], "md": trap["md"], 
                    "market": trap["market"], "stake": BASE_STAKE, "type": trap["type"],
                    "placed_at": datetime.now(timezone.utc).isoformat()
                })
                self._save_state()
                return True
        except Exception as e:
            logger.error(f"Bet placement failed: {e}")
        return False

    def settle_bets(self):
        """Check results and settle active value bets."""
        if not self.state["active_bets"]: return

        with get_db() as cur:
            remaining = []
            for bet in self.state["active_bets"]:
                cur.execute("""
                    SELECT home_goals, away_goals FROM vfl_results_v2 
                    WHERE home_team = %s AND away_team = %s AND matchday_id IN 
                    (SELECT id FROM vfl_matchdays WHERE matchday_number = %s)
                    ORDER BY id DESC LIMIT 1
                """, (bet["home"], bet["away"], bet["md"]))
                row = cur.fetchone()
                
                if row:
                    hg, ag = row[0], row[1]
                    won = False
                    if bet["market"] == "Draw" and hg == ag: won = True
                    elif bet["market"] == "Home" and hg > ag: won = True
                    elif bet["market"] == "Away" and ag > hg: won = True
                    
                    if won:
                        # Estimate odds if not stored (default 3.0 for draws, 4.0 for underdogs)
                        est_odds = 3.2 if bet["market"] == "Draw" else 4.5
                        profit = round((bet["stake"] * est_odds) - bet["stake"], 2)
                        fee = round(profit * SERVICE_FEE, 2)
                        net_profit = profit - fee
                        self.state["total_profit"] += net_profit
                        logger.info(f"💰 VALUE WIN! {bet['home']} vs {bet['away']} ({bet['market']}) Net: +₦{net_profit}")
                    else:
                        self.state["total_profit"] -= bet["stake"]
                        logger.info(f"💀 Loss: {bet['home']} vs {bet['away']} ({bet['market']})")
                    
                    bet["won"] = won
                    self.state["history"].append(bet)
                else:
                    remaining.append(bet)
            
            self.state["active_bets"] = remaining
            self._save_state()

def main():
    manager = DrawUpsetManager()
    logger.info("Starting Draw & Underdog Orchestrator...")
    
    while True:
        try:
            # 1. Settle
            manager.settle_bets()
            
            # 2. Find new traps
            if PREDICTIONS_FILE.exists():
                with open(PREDICTIONS_FILE) as f:
                    preds = json.load(f)
                    # Support both list and dict formats
                    matchdays = preds if isinstance(preds, list) else preds.get("matchdays", [])
                
                traps = manager.get_upcoming_traps(matchdays)
                active_keys = [f"{b['home']}|{b['away']}|{b['md']}" for b in manager.state["active_bets"]]
                
                # Check current MD info
                info = get_current_match_day_info()
                if info:
                    curr_md = info.get("matchDay", 0)
                    for t in traps:
                        key = f"{t['home']}|{t['away']}|{t['md']}"
                        if key not in active_keys and t["md"] > curr_md:
                            manager.place_value_bet(t)
                            break # One value bet per MD to keep exposure low
                            
        except Exception as e:
            logger.error(f"Loop error: {e}")
            
        time.sleep(120)

if __name__ == "__main__":
    main()
