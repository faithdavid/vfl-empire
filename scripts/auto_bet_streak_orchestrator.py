#!/usr/bin/env python3
"""
auto_bet_streak_orchestrator.py — Empire's Streak Betting Engine.
Implements Lord FaithDavid's "50 naira over 7 streak" strategy.

Strategy:
  - Base Seed: ₦50.00
  - Compound winnings through a 7-win streak.
  - Reset to ₦50.00 after 7 wins OR any loss.
  - ONLY place bets on "Safe Days" (Accuracy > 80% in last 10).
  - ONLY place bets on "Sure Picks" (Confidence ≥ 90%).
  - Single-leg (1-fixture) bets only for maximum safety.
"""

import json, sys, os, subprocess, time, re
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# ── Imports for Postgres ──
sys.path.insert(0, str(Path("/home/ubuntu/faith-workspace/vfl-empire/services")))
try:
    from common.db_manager import get_db
except ImportError:
    get_db = None

# ── Paths ──
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
BET_PLACER = SCRIPTS_DIR / "browser_bet_placer.py"
SIGNALS_DIR = BASE_DIR / "signals"
# DB_PATH is no longer used for settlement (Postgres)

STREAK_STATE_FILE = SIGNALS_DIR / "streak_state.json"
BANKROLL_FILE = SIGNALS_DIR / "bankroll.json"
LEDGER_FILE = SIGNALS_DIR / "bet_ledger.json"
PREDICTIONS_FILE = SIGNALS_DIR / "predictions_latest.json"
SIGNALS_FILE = SIGNALS_DIR / "betting_signals.json"

# ── Config ──
MIN_CONFIDENCE = 90
STREAK_TARGET = 7
BASE_STAKE = 50.0
DANGER_ZONE_START = 25
DANGER_ZONE_END = 30
TARGET_BANKROLL = 30000.0
SAFE_DAY_ACCURACY = 0.85 # Increased for the 30k Goal
SERVICE_FEE_PERCENT = 0.10 # 10% fee on profits to be banked in vault
PRIORITY_TEAMS = ["Manchester Blue", "Manchester Red", "London Guns", "Liverpool", "Chelsea", "Tottenham"]

class StreakManager:
    def __init__(self, state_path):
        self.state_path = Path(state_path)
        self.state = self._load_state()

    def _load_state(self):
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return json.load(f)
            except:
                pass
        return {
            "current_streak": 0,
            "current_stake": BASE_STAKE,
            "active_bet": None,
            "history": [],
            "total_profit": 0.0,
            "safe_day": False,
            "last_update": datetime.now(timezone.utc).isoformat()
        }

    def _save_state(self):
        self.state["last_update"] = datetime.now(timezone.utc).isoformat()
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def check_safe_day(self):
        """Check if the predictor has been performing well recently."""
        # Check simulation performance or recent history
        perf_file = SIGNALS_DIR / "simulation_performance.json"
        if perf_file.exists():
            try:
                with open(perf_file) as f:
                    perf = json.load(f)
                    # Use hit_rate_by_leg['1'] for single bets
                    leg1_hr = perf.get("hit_rate_by_leg", {}).get("1", {}).get("hit_rate", 0)
                    if leg1_hr >= SAFE_DAY_ACCURACY * 100:
                        self.state["safe_day"] = True
                        return True
            except:
                pass
        
        # Fallback: check last 10 in history
        history = self.state["history"][-10:]
        if len(history) >= 5:
            wins = sum(1 for b in history if b.get("won"))
            acc = wins / len(history)
            if acc >= SAFE_DAY_ACCURACY:
                self.state["safe_day"] = True
                return True
        
        # If no history, assume not safe yet
        self.state["safe_day"] = False
        return False

    def update_status(self):
        """Check if active bet is settled and update streak."""
        if not self.state.get("active_bet"):
            return "IDLE"

        bet = self.state["active_bet"]
        event_id = bet["legs"][0]["event_id"]
        
        try:
            if get_db:
                with get_db() as cur:
                    # 1. Try by exact event_id
                    cur.execute("SELECT * FROM results WHERE event_id = %s", (event_id,))
                    row = cur.fetchone()
                    
                    # 2. Fallback to Team + MD lookup (LATEST result only)
                    if not row:
                        home = bet["legs"][0]["home"]
                        away = bet["legs"][0]["away"]
                        md = bet["legs"][0]["matchday"]
                        cur.execute("""
                            SELECT * FROM results 
                            WHERE match_day = %s AND home_team = %s AND away_team = %s
                            ORDER BY id DESC LIMIT 1
                        """, (md, home, away))
                        row = cur.fetchone()
            else:
                print("⚠️ Postgres not available for settlement.")
                return "ERROR"
        except Exception as e:
            print(f"⚠️ Error checking results: {e}")
            return "ERROR"

        if row:
            won = self._check_won(bet["legs"][0], row)
            bet["won"] = won
            bet["settled_at"] = datetime.now(timezone.utc).isoformat()
            
            if won:
                self.state["current_streak"] += 1
                return_amt = round(bet["stake"] * bet["combined_odds"], 2)
                profit = round(return_amt - bet["stake"], 2)
                
                # Deduct Service Fee (Skim 10% of profit)
                fee = round(profit * SERVICE_FEE_PERCENT, 2)
                return_amt = round(return_amt - fee, 2)
                self.state["total_profit"] = round(self.state.get("total_profit", 0.0) + fee, 2)
                
                print(f"🎉 WIN! Streak: {self.state['current_streak']}/{STREAK_TARGET} | Return: ₦{return_amt} (Fee: ₦{fee} banked)")
                
                if self.state["current_streak"] >= STREAK_TARGET:
                    print(f"🏆 CYCLE COMPLETE! Target reached. Continuing with COMPOUNDED bankroll.")
                    self.state["current_stake"] = return_amt
                    self.state["current_streak"] = 0 
                    # Track net growth separately if needed
                else:
                    # Compound within cycle: next stake is the return amount
                    self.state["current_stake"] = return_amt
            else:
                print(f"❌ LOSS. Bankroll wiped. Resetting to ₦{BASE_STAKE}.")
                self.state["total_profit"] -= (self.state.get("current_stake", BASE_STAKE))
                self._reset()
            
            self.state["history"].append(bet)
            self.state["active_bet"] = None
            self._save_state()
            return "SETTLED"
            
        return "WAITING"

    def _reset(self):
        self.state["current_streak"] = 0
        self.state["current_stake"] = BASE_STAKE

    def _check_won(self, leg, row):
        market = leg["market"]
        hg = row["home_goals"]
        ag = row["away_goals"]
        total = hg + ag
        if "Over 1.5" in market: return total > 1
        if "Over 2.5" in market: return total > 2
        if "Under 3.5" in market: return total < 4
        if "BTTS Yes" in market: return hg > 0 and ag > 0
        if "BTTS No" in market: return hg == 0 or ag == 0
        if "Home" in market: return hg > ag
        if "Away" in market: return ag > hg
        return False

    def set_active_bet(self, pick, stake):
        self.state["active_bet"] = {
            "season_name": pick.get("season_name"),
            "matchday": pick["matchday"],
            "legs": [pick],
            "combined_odds": float(pick["odds"]),
            "stake": stake,
            "placed_at": datetime.now(timezone.utc).isoformat()
        }
        self._save_state()

def get_live_data():
    """Fetch current balance and matchday."""
    try:
        res = subprocess.run([sys.executable, str(BET_PLACER), "balance"], capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            bal_str = str(data.get("balance", "0")).replace("NGN", "").replace(",", "").strip()
            return {
                "balance": float(bal_str), 
                "matchday": data.get("matchday"),
                "available_mds": data.get("available_mds", [])
            }
    except:
        pass
    return None

def select_sure_pick(predictions, seen_keys):
    """Find a single high-confidence pick from latest predictions."""
    best = None
    max_conf = 0
    
    # Try parsing predictions_latest format (which is a list of matchdays)
    if isinstance(predictions, list):
        mds = predictions
    else:
        mds = predictions.get("matchdays", [predictions])

    for md in mds:
        season_name = md.get("season_id") or md.get("season_name")
        matchday = md.get("matchday")
        
        for f in md.get("fixtures", []):
            # Check 'predictions' list in the fixture
            preds = f.get("predictions", [])
            for p in preds:
                conf = p.get("confidence", 0)
                if conf < MIN_CONFIDENCE: continue
                
                market = p.get("market")
                pick_key = f"{season_name}|MD{matchday}|{f.get('home')}|{f.get('away')}|{market}"
                if pick_key in seen_keys: continue
                
                # Priority Bonus for Big 6 teams
                priority = 0
                if any(t in (f["home"], f["away"]) for t in PRIORITY_TEAMS):
                    priority = 500  # Massive boost to ensure priority teams are picked over West Ham etc.
                    
                score = conf + priority
                
                if score > max_conf:
                    max_conf = score
                    best = {
                        "home": f["home"],
                        "away": f["away"],
                        "market": market,
                        "odds": p["odds"],
                        "confidence": conf,
                        "matchday": matchday,
                        "season_name": season_name,
                        "event_id": f.get("event_id"),
                        "key": pick_key
                    }
    return best

def select_sure_pick_from_signals(signals_data, seen_keys):
    """Fallback: Find a pick from betting_signals.json."""
    best = None
    max_conf = 0
    signals = signals_data.get("signals", [])
    
    for s in signals:
        conf = s.get("confidence", 0)
        if conf < MIN_CONFIDENCE: continue
        
        pick_key = f"{s.get('season')}|MD{s.get('matchday')}|{s.get('match')}|{s.get('market')}"
        if pick_key in seen_keys: continue
        
        if conf > max_conf:
            max_conf = conf
            m_parts = s.get("match", "").split(" vs ")
            best = {
                "home": m_parts[0],
                "away": m_parts[1] if len(m_parts) > 1 else "?",
                "market": s.get("market"),
                "odds": s.get("odds"),
                "confidence": conf,
                "matchday": s.get("matchday"),
                "season_name": s.get("season"),
                "event_id": s.get("event_id"),
                "key": pick_key
            }
    return best

def main():
    print(f"👑 **VFL Streak Orchestrator** — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 0. Check for pause flag
    if (SIGNALS_DIR / "pause_betting.flag").exists():
        print("⛔ Betting paused by flag.")
        return

    # 1. Load state and live data
    manager = StreakManager(STREAK_STATE_FILE)
    live = get_live_data()
    if not live:
        print("⚠️ Could not fetch live data. Skipping.")
        return
    
    balance = live["balance"]
    current_md = live["matchday"]
    available_mds = live.get("available_mds", [])
    print(f"💰 Balance: ₦{balance:.2f} | Current MD: {current_md} | Open MDs: {available_mds}")

    # 2. Update status
    status = manager.update_status()
    print(f"🔄 Status: {status} | Streak: {manager.state['current_streak']}/{STREAK_TARGET} | Next Stake: ₦{manager.state['current_stake']}")

    if manager.state.get("active_bet"):
        print(f"⏳ Waiting for MD{manager.state['active_bet']['matchday']} to settle...")
        return

    # 2.5 Target Check
    if balance >= TARGET_BANKROLL:
        print(f"🏁 GOAL REACHED! Bankroll (₦{balance:.2f}) >= Target (₦{TARGET_BANKROLL:.2f})")
        return

    # 3. Safe Day check
    if not manager.check_safe_day():
        print("⚠️ Not a 'Safe Day' yet (Predictor accuracy < 85%). Waiting for safety.")
        return 

    # 4. Find Pick
    pick = None
    if PREDICTIONS_FILE.exists():
        try:
            with open(PREDICTIONS_FILE) as f:
                predictions = json.load(f)
            seen_keys = set(b.get("key", "") for b in manager.state["history"])
            pick = select_sure_pick(predictions, seen_keys)
        except Exception as e:
            print(f"⚠️ Error loading predictions: {e}")

    if not pick and SIGNALS_FILE.exists():
        try:
            with open(SIGNALS_FILE) as f:
                signals_data = json.load(f)
            seen_keys = set(b.get("key", "") for b in manager.state["history"])
            pick = select_sure_pick_from_signals(signals_data, seen_keys)
        except Exception as e:
            print(f"⚠️ Error loading signals: {e}")
    
    if not pick:
        print("⏳ No 'Sure Picks' (Conf ≥ 90%) found for upcoming matchdays.")
        return
    
    if pick["matchday"] not in available_mds:
        print(f"⏳ MD{pick['matchday']} is not open for betting (Available: {available_mds}). Waiting.")
        return

    if pick["matchday"] < current_md:
        print(f"⏳ Pick for MD{pick['matchday']} is in the past. Skipping.")
        return

    # 4.5 Prediction Gate — Verify pick against H2H and Regime
    print(f"🔍 Running prediction gate on {pick['home']} vs {pick['away']} → {pick['market']}...")
    try:
        gate_res = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "prediction_gate.py"),
             "--home", pick["home"], "--away", pick["away"],
             "--market", pick["market"], "--odds", str(pick["odds"]),
             "--confidence", str(pick.get("confidence", 50)), "--json"],
            capture_output=True, text=True, timeout=30
        )
        if gate_res.returncode == 0:
            gate_data = json.loads(gate_res.stdout)
            if gate_data.get("verdict") == "PASS":
                print(f"✅ Gate PASS")
            else:
                fails = [k for k,v in gate_data.get('gates',{}).items() if v.get('status') != 'PASS']
                print(f"🚫 Gate FAIL: {fails}. Skipping pick.")
                return
        else:
            print(f"⚠️ Gate error: {gate_res.stderr[:100]}. Proceeding with caution.")
    except Exception as e:
        print(f"⚠️ Gate exception: {e}")

    # 5. Calculate Stake
    stake = manager.state["current_stake"]
    if stake > balance:
        print(f"⚠️ Stake ₦{stake} exceeds balance. Capping at ₦{balance}.")
        stake = balance
    
    if stake < 20:
        print(f"⛔ Stake too low (₦{stake}).")
        return

    print(f"\n🎯 **Placing Streak Bet**")
    print(f"📅 {pick['season_name']} — MD{pick['matchday']}")
    print(f"⚽ {pick['home']} vs {pick['away']} → {pick['market']} @{pick['odds']} (Conf: {pick['confidence']}%)")
    print(f"💵 Stake: ₦{stake:.2f} | Potential Return: ₦{stake * float(pick['odds']):.2f}")

    # Place via browser
    input_data = {
        "home": pick["home"], "away": pick["away"],
        "market": pick["market"], "odds": pick["odds"],
        "stake": stake, "matchday": pick["matchday"]
    }
    
    try:
        res = subprocess.run([sys.executable, str(BET_PLACER), "bet", json.dumps(input_data)], capture_output=True, text=True, timeout=120)
        try:
            result = json.loads(res.stdout)
        except:
            print(f"❌ Failed to parse placer output. Raw: {res.stdout}")
            print(f"Stderr: {res.stderr}")
            return

        if result.get("success"):
            print("✅ Bet placed successfully!")
            manager.set_active_bet(pick, stake)
        else:
            print(f"❌ Placement failed: {result.get('error', 'Unknown error')}")
            if res.stderr: print(f"Placer Stderr: {res.stderr}")
            if result.get("page_text"):
                print(f"Page Preview: {result['page_text'][:200]}...")
    except Exception as e:
        print(f"❌ Error during placement: {e}")

if __name__ == "__main__":
    import logging
    logging.basicConfig(
        filename="/home/ubuntu/faith-workspace/vfl-empire/logs/streak_betting.log",
        level=logging.INFO,
        format="%(asctime)s %(message)s"
    )
    POLL_INTERVAL = 120  # seconds between checks
    print(f"🚀 VFL Streak Betting Daemon started. Polling every {POLL_INTERVAL}s.")
    while True:
        try:
            main()
        except Exception as e:
            print(f"❌ Unhandled error in main(): {e}")
        time.sleep(POLL_INTERVAL)
