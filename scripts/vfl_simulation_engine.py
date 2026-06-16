#!/usr/bin/env python3
"""
vfl_simulation_engine.py — Standing simulation/paper-trading layer for Trillions Empire.
Replicates the real-money betting pipeline using virtual bankroll, custom simulation state,
and ledger files. Never touches real-money files.
"""

import json
import sys
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# Add current script directory to Python path to ensure easy imports
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.append(str(SCRIPTS_DIR))

# Import orchestrator logic
try:
    from auto_bet_orchestrator import (
        build_parlays,
        select_rolling_pick,
        _parlay_key,
        RollingCompoundManager,
        MIN_CONF,
        MIN_EV,
        BASE_DIR,
    )
except ImportError as e:
    print(f"ERROR: Failed to import from auto_bet_orchestrator: {e}", file=sys.stderr)
    sys.exit("NO_DATA")

# Custom state paths
SIM_STATE_FILE = BASE_DIR / "signals" / "simulation_state.json"
SIM_LEDGER_FILE = BASE_DIR / "signals" / "simulation_ledger.json"
SIM_PERF_FILE = BASE_DIR / "signals" / "simulation_performance.json"
RESULTS_DB = BASE_DIR / "databases" / "vfl_results.db"

DEFAULT_SIM_STATE = {
    "bankroll": 10000.0,
    "peak_bankroll": 10000.0,
    "max_drawdown": 0.0,
    "phase": 1,
    "milestone": 0,
    "hits_in_step": 0,
    "current_seed": 50.0,
    "current_stake": 50.0,
    "total_profit_banked": 0.0,
    "active_bet": None,
    "seen_parlays": [],
    "last_run": None
}

def load_json(path, default=None):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def load_predictions():
    p = load_json(BASE_DIR / "signals" / "live_test_predictions.json")
    if not p:
        p = load_json(BASE_DIR / "signals" / "vfl_llm_picks.json")
    return p

def update_performance_metrics(ledger, current_bankroll, state):
    """Calculate and update historical performance metrics."""
    bets = ledger.get("bets", [])
    placed_bets = [b for b in bets if b.get("placed", False)]
    settled_bets = [b for b in placed_bets if b.get("settled", False)]
    
    total_placed = len(placed_bets)
    total_settled = len(settled_bets)
    
    won_bets = [b for b in settled_bets if b.get("won", False)]
    lost_bets = [b for b in settled_bets if not b.get("won", False)]
    
    total_won = len(won_bets)
    total_lost = len(lost_bets)
    
    hit_rate = (total_won / total_settled * 100) if total_settled > 0 else 0.0
    
    # Hit rate by leg count
    by_leg = {}
    for leg_cnt in (1, 2, 3):
        leg_placed = [b for b in settled_bets if len(b.get("legs", [])) == leg_cnt]
        leg_won = [b for b in leg_placed if b.get("won", False)]
        l_p = len(leg_placed)
        l_w = len(leg_won)
        by_leg[str(leg_cnt)] = {
            "placed": l_p,
            "won": l_w,
            "hit_rate": round((l_w / l_p * 100), 2) if l_p > 0 else 0.0
        }
        
    # Streaks
    current_streak = 0
    longest_win_streak = 0
    current_loss_streak = 0
    longest_loss_streak = 0
    
    # We sort by placement/settlement timestamp
    sorted_bets = sorted(settled_bets, key=lambda x: x.get("timestamp", ""))
    
    temp_win = 0
    temp_loss = 0
    for b in sorted_bets:
        if b.get("won", False):
            temp_win += 1
            longest_win_streak = max(longest_win_streak, temp_win)
            temp_loss = 0
        else:
            temp_loss += 1
            longest_loss_streak = max(longest_loss_streak, temp_loss)
            temp_win = 0
            
    if sorted_bets:
        last_bet = sorted_bets[-1]
        if last_bet.get("won", False):
            current_streak = temp_win
        else:
            current_streak = -temp_loss
            
    # Avg Odds
    avg_odds = sum(b.get("combined_odds", 1.0) for b in placed_bets) / total_placed if total_placed > 0 else 0.0
    
    # ROI: (total return - total stake) / total stake
    total_stake = sum(b.get("stake", 0.0) for b in placed_bets)
    total_payout = sum((b.get("stake", 0.0) * b.get("combined_odds", 0.0)) for b in settled_bets if b.get("won", False))
    # For unsettled bets, we already paid the stake, so they are part of total_stake
    net_pnl = total_payout - total_stake
    roi = (net_pnl / total_stake * 100) if total_stake > 0 else 0.0
    
    # Max drawdown calculation
    # Track peak bankroll and drawdown on the fly
    peak_bankroll = state.get("peak_bankroll", 10000.0)
    if current_bankroll > peak_bankroll:
        peak_bankroll = current_bankroll
    
    drawdown = (peak_bankroll - current_bankroll) / peak_bankroll if peak_bankroll > 0 else 0.0
    max_drawdown = max(state.get("max_drawdown", 0.0), drawdown)
    
    # Update peak and max drawdown in state for persistence
    state["peak_bankroll"] = round(peak_bankroll, 2)
    state["max_drawdown"] = round(max_drawdown, 4)
    
    perf = {
        "virtual_bankroll": round(current_bankroll, 2),
        "total_profit_banked": round(state.get("total_profit_banked", 0.0), 2),
        "total_placed": total_placed,
        "total_settled": total_settled,
        "total_won": total_won,
        "total_lost": total_lost,
        "hit_rate": round(hit_rate, 2),
        "hit_rate_by_leg": by_leg,
        "streaks": {
            "current_streak": current_streak,
            "longest_win_streak": longest_win_streak,
            "longest_loss_streak": longest_loss_streak
        },
        "avg_odds": round(avg_odds, 2),
        "roi_pct": round(roi, 2),
        "net_pnl": round(net_pnl, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "last_update": datetime.now(timezone.utc).isoformat()
    }
    save_json(SIM_PERF_FILE, perf)

def check_leg_won(leg, row):
    """Standalone settlement check - mirrors RollingCompoundManager._check_leg_won."""
    market = leg.get("market", "")
    hg = row["home_goals"]
    ag = row["away_goals"]
    total = hg + ag
    if market == "Over 1.5 Goals": return total > 1
    if market == "Over 0.5 Goals": return total > 0
    if market == "Under 3.5 Goals": return total < 4
    if market == "Under 2.5 Goals": return total < 3
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

def check_and_settle_active_bet(state, ledger):
    """Check if active bet is settled in vfl_results.db, apply Ratchet Protocol."""
    active_bet = state.get("active_bet")
    if not active_bet:
        return "IDLE"

    if not RESULTS_DB.exists():
        print("⚠️ Results DB not found. Skipping settlement.")
        return "ERROR"

    all_settled = True
    all_won = True
    
    try:
        conn = sqlite3.connect(RESULTS_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        for leg in active_bet["legs"]:
            # Try event_id first
            row = None
            if leg.get("event_id"):
                cursor.execute("SELECT * FROM results WHERE event_id = ?", (leg["event_id"],))
                row = cursor.fetchone()
            
            # Fallback to Matchday + Teams + Season
            if not row:
                md_num = active_bet.get("matchday")
                season_name = active_bet.get("season_name")
                if md_num:
                    if season_name:
                        cursor.execute("""
                            SELECT * FROM results 
                            WHERE match_day = ? AND home_team = ? AND away_team = ? AND season_name = ?
                        """, (md_num, leg["home"], leg["away"], season_name))
                        row = cursor.fetchone()
                    
                    if not row and not season_name:
                        cursor.execute("""
                            SELECT * FROM results 
                            WHERE match_day = ? AND home_team = ? AND away_team = ?
                            ORDER BY captured_at DESC LIMIT 1
                        """, (md_num, leg["home"], leg["away"]))
                        row = cursor.fetchone()

            if not row:
                all_settled = False
                break
            
            # Standalone leg settlement check (mirrors RollingCompoundManager._check_leg_won logic)
            won = check_leg_won(leg, row)
            if not won:
                all_won = False
                break
        conn.close()
    except Exception as e:
        print(f"⚠️ Error querying database: {e}", file=sys.stderr)
        return "ERROR"

    if all_settled:
        stake = active_bet["stake"]
        odds = active_bet["combined_odds"]
        
        # Settle bet in ledger
        for ledger_bet in ledger.get("bets", []):
            if (ledger_bet.get("matchday") == active_bet["matchday"] and 
                ledger_bet.get("season") == active_bet.get("season_name") and 
                not ledger_bet.get("settled")):
                
                ledger_bet["settled"] = True
                ledger_bet["won"] = all_won
                ledger_bet["settled_at"] = datetime.now(timezone.utc).isoformat()
                break

        if all_won:
            payout = round(stake * odds, 2)
            state["bankroll"] = round(state["bankroll"] + payout, 2)
            state["hits_in_step"] += 1
            print(f"🎉 Simulated Parlay WON! Stake: ₦{stake} → Return: ₦{payout}")
            
            # Ratchet Protocol logic
            if state["hits_in_step"] == 2:
                if state["phase"] == 1:
                    # Phase 1 Complete (Capital Recovery): Skim ₦60
                    skim_amt = 60.0
                    state["total_profit_banked"] = round(state["total_profit_banked"] + skim_amt, 2)
                    working_cap = round(payout - skim_amt, 2)
                    print(f"💰 CAPITAL RECOVERY COMPLETE! Banking ₦{skim_amt} to Safe Vault.")
                    print(f"🔄 Moving to Phase 2, Milestone 1 with Working Capital: ₦{working_cap}")
                    
                    state["phase"] = 2
                    state["milestone"] = 1
                    state["hits_in_step"] = 0
                    state["current_stake"] = working_cap
                else:
                    m = state["milestone"]
                    if state["total_profit_banked"] + payout >= 10000.0:
                        state["total_profit_banked"] = round(state["total_profit_banked"] + payout, 2)
                        print(f"🏆 TARGET REACHED! ₦10,000+ earned! Resetting and locking ₦{payout}.")
                        # Reset
                        state["phase"] = 1
                        state["milestone"] = 0
                        state["hits_in_step"] = 0
                        state["current_stake"] = state["current_seed"]
                    else:
                        # Skim 30% into Safe Vault
                        skim = round(payout * 0.30, 2)
                        state["total_profit_banked"] = round(state["total_profit_banked"] + skim, 2)
                        working_cap = round(payout - skim, 2)
                        print(f"💰 Milestone {m} Complete! Skimming 30% (₦{skim}) to Safe Vault.")
                        print(f"🔄 Moving to Milestone {m+1} with Working Capital: ₦{working_cap}")
                        
                        state["milestone"] = m + 1
                        state["hits_in_step"] = 0
                        state["current_stake"] = working_cap
            else:
                # Won 1 parlay, need 1 more
                state["current_stake"] = payout
                print(f"📈 1 hit recorded for milestone. Capital is now ₦{payout}. Need 1 more win to skim.")
        else:
            print(f"❌ Simulated Parlay LOST. Resetting active capital to ₦{state['current_seed']}.")
            # Reset
            state["phase"] = 1
            state["milestone"] = 0
            state["hits_in_step"] = 0
            state["current_stake"] = state["current_seed"]

        state["active_bet"] = None
        save_json(SIM_STATE_FILE, state)
        save_json(SIM_LEDGER_FILE, ledger)
        update_performance_metrics(ledger, state["bankroll"], state)
        return "SETTLED"

    return "WAITING"

def main():
    # 1. Load or Initialize State and Ledger
    state = load_json(SIM_STATE_FILE, DEFAULT_SIM_STATE)
    ledger = load_json(SIM_LEDGER_FILE, {"bets": []})
    
    print("🤖 Running VFL Simulation Cycle...")
    
    # 2. Check and Settle Active Bet
    status = check_and_settle_active_bet(state, ledger)
    print(f"📊 Status: {status} | Bankroll: ₦{state['bankroll']:.2f} | Vault: ₦{state['total_profit_banked']:.2f}")
    print(f"   Ratchet Phase: {state['phase']} | Milestone: {state['milestone']} | Hits: {state['hits_in_step']} | Next Stake: ₦{state['current_stake']:.2f}")

    if state.get("active_bet"):
        active = state["active_bet"]
        print(f"⏳ Pending Settlement: MD{active['matchday']} | Stake: ₦{active['stake']} | Odds: @{active['combined_odds']:.2f}")
        return

    # 3. Load Predictions & Build Parlays
    predictions = load_predictions()
    if not predictions:
        print("⚠️ Predictions file unavailable (NO_DATA). Gracefully exiting.")
        sys.exit("NO_DATA")

    parlays = build_parlays(predictions)
    if not parlays:
        print("⏳ No qualifying parlays found. Skipping.")
        sys.exit("NO_DATA")

    # 4. Select Best Unseen Parlay
    seen_keys = set(state.get("seen_parlays", []))
    best = select_rolling_pick(parlays, seen_keys)
    if not best:
        print("⏳ No new qualifying unseen picks found. Skipping.")
        return

    # 5. Place Simulated Bet
    stake = state.get("current_stake", state["current_seed"])
    
    # Cap stake to current virtual bankroll
    if stake > state["bankroll"]:
        print(f"⚠️ Simulated stake (₦{stake}) exceeds virtual bankroll (₦{state['bankroll']}). Capping.")
        stake = state["bankroll"]

    if stake < 10.0:
        print(f"⛔ Virtual bankroll depleted or stake too low (₦{stake}). Cannot place bet.")
        return

    # Deduct stake from bankroll
    state["bankroll"] = round(state["bankroll"] - stake, 2)
    
    # Record active bet
    state["active_bet"] = {
        "season_name": best.get("season_name"),
        "matchday": best["matchday"],
        "legs": best["legs"],
        "combined_odds": best["combined_odds"],
        "stake": stake,
        "placed_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Log to ledger
    bet_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "simulated_ratchet",
        "phase": state["phase"],
        "milestone": state["milestone"],
        "hits_in_step": state["hits_in_step"],
        "season": best["season_name"],
        "matchday": best["matchday"],
        "legs": best["legs"],
        "combined_odds": best["combined_odds"],
        "stake": stake,
        "placed": True,
        "settled": False,
    }
    ledger["bets"].append(bet_entry)
    
    # Update seen parlays
    seen_keys.add(_parlay_key(best))
    state["seen_parlays"] = list(seen_keys)[-200:]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    
    save_json(SIM_STATE_FILE, state)
    save_json(SIM_LEDGER_FILE, ledger)
    update_performance_metrics(ledger, state["bankroll"], state)
    
    print(f"\n🎯 **Simulated Bet Placed!**")
    print(f"📅 MD {best['matchday']} | Combined Odds: {best['combined_odds']:.2f} | Stake: ₦{stake}")
    for i, leg in enumerate(best["legs"], 1):
        print(f"  Leg {i}: {leg['home']} vs {leg['away']} → {leg['market']} @{leg['odds']}")
    print(f"🏦 Remaining Bankroll: ₦{state['bankroll']:.2f}\n")

if __name__ == "__main__":
    main()
