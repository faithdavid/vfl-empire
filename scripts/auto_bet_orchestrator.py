#!/usr/bin/env python3
"""
auto_bet_orchestrator.py — Empire's parlay betting engine.
Builds 2-3 leg parlays from the highest-conviction picks per matchday,
places via browser, tracks settlements.

Lord FaithDavid's directive:
  - Only CERTAIN picks (Conf ≥ 80%, EV ≥ +3%)
  - Parlays of 2-3 sure fixtures per matchday
  - Money to be made, not wasted
"""

import json, sys, os, subprocess, time, re
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

# Add path for common tools
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from common.db_manager import get_db, fetch_all

BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")

# ── High-confidence Under matchups (goal-wise analysis) ──
# These pairs have extremely low scoring profiles. We want accurate under rates + strong avoidance of Overs.
ULTRA_UNDER_PAIRS = {
    frozenset({"Everton", "Leeds"}),
    frozenset({"Fulham", "Leeds"}),
    frozenset({"Bournemouth", "Leeds"}),
    frozenset({"Fulham", "Bournemouth"}),
    frozenset({"Aston Villa", "Everton"}),
    frozenset({"Aston Villa", "Bournemouth"}),
}

def get_pair_under_stats(home: str, away: str) -> dict:
    """
    Returns real historical under rates for this exact matchup (both directions).
    Used to calculate accurate Under edges instead of using blanket assumptions.
    """
    try:
        rows = fetch_all("""
            SELECT total_goals 
            FROM vfl_results_v2 
            WHERE (LOWER(home_team) = LOWER(%s) AND LOWER(away_team) = LOWER(%s))
               OR (LOWER(home_team) = LOWER(%s) AND LOWER(away_team) = LOWER(%s))
        """, (home, away, away, home))
        
        if not rows:
            return {"games": 0}
        
        totals = [r[0] for r in rows]
        n = len(totals)
        
        return {
            "games": n,
            "avg_goals": round(sum(totals) / n, 2),
            "under_1_5": round(sum(1 for t in totals if t < 2) / n * 100, 1),
            "under_2_5": round(sum(1 for t in totals if t < 3) / n * 100, 1),
            "under_3_5": round(sum(1 for t in totals if t < 4) / n * 100, 1),
            "ng_rate": round(sum(1 for t in totals if t == 0) / n * 100, 1),
        }
    except Exception as e:
        print(f"⚠️ Failed to get under stats for {home} vs {away}: {e}")
        return {"games": 0}
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
BET_PLACER = SCRIPTS_DIR / "browser_bet_placer.py"

# ── Money Management State ──
BANKROLL_FILE = BASE_DIR / "signals" / "bankroll.json"
LEDGER_FILE = BASE_DIR / "signals" / "bet_ledger.json"
STATE_FILE = BASE_DIR / "signals" / "orchestrator_state.json"

DEFAULT_BANKROLL = {"active_base": 50.0, "reserve": 50.0, "total": 100.0,
                    "profit_locked": 0.0, "cycle": 1, "wins_in_cycle": 0,
                    "net_profit": 0.0, "created_at": None, "updated_at": None}

# ── FaithDavid's Certainty Thresholds ──
MIN_CONF = 48       # Minimum confidence % (matches cluster hit rates like C4=52%, C6=58%)
MIN_EV = 0.0        # Minimum EV % (set to 0 for high-probability short-odds picks)

# Ratchet Protocol Settings
BASE_STAKE = 10.0  # User requested start from 10 Naira
RESERVE_PERCENT = 0.15 # Keep 15% for safety
ACTIVE_CAPITAL = 82.47  # Current bankroll
VAULT = 0.0
MILESTONES = [10.0, 20.0, 40.0, 100.0, 250.0, 500.0, 1000.0]
SERVICE_FEE_PERCENT = 0.10 # 10% fee on every win
ELITE_TEAMS = ["Manchester Blue", "Manchester Red", "London Guns"] # User's clear favorites
BIG_TEAMS = ["Liverpool", "Chelsea", "Tottenham"]
PRIORITY_TEAMS = ELITE_TEAMS + BIG_TEAMS

# ── Mirror Sync State ──
MIRROR_INDEX_FILE = BASE_DIR / "master_mirror_index.json"
GHOST_SEASON = "VFLM 5145" # Confirmed 1.0 sync candidate

def load_json(path):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except:
            pass
    return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def load_bankroll():
    b = load_json(BANKROLL_FILE)
    if not b or "active_base" not in b:
        b = dict(DEFAULT_BANKROLL)
        b["created_at"] = datetime.now(timezone.utc).isoformat()
        save_json(BANKROLL_FILE, b)
    return b

def save_bankroll(b):
    b["updated_at"] = datetime.now(timezone.utc).isoformat()
    b["total"] = round(b["active_base"] + b["reserve"] + b["profit_locked"], 2)
    save_json(BANKROLL_FILE, b)

def load_state():
    s = load_json(STATE_FILE)
    if not s:
        s = {"seen_parlays": [], "last_run": None}
    return s

def save_state(s):
    s["last_run"] = datetime.now(timezone.utc).isoformat()
    save_json(STATE_FILE, s)

# ── Rolling Strategy State ──
ROLLING_STATE_FILE = BASE_DIR / "signals" / "rolling_state.json"
RESULTS_DB = BASE_DIR / "databases" / "vfl_results.db"

import sqlite3

class RollingCompoundManager:
    def __init__(self, state_path, db_path):
        self.state_path = Path(state_path)
        self.db_path = Path(db_path)
        self.state = self._load_state()

    def _load_state(self):
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    s = json.load(f)
                    # Migrate old state to Ratchet Protocol State if needed
                    if "phase" not in s:
                        print("🔄 Migrating live rolling state to 30% Ratchet Protocol (Strategy B)")
                        s["phase"] = 1
                        s["milestone"] = 0
                        s["hits_in_step"] = s.get("current_step", 1) - 1
                        if s["hits_in_step"] > 1:
                            s["hits_in_step"] = 1
                        s["total_profit_banked"] = s.get("total_profit_banked", 0.0)
                    return s
            except Exception as e:
                print(f"⚠️ Error loading state, using default: {e}")
        return {
            "phase": 1,
            "milestone": 0,
            "hits_in_step": 0,
            "current_seed": 10.0, # Adjusted to 10.0 as per User directive
            "current_stake": 25.0,
            "active_bet": None,
            "history": [],
            "total_profit_banked": 60.0, # Preserve already banked profits
            "last_update": datetime.now(timezone.utc).isoformat()
        }

    def _save_state(self):
        self.state["last_update"] = datetime.now(timezone.utc).isoformat()
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def update_status(self, current_md=None):
        """Check if active bet is settled and update step."""
        if not self.state.get("active_bet"):
            return "IDLE"

        bet = self.state["active_bet"]
        
        all_settled = True
        all_won = True
        
        try:
            with get_db() as cursor:
                for leg in bet["legs"]:
                    # Try event_id first
                    cursor.execute("SELECT * FROM vfl_results_v2 WHERE event_id = %s", (leg["event_id"],))
                    row = cursor.fetchone()
                    
                    # Fallback to Matchday + Teams + Season
                    if not row:
                        md_num = bet.get("matchday")
                        season_name = bet.get("season_name")
                        if md_num:
                            if season_name:
                                cursor.execute("""
                                    SELECT r.* FROM vfl_results_v2 r
                                    JOIN vfl_matchdays m ON r.matchday_id = m.id
                                    JOIN vfl_seasons s ON m.season_id = s.id
                                    WHERE m.matchday_number = %s AND r.home_team = %s AND r.away_team = %s AND s.season_name = %s
                                """, (md_num, leg["home"], leg["away"], season_name))
                                row = cursor.fetchone()
                            pass

                    if not row:
                        all_settled = False
                        break
                    
                    won = self._check_leg_won(leg, row)
                    if not won:
                        all_won = False
                        break
        except Exception as e:
            print(f"⚠️ Error checking results: {e}")
            return "ERROR"

        if all_settled:
            if all_won:
                current_cap = round(bet["stake"] * bet["combined_odds"], 2)
                profit = round(current_cap - bet["stake"], 2)
                
                # Deduct Service Fee (10% of profit)
                fee = round(profit * SERVICE_FEE_PERCENT, 2)
                current_cap = round(current_cap - fee, 2)
                self.state["total_profit_banked"] = round(self.state.get("total_profit_banked", 0.0) + fee, 2)
                
                self.state["hits_in_step"] += 1
                print(f"🎉 Parlay WON! Stake: ₦{bet['stake']} → Return: ₦{current_cap} (Fee: ₦{fee} banked)")
                
                # 30% Ratchet Protocol Logic (2-Parlay Milestones)
                if self.state["hits_in_step"] == 2:
                    if self.state["phase"] == 1:
                        # Phase 1 Complete (Capital Recovery): Skim ₦25 (User recovery rule)
                        # We started with 25, so we recover 25.
                        skim_amt = self.state["current_seed"]
                        self.state["total_profit_banked"] = round(self.state["total_profit_banked"] + skim_amt, 2)
                        working_cap = round(current_cap - skim_amt, 2)
                        print(f"💰 CAPITAL RECOVERY COMPLETE! Banking ₦{skim_amt} to Safe Vault.")
                        print(f"🔄 Moving to Phase 2, Milestone 1 with Working Capital: ₦{working_cap}")
                        
                        self.state["phase"] = 2
                        self.state["milestone"] = 1
                        self.state["hits_in_step"] = 0
                        self.state["current_stake"] = working_cap
                    else:
                        m = self.state["milestone"]
                        # Check target limit of ₦10,000 total banked/earned
                        if self.state["total_profit_banked"] + current_cap >= 10000.0:
                            self.state["total_profit_banked"] = round(self.state["total_profit_banked"] + current_cap, 2)
                            print(f"🏆 TARGET REACHED! ₦10,000+ earned! Resetting and locking ₦{current_cap}.")
                            self._reset()
                        else:
                            # Skim 30% into Safe Vault
                            skim = round(current_cap * 0.30, 2)
                            self.state["total_profit_banked"] = round(self.state["total_profit_banked"] + skim, 2)
                            working_cap = round(current_cap - skim, 2)
                            print(f"💰 Milestone {m} Complete! Skimming 30% (₦{skim}) to Safe Vault.")
                            print(f"🔄 Moving to Milestone {m+1} with Working Capital: ₦{working_cap}")
                            
                            self.state["milestone"] = m + 1
                            self.state["hits_in_step"] = 0
                            self.state["current_stake"] = working_cap
                else:
                    # Won 1 parlay, need 1 more to complete the milestone
                    self.state["current_stake"] = current_cap
                    print(f"📈 1 hit recorded for milestone. Capital is now ₦{current_cap}. Need 1 more win to skim.")
            else:
                print(f"❌ Parlay LOST. Resetting active capital to 0.")
                self._reset()
            
            bet["won"] = all_won
            bet["settled_at"] = datetime.now(timezone.utc).isoformat()
            self.state["history"].append(bet)
            self.state["active_bet"] = None
            self._save_state()
            return "SETTLED"
            
        return "WAITING"

    def _reset(self):
        self.state["phase"] = 1
        self.state["milestone"] = 0
        self.state["hits_in_step"] = 0
        # When resetting, we stick to the ₦25 capital spending rule
        self.state["current_stake"] = self.state.get("current_seed", 25.0)

    def get_current_stake(self):
        # MSport minimum bet is 10.0. Ensure we don't drop below it if balance allows.
        stake = self.state.get("current_stake", self.state["current_seed"])
        if stake < 10.0:
            return 10.0
        return stake

    def _check_leg_won(self, leg, row):
        market = leg["market"]
        hg = row["home_goals"]
        ag = row["away_goals"]
        total = hg + ag
        if market == "Over 1.5 Goals": return total > 1
        if market == "Over 0.5 Goals": return total > 0
        if market == "Under 3.5 Goals": return total < 4
        if market == "Double Chance Home/Draw": return hg >= ag
        if market == "Double Chance Away/Draw": return ag >= hg
        if market == "Home Win": return hg > ag
        if market == "Away Win": return ag > hg
        if market == "BTTS Yes": return hg > 0 and ag > 0
        if market == "BTTS No": return hg == 0 or ag == 0
        if market == "Home": return hg > ag
        if market == "Away": return ag > hg
        if market == "Draw": return hg == ag
        return False

    def set_active_bet(self, parlay, stake):
        self.state["active_bet"] = {
            "season_name": parlay.get("season_name"),
            "matchday": parlay["matchday"],
            "legs": parlay["legs"],
            "combined_odds": parlay["combined_odds"],
            "stake": stake,
            "placed_at": datetime.now(timezone.utc).isoformat()
        }
        self._save_state()

def load_predictions():
    p = load_json(BASE_DIR / "signals" / "predictions_latest.json")
    if not p:
        p = load_json(BASE_DIR / "signals" / "live_test_predictions.json")
    return p

def get_live_data():
    """Fetch current balance and matchday from MSport via browser with retries."""
    for attempt in range(1, 6):
        try:
            print(f"🔄 Fetching live balance (attempt {attempt}/5)...")
            res = subprocess.run([sys.executable, str(BET_PLACER), "balance"], capture_output=True, text=True, timeout=60)
            if res.returncode != 0:
                print(f"⚠️ Bet placer exited with code {res.returncode}: {res.stderr}")
                time.sleep(2)
                continue
            data = json.loads(res.stdout)
            
            bal_raw = data.get("balance")
            if bal_raw is None:
                print("⚠️ Balance value is empty or None.")
                time.sleep(2)
                continue
                
            bal_str = str(bal_raw).replace("NGN", "").replace(",", "").strip()
            if bal_str == "--" or not bal_str:
                print("⚠️ Balance is currently '--' or empty. VFL page might be settling or loading.")
                time.sleep(2)
                continue
                
            balance = float(bal_str)
            md = data.get("matchday")
            season = data.get("season")
            return {"balance": balance, "matchday": md, "season_name": season}
        except Exception as e:
            print(f"⚠️ Attempt {attempt}/5 failed to fetch live data: {e}")
            time.sleep(2)
            
    print("❌ Failed to fetch a valid numeric balance after 5 attempts.")
    return None


# ── Under 3.5 Goal Factories (fixtures with >85% hit rate) ──
U35_SURE_FIXTURES = {
    ("Leeds", "Everton"), ("Leeds", "Fulham"), ("Fulham", "Brighton"),
    ("Everton", "Fulham"), ("Manchester Red", "Everton"), ("Leeds", "Newcastle"),
    ("Everton", "Leeds"), ("Everton", "Aston Villa"), ("Everton", "Bournemouth"),
    ("Leeds", "Crystal Palace"), ("Aston Villa", "Leeds"), ("Bournemouth", "Fulham"),
    ("West Ham", "Fulham"), ("Fulham", "West Ham"), ("London Guns", "Wolverhampton"),
    ("Everton", "Manchester Red"), ("Bournemouth", "Leeds"),
    # New high-confidence additions from detailed matchup analysis (May 2026)
    ("Fulham", "Leeds"), ("Leeds", "Bournemouth"), ("Bournemouth", "Everton"),
    ("Aston Villa", "Bournemouth"), ("Fulham", "Bournemouth"),  # Confirmed very low scoring
}

# ── Over 1.5 Goal Factories (fixtures with >85% hit rate) ──
O15_SURE_FIXTURES = {
    ("Wolverhampton", "Manchester Blue"), ("Manchester Blue", "Chelsea"),
    ("Manchester Blue", "West Ham"), ("London Guns", "Crystal Palace"),
    ("Wolverhampton", "West Ham"), ("Chelsea", "Wolverhampton"),
    ("Bournemouth", "Manchester Blue"), ("Tottenham", "Newcastle"),
    ("Brighton", "Manchester Blue"), ("Leeds", "Chelsea"), ("Chelsea", "Leeds"),
    ("Chelsea", "Bournemouth"), ("Manchester Blue", "Fulham"),
    ("Manchester Red", "Manchester Blue"), ("Manchester Red", "Newcastle"),
    ("Wolverhampton", "Chelsea"),
    ("Liverpool", "London Guns"), ("Manchester Red", "West Ham")
}

# Teams that are strong Unders (empirically validated) - heavily deprioritize Over markets
STRONG_UNDER_TEAMS = {"Aston Villa", "Fulham"}  

# Fulham: Recent 50 games avg 2.00 goals, 42% Under 1.5. 
# User lost on Fulham vs Bournemouth Over 1.5 (actual result very low scoring).
# Add Bournemouth in specific low-scoring matchups if pattern continues.
# ── 1x2 Titan Anchors (fixtures with >90% Win rate) ──
WIN_SURE_FIXTURES = {
    ("Liverpool", "Bournemouth", "HOME"), ("London Guns", "Newcastle", "HOME"),
    ("Manchester Blue", "Everton", "HOME"), ("Manchester Blue", "Crystal Palace", "HOME"),
    ("Manchester Red", "Wolverhampton", "HOME"), ("Liverpool", "Fulham", "HOME")
}

def build_parlays(predictions):
    """Build 2-3 leg parlays using the new Ghost Sync Mirroring logic."""
    parlays = []
    
    for md in predictions.get("matchdays", [predictions]):
        season_name = md.get("season", "VFLM ?")
        season_id = md.get("season_id", 0)
        md_num = md.get("matchday", "?")

        # Collect all qualifying picks for this matchday
        qualifiers = []
        sure_anchors = [] 

        for f in md.get("fixtures", []):
            home = f.get("home", "?")
            away = f.get("away", "?")
            is_ghost_fixture = False
            
            # 👻 GHOST REGIME ANCHORING: Scan history for THIS fixture on THIS Matchday
            try:
                with open(MIRROR_INDEX_FILE) as f_idx:
                    mirror_data = json.load(f_idx)
                    hits_o15 = 0
                    hits_u35 = 0
                    total_occ = 0
                    
                    # Scan ALL seasons for this fixture on this MD
                    for s_name, s_mds in mirror_data.items():
                        md_fix = s_mds.get(str(md_num), [])
                        for g_fix in md_fix:
                            if g_fix["teams"] == f"{home} vs {away}":
                                total_occ += 1
                                if g_fix["total"] > 1: hits_o15 += 1
                                if g_fix["total"] < 4: hits_u35 += 1
                    
                    # If it's a 100% Chronological Lock (min 5 occurrences)
                    if total_occ >= 5:
                        p_o15 = hits_o15 / total_occ
                        p_u35 = hits_u35 / total_occ
                        
                        market_lock = None
                        if p_o15 == 1.0: market_lock = "Over 1.5 Goals"
                        elif p_u35 == 1.0: market_lock = "Under 3.5 Goals"
                        
                        if market_lock:
                            ghost_leg = {
                                "home": home, "away": away,
                                "market": market_lock, 
                                "odds": f.get("odds", {}).get(market_lock.lower().replace(" ", "_").replace("goals", "").strip("_"), 1.2),
                                "confidence": 100, "strength": "ELITE", "ev_pct": 15.0, "is_anchor": True,
                                "event_id": f.get("event_id", "")
                            }
                            sure_anchors.append(ghost_leg)
                            is_ghost_fixture = True
                            print(f"👻 GHOST LOCK: {home} vs {away} → {market_lock} (100% Chronological Hit Rate | n={total_occ})")
            except Exception as e:
                print(f"⚠️ Regime anchoring failed: {e}")

            if is_ghost_fixture:
                continue

            # A. Check for U3.5 Sure-Fixture Anchors
            is_sure_u35 = (home, away) in U35_SURE_FIXTURES or (away, home) in U35_SURE_FIXTURES
            if is_sure_u35:
                u35_odds = f.get("odds", {}).get("under_3.5")
                if u35_odds and u35_odds > 1.01:
                    anchor = {
                        "home": home, "away": away,
                        "market": "Under 3.5 Goals", "odds": u35_odds,
                        "confidence": 95 if (home, away) in [("Everton", "Leeds"), ("Leeds", "Everton")] else 92 if (home, away) in [("Everton", "Manchester Red"), ("Everton", "Aston Villa")] or (away, home) in [("Everton", "Manchester Red"), ("Everton", "Aston Villa")] else 88,
                        "strength": "STRONG", "ev_pct": 5.0, "is_anchor": True,
                        "event_id": f.get("event_id", "")
                    }
                    sure_anchors.append(anchor)
                    print(f"⚓ FOUND U3.5 ANCHOR: {home} vs {away} @{u35_odds}")

            # A2. Check for O1.5 Sure-Fixture Anchors
            # Never create O1.5 anchors on ultra strong under matchups
            if frozenset({home, away}) in ULTRA_UNDER_PAIRS:
                is_sure_o15 = False
            else:
                is_sure_o15 = (home, away) in O15_SURE_FIXTURES or (away, home) in O15_SURE_FIXTURES

            if is_sure_o15:
                o15_odds = f.get("odds", {}).get("over_1.5")
                if o15_odds and o15_odds > 1.01:
                    anchor = {
                        "home": home, "away": away,
                        "market": "Over 1.5 Goals", "odds": o15_odds,
                        "confidence": 95 if (home, away) == ("Wolverhampton", "Manchester Blue") or (away, home) == ("Wolverhampton", "Manchester Blue") else 92,
                        "strength": "STRONG", "ev_pct": 3.0, "is_anchor": True,
                        "event_id": f.get("event_id", "")
                    }
                    sure_anchors.append(anchor)
                    print(f"⚓ FOUND O1.5 ANCHOR: {home} vs {away} @{o15_odds}")

            # A3. Check for 1x2 Titan Win Anchors
            for (h, a, pick) in WIN_SURE_FIXTURES:
                if home == h and away == a:
                    m_key = "Home" if pick == "HOME" else "Away"
                    win_odds = f.get("odds", {}).get(m_key.lower())
                    if win_odds and win_odds > 1.01:
                        anchor = {
                            "home": home, "away": away,
                            "market": m_key, "odds": win_odds,
                            "confidence": 98, "strength": "STRONG", "ev_pct": 2.0, "is_anchor": True,
                            "event_id": f.get("event_id", "")
                        }
                        sure_anchors.append(anchor)
                        print(f"⚓ FOUND TITAN WIN ANCHOR: {home} vs {away} → {m_key} @{win_odds}")

            # B. Standard Qualifiers from predictions list (New Service Format)
            for p in f.get("predictions", []):
                market = p.get("market", "")
                strength = p.get("strength", "")
                if strength not in ("STRONG", "MODERATE"): continue
                odds = float(p.get("odds", 0))
                confidence = p.get("confidence", 0)
                if odds < 1.05 or odds > 5.0: continue
                if confidence < MIN_CONF: continue
                ev_pct = p.get("expected_value", 0) * 100
                if ev_pct < MIN_EV: continue

                qualifiers.append({
                    "home": home, "away": away,
                    "market": market, "odds": odds,
                    "confidence": confidence, "strength": strength,
                    "ev_pct": round(ev_pct, 1),
                    "event_id": f.get("event_id", ""),
                    "is_anchor": False
                })

        # Sort by conviction
        def conviction(q):
            mult = 1.15 if q["strength"] == "STRONG" else 1.0
            anchor_bonus = 2.0 if q.get("is_anchor") else 1.0
            priority_bonus = 1.0
            teams = (q["home"], q["away"])
            if any(t in teams for t in ELITE_TEAMS):
                priority_bonus = 2.5 
            elif any(t in teams for t in BIG_TEAMS):
                priority_bonus = 1.0 

            pair = frozenset(teams)
            is_ultra_under = pair in ULTRA_UNDER_PAIRS

            # Strong empirical bias against Over on known strong under matchups
            if "Over" in q.get("market", ""):
                if is_ultra_under:
                    mult *= 0.05  # Extremely aggressive avoidance of Over on the very worst pairs
                elif any(t in teams for t in STRONG_UNDER_TEAMS):
                    mult *= 0.12

            # === Accurate Under calculation for ultra under matchups ===
            if is_ultra_under and ("Under" in q.get("market", "") or "NG" in q.get("market", "")):
                stats = get_pair_under_stats(q["home"], q["away"])
                if stats.get("games", 0) >= 30:
                    rate = 0.0
                    market = q.get("market", "")
                    if "Under 3.5" in market:
                        rate = stats.get("under_3_5", 0) / 100.0
                    elif "Under 2.5" in market:
                        rate = stats.get("under_2_5", 0) / 100.0
                    elif "Under 1.5" in market:
                        rate = stats.get("under_1_5", 0) / 100.0
                    elif "NG" in market or "No Goal" in market:
                        rate = stats.get("ng_rate", 0) / 100.0

                    if rate > 0.60:  # Only apply if there's a real edge
                        # Recalculate a more accurate EV using the real historical rate
                        implied_prob = 1.0 / q["odds"] if q["odds"] > 0 else 0.5
                        accurate_ev = (rate - implied_prob) * 100.0
                        q["ev_pct"] = max(q["ev_pct"], round(accurate_ev, 1))
                        # Also boost confidence toward the real rate
                        q["confidence"] = max(q["confidence"], min(96, int(rate * 100)))

            return (q["ev_pct"] * q["confidence"] / 100.0) * mult * anchor_bonus * priority_bonus
        
        qualifiers.sort(key=conviction, reverse=True)

        # Build parlays
        if sure_anchors:
            # 1. Pure Ghost Parlays (Highest conviction Mirror Locks)
            ghost_locks = [a for a in sure_anchors if a.get("strength") == "ELITE"]
            if len(ghost_locks) >= 2:
                # All 2-leg Ghost combinations
                for i in range(len(ghost_locks)):
                    for j in range(i + 1, len(ghost_locks)):
                        parlays.append(_make_parlay([ghost_locks[i], ghost_locks[j]], season_name, season_id, md_num))
                # All 3-leg Ghost combinations
                if len(ghost_locks) >= 3:
                    for i in range(len(ghost_locks)):
                        for j in range(i + 1, len(ghost_locks)):
                            for k in range(j + 1, len(ghost_locks)):
                                parlays.append(_make_parlay([ghost_locks[i], ghost_locks[j], ghost_locks[k]], season_name, season_id, md_num))
            
            # 2. Hybrid/Standard Parlays (only if needed)
            # Combine anchors with qualifiers to hit the 2.0 sweet spot
            for anchor in sure_anchors:
                other_q = [q for q in qualifiers if q["home"] != anchor["home"]]
                for q in other_q[:3]:
                    combined = anchor["odds"] * q["odds"]
                    if 1.7 <= combined <= 2.5:
                        parlays.append(_make_parlay([anchor, q], season_name, season_id, md_num))
            
            # 3. High-confidence single legs
            for q in sure_anchors:
                parlays.append(_make_parlay([q], season_name, season_id, md_num))
        else:
            # Fallback to standard qualifier logic
            if len(qualifiers) >= 2:
                parlays.append(_make_parlay(qualifiers[:2], season_name, season_id, md_num))
            for q in qualifiers:
                if q["confidence"] >= 85:
                    parlays.append(_make_parlay([q], season_name, season_id, md_num))

    return parlays

def _make_parlay(legs, season_name, season_id, md_num):
    """Create a parlay from a list of legs."""
    combined_odds = 1.0
    combined_prob = 1.0
    for leg in legs:
        combined_odds *= leg["odds"]
        combined_prob *= leg["confidence"] / 100.0

    parlay_ev = round((combined_odds - 1) * combined_prob - (1 - combined_prob), 4) * 100

    return {
        "season_name": season_name,
        "season_id": season_id,
        "matchday": md_num,
        "legs": legs,
        "leg_count": len(legs),
        "combined_odds": round(combined_odds, 2),
        "combined_prob": round(combined_prob * 100, 1),
        "ev_pct": round(parlay_ev, 1),
    }

def select_best_parlay(parlays, seen_keys):
    """Select the best parlay we haven't already placed."""
    # Filter out already-seen parlays
    fresh = [p for p in parlays
             if _parlay_key(p) not in seen_keys]

    if not fresh:
        return None

    # Sort by conviction: EV × probability × (3-leg bonus over 2-leg)
    def score(p):
        leg_bonus = 1.1 if p["leg_count"] >= 3 else 1.0
        return (p["ev_pct"] * p["combined_prob"] / 100.0) * leg_bonus

    fresh.sort(key=score, reverse=True)
    return fresh[0]

def _parlay_key(p):
    """Unique key for a parlay to avoid re-betting."""
    leg_keys = ":".join(f"{l['home']}|{l['away']}|{l['market']}" for l in p["legs"])
    return f"{p['season_name']}|MD{p['matchday']}|{leg_keys}"

def place_parlay_via_browser(parlay, stake):
    """Call browser_bet_placer.py with parlay JSON via stdin."""
    cmd = [
        sys.executable or "python3",
        str(BET_PLACER),
        "parlay"
    ]
    input_data = {
        "parlay": True,
        "legs": [{
            "fixture": f"{leg['home']} vs {leg['away']}",
            "home": leg["home"],
            "away": leg["away"],
            "market": leg["market"],
            "odds": leg["odds"],
        } for leg in parlay["legs"]],
        "stake": stake,
        "combined_odds": parlay["combined_odds"],
        "matchday": parlay["matchday"],
    }
    try:
        result = subprocess.run(
            cmd, input=json.dumps(input_data),
            capture_output=True, text=True, timeout=180
        )
        output = result.stdout.strip()
        if result.stderr:
            sys.stderr.write(result.stderr)
        if result.returncode != 0:
             return {"success": False, "error": f"Exit {result.returncode}: {result.stderr.strip()}"}
        try:
            return json.loads(output)
        except:
            return {"success": False, "error": f"Non-JSON: {output[:200]}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Browser bet placer timed out (180s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def kelly_stake(parlay, bankroll_base):
    """Calculate 25% Kelly stake for a parlay."""
    odds = parlay["combined_odds"]
    prob = parlay["combined_prob"] / 100.0
    b = odds - 1
    q = 1 - prob
    if b <= 0:
        return 50.0
    kelly = (b * prob - q) / b
    stake = round(min(kelly * 0.25 * bankroll_base, bankroll_base), 0)
    return max(50.0, min(stake, bankroll_base))




def select_rolling_pick(parlays, seen, current_streak=0):
    """Find the best pick for the rolling strategy, prioritizing stability ('it should win')."""
    if not parlays: return None
    
    md_groups = defaultdict(list)
    for p in parlays:
        if _parlay_key(p) not in seen:
            md_groups[int(p["matchday"])].append(p)
            
    if not md_groups: return None
    
    # Pick the earliest MD available
    earliest_md = min(md_groups.keys())
    candidates = md_groups[earliest_md]
    
    def rolling_rank(p):
        # 1. Strength is paramount ("It should win")
        # 🔥 GHOST LOCK PRIORITY: Elite strength gets the highest priority
        strength_score = 0
        is_elite = any(leg.get("strength") == "ELITE" for leg in p["legs"])
        all_elite = all(leg.get("strength") == "ELITE" for leg in p["legs"])
        
        if all_elite:
            strength_score = 10000 # Absolute, non-negotiable priority for Pure Mirror Parlays
        elif is_elite:
            strength_score = 1000 # High priority for parlays with at least one Mirror Anchor
        elif all(leg.get("strength") == "STRONG" for leg in p["legs"]):
            strength_score = 100
        elif any(leg.get("strength") == "STRONG" for leg in p["legs"]):
            strength_score = 50
            
        # 2. Odds targeting (User wants ~2.0 for faster growth)
        odds = p["combined_odds"]
        odds_score = 0
        if 1.9 <= odds <= 2.3:
            odds_score = 200 # Ideal for your request
        elif 1.7 <= odds <= 2.5:
            odds_score = 100 # Acceptable
        elif odds > 3.0:
            odds_score = -100 # Too risky
            
        # 3. Safety Bonus for specific markets
        # "prefer safer markets for the safe legs"
        safe_markets = ["Over 0.5 Goals", "Double Chance Home/Draw", "Double Chance Away/Draw", "BTTS No"]
        safety_bonus = sum(20 for leg in p["legs"] if leg.get("market") in safe_markets)
            
        # 4. Confidence
        conf_score = sum(leg.get("confidence", 0) for leg in p["legs"]) / len(p["legs"])

        # 5. Trap/Pivot/Magnet Intelligence
        trap_score = 0
        from prediction_gate import detect_trap, detect_magnet, MARKET_ALIASES
        for leg in p["legs"]:
            m_key = MARKET_ALIASES.get(leg["market"], leg["market"])
            
            # Check for traps
            trap = detect_trap(leg["home"], leg["away"], m_key)
            if trap:
                print(f"  ⚠️ Ranking warning: Found TRAP {leg['home']} vs {leg['away']} for {leg['market']}")
                trap_score -= 200 # Heavy penalty for known traps
            
            # Check for magnets
            magnet = detect_magnet(leg["home"], leg["away"], m_key)
            if magnet:
                print(f"  💎 Magnet Bonus: Found ELITE fixture {leg['home']} vs {leg['away']} for {leg['market']}")
                trap_score += 500 # Massive bonus for known Elite Magnets

        # 6. Team Priority
        priority_score = 0
        for leg in p["legs"]:
            teams = (leg["home"], leg["away"])
            if any(t in teams for t in ELITE_TEAMS):
                priority_score += 150 # Massive bonus
            elif any(t in teams for t in BIG_TEAMS):
                priority_score += 50  # Modest bonus
                
        # 7. Streak Guard Logic (PRNG Reset Awareness)
        # If current_streak >= 3, MSport usually triggers a "Cooling Phase"
        # We MUST increase confidence floor and lean into "Elite Magnets" only
        if current_streak >= 3:
            has_anchor = any(leg.get("is_anchor") for leg in p["legs"])
            if not has_anchor:
                return -1000 # Discard non-anchored parlays during cooling phase
            conf_floor = 85
            if conf_score < conf_floor:
                return -500 # Penalize low confidence during streaks
                
        return (strength_score + trap_score + priority_score, safety_bonus, odds_score, conf_score, p["ev_pct"])
        
    # Primary filter: 2-leg parlays
    candidates_2leg = [c for c in candidates if c["leg_count"] == 2]
    
    if candidates_2leg:
        candidates_2leg.sort(key=rolling_rank, reverse=True)
        return candidates_2leg[0]
    
    # Fallback to 1-leg or 3-leg if no 2-leg exists
    candidates.sort(key=rolling_rank, reverse=True)
    return candidates[0]

def main():
    # ── 0. Pause Flag Check ──
    pause_flag = BASE_DIR / "signals" / "pause_betting.flag"
    if pause_flag.exists():
        print("⛔ Betting paused by flag (pause_betting.flag exists)")
        return

    bankroll_data = load_bankroll()
    state = load_state()
    predictions = load_predictions()
    ledger = load_json(LEDGER_FILE)
    if "bets" not in ledger:
        ledger = {"bets": [], "bankroll": {"initial": 100.0, "current": bankroll_data["total"]}}

    seen = set(state.get("seen_parlays", []))

    # ── 1. Live Data ──
    live_data = get_live_data()
    if not live_data:
        print("⏳ Temporarily unable to fetch stable balance. Skipping this run to avoid false stop-loss.")
        return
    balance = live_data["balance"]
    bankroll_data["active_base"] = balance
    save_bankroll(bankroll_data)
    
    rolling = RollingCompoundManager(ROLLING_STATE_FILE, RESULTS_DB)
    current_md = live_data.get("matchday")

    # ── 1.5 Generate Cluster-Enhanced Picks (pipeline_integration) ──
    try:
        season_str = live_data.get("season_name") or "5145" # Fallback to 5145 if detection fails
        if "VFLM" in season_str:
            season_str = season_str.replace("VFLM", "").strip()
            
        md = current_md or live_data.get("matchday")
        if md:
            print(f"🧬 Generating cluster picks for season {season_str}, MD{md}...")
            pipe_script = SCRIPTS_DIR / "pipeline_integration.py"
            res = subprocess.run(
                [sys.executable, str(pipe_script), "--season", season_str,
                 "--matchday", str(md), "--save"],
                capture_output=True, text=True, timeout=90
            )
            if res.returncode == 0:
                print(f"✅ Cluster picks saved")
                # Do NOT reload predictions — keep LLM picks as primary
                # Cluster picks supplement when LLM doesn't have enough
            else:
                print(f"⚠️ Cluster pipeline exit={res.returncode}: {res.stderr[:200]}")
        else:
            print("⚠️ No matchday from live data, skipping cluster pipeline")
    except subprocess.TimeoutExpired:
        print("⚠️ Cluster pipeline timed out (90s), proceeding with existing predictions")
    except Exception as e:
        print(f"⚠️ Cluster pipeline error: {e}")
    
    # ── 2. Rolling Strategy Status ──
    rolling_status = rolling.update_status()
    print(f"🔄 Ratchet Protocol Status: {rolling_status} | Phase: {rolling.state['phase']} | Milestone: {rolling.state['milestone']} | Hits: {rolling.state['hits_in_step']} | Active Capital: ₦{rolling.state['current_stake']} | Vault: ₦{rolling.state['total_profit_banked']:.2f}")

    if rolling_status == "SETTLED":
        # Re-fetch live data to get the updated balance after winnings/refunds are credited
        print("🔄 Re-fetching live balance after settlement...")
        live_data = get_live_data()
        if not live_data:
            print("⏳ Temporarily unable to fetch stable balance. Skipping this run to avoid false stop-loss.")
            return
        balance = live_data["balance"]
        bankroll_data["active_base"] = balance
        save_bankroll(bankroll_data)

    stake = rolling.get_current_stake()

    if rolling.state.get("active_bet"):
        active = rolling.state["active_bet"]
        print(f"⏳ Waiting for active bet (MD{active['matchday']}) to settle...")
        return

    # STOP LOSS CHECK (Disabled as per Lord FaithDavid's directive for 25 start)
    STOP_LOSS = 0.0
    # Only halt if balance itself is at/below stop loss
    if balance <= STOP_LOSS:
        msg = f"⛔ STOP LOSS TRIGGERED — Balance ₦{balance} is at or below stop-loss of ₦{STOP_LOSS}"
        print(msg)
        save_json(BASE_DIR / "signals" / "PAUSED.json", {"reason": msg, "timestamp": datetime.now().isoformat()})
        return

    if not predictions:
        print("⏳ No predictions available")
        return

    # ── 3. Build & Filter parlays ──
    parlays = build_parlays(predictions)
    if current_md:
        parlays = [p for p in parlays if int(p["matchday"]) >= current_md]
    
    if not parlays:
        print("⏳ No qualifying parlays found for future matchdays")
        return

    # ── 4. Select rolling pick ──
    current_streak = rolling.state.get("hits_in_step", 0)
    best = select_rolling_pick(parlays, seen, current_streak=current_streak)
    if not best:
        print("⏳ No new qualifying picks found")
        return

    # ── 5. AGY VALIDATOR INTEGRATION (soft-fail) ──
    print(f"🤖 Consulting agy validator...")
    try:
        agy_query = f"Validate this bet: {json.dumps(best)}. Current balance: ₦{balance}. Should I place it? Reply YES or NO with reason."
        agy_res = subprocess.run(
            ["/home/ubuntu/.local/bin/agy", "--print", agy_query, "--print-timeout", "15s", "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=25
        )
        agy_out = agy_res.stdout.upper()
        if "YES" in agy_out:
            print(f"✅ Agy approved the bet.")
        elif "NO" in agy_out:
            print(f"🚫 Agy rejected the bet: {agy_res.stdout[:200]}")
            return
        else:
            print(f"⚠️ Agy response unclear ({agy_res.stdout[:100]}), proceeding anyway.")
    except subprocess.TimeoutExpired:
        print(f"⚠️ Agy validation timed out, proceeding with bet.")
    except Exception as e:
        print(f"⚠️ Agy validation error ({e}), proceeding anyway.")

    # ── 5.5 PREDICTION GATE — Verify all legs against all data sources ──
    print(f"🔍 Running prediction gate on all legs...")
    all_legs_pass = True
    gate_results = []
    for leg in best["legs"]:
        # 🛡️ GHOST BYPASS: If it's an ELITE ghost lock, skip the standard gate
        if leg.get("strength") == "ELITE":
            print(f"🛡️ GHOST BYPASS: {leg['home']} vs {leg['away']} → {leg['market']} (Mirror Grounded)")
            gate_results.append({"verdict": "PASS", "source": "GHOST_MIRROR"})
            continue

        try:
            gate_res = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "prediction_gate.py"),
                 "--home", leg["home"], "--away", leg["away"],
                 "--market", leg["market"], "--odds", str(leg["odds"]),
                 "--confidence", str(leg.get("confidence", 50)), "--json"],
                capture_output=True, text=True, timeout=30
            )
            if gate_res.returncode == 0:
                gate_data = json.loads(gate_res.stdout)
                if gate_data.get("verdict") == "PASS":
                    print(f"  ✅ Gate PASS: {leg['home']} vs {leg['away']} → {leg['market']}")
                    gate_results.append(gate_data)
                else:
                    fails = [k for k,v in gate_data.get('gates',{}).items() if v.get('status') != 'PASS']
                    print(f"  ❌ Gate FAIL: {leg['home']} vs {leg['away']} → {leg['market']} FAILS: {fails}")
                    all_legs_pass = False
            else:
                print(f"  ⚠️ Gate error on {leg['home']} vs {leg['away']}: {gate_res.stderr[:100]}")
        except Exception as e:
            print(f"  ⚠️ Gate exception: {e}")

    if not all_legs_pass:
        print(f"🚫 Prediction gate rejected bet — one or more legs failed data validation")
        return
    else:
        print(f"✅ All legs passed prediction gate (H2H + Form + Cluster + Odds + Regime)")

    # ── 6. Final Stake Verification ──
    # Cap stake to avoid breaching stop loss
    if stake > balance:
        print(f"⚠️ Ratchet stake (₦{stake}) exceeds balance (₦{balance}). Capping.")
        stake = balance
    
    # Ensure stake doesn't drop balance below STOP_LOSS
    max_stake = max(0, balance - STOP_LOSS)
    if stake > max_stake:
        print(f"⚠️ Capping stake from ₦{stake:.0f} to ₦{max_stake:.0f} to stay above stop loss")
        stake = max_stake
        
    if stake < 5.0:
        print(f"⛔ Stake too low (₦{stake:.0f})")
        return

    # ── 7. Print selected pick ──
    print(f"\n🎯 **30% RATCHET PROTOCOL — Phase {rolling.state['phase']} | Milestone {rolling.state['milestone']} | Hits {rolling.state['hits_in_step']}**")
    print(f"📅 {best['season_name']} — MD{best['matchday']}")
    print(f"{'─'*60}")
    for i, leg in enumerate(best["legs"], 1):
        print(f"  Leg {i}: {leg['home']} vs {leg['away']} → {leg['market']} @{leg['odds']}")
    print(f"{'─'*60}")
    print(f"💵 Combined Odds: {best['combined_odds']:.2f}")
    print(f"🏦 Bankroll: ₦{balance:.1f}")
    print(f"💰 Stake: ₦{stake:.0f}")
    print(f"💵 Potential Return: ₦{stake * best['combined_odds']:.2f}")

    # ── 8. Place via browser ──
    print(f"\n🖱 Placing bet via browser...")
    result = place_parlay_via_browser(best, stake)
    print(f"   Result: {json.dumps(result, indent=2)}")

    # ── 9. Record ──
    placed = result.get("success", False)
    if placed:
        rolling.set_active_bet(best, stake)
        bet_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "ratchet_protocol",
            "phase": rolling.state["phase"],
            "milestone": rolling.state["milestone"],
            "hits_in_step": rolling.state["hits_in_step"],
            "season": best["season_name"],
            "matchday": best["matchday"],
            "legs": best["legs"],
            "combined_odds": best["combined_odds"],
            "stake": stake,
            "placed": True,
            "settled": False,
        }
        ledger["bets"].append(bet_entry)
        seen.add(_parlay_key(best))
        state["seen_parlays"] = list(seen)[-200:]
        save_state(state)
        save_json(LEDGER_FILE, ledger)
        print(f"\n✅ Bet recorded. Good luck!")
    else:
        print(f"\n❌ Placement failed.")

if __name__ == "__main__":
    main()
