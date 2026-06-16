#!/usr/bin/env python3
"""
vfl_simulation_report.py — Performance reporting generator for Trillions Empire.
Reads simulation ledger and performance, and outputs a highly polished Markdown report.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
SIM_STATE_FILE = BASE_DIR / "signals" / "simulation_state.json"
SIM_LEDGER_FILE = BASE_DIR / "signals" / "simulation_ledger.json"
SIM_PERF_FILE = BASE_DIR / "signals" / "simulation_performance.json"

def load_json(path):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def generate_report():
    perf = load_json(SIM_PERF_FILE)
    ledger = load_json(SIM_LEDGER_FILE)
    state = load_json(SIM_STATE_FILE)
    
    if not perf:
        print("⚠️ No simulation performance data found. Please run the simulation first.")
        sys.exit(1)
        
    bets = ledger.get("bets", [])
    placed_bets = [b for b in bets if b.get("placed", False)]
    settled_bets = [b for b in placed_bets if b.get("settled", False)]
    
    # Risk Metrics
    avg_stake = sum(b.get("stake", 0.0) for b in placed_bets) / len(placed_bets) if placed_bets else 0.0
    current_bankroll = state.get("bankroll", 10000.0)
    stake_to_bankroll_ratio = (avg_stake / current_bankroll * 100) if current_bankroll > 0 else 0.0
    
    # Avg profit per parlay
    total_net_pnl = perf.get("net_pnl", 0.0)
    total_settled = perf.get("total_settled", 0)
    avg_profit_per_parlay = total_net_pnl / total_settled if total_settled > 0 else 0.0
    
    # Icons for aesthetics
    status_icon = "🟢" if total_net_pnl >= 0 else "🔴"
    
    # Streaks formatting
    streaks = perf.get("streaks", {})
    curr_streak = streaks.get("current_streak", 0)
    streak_str = f"🔥 {curr_streak} Wins" if curr_streak > 0 else (f"❄️ {abs(curr_streak)} Losses" if curr_streak < 0 else "0")
    
    report = f"""# 📊 **TRILLIONS EMPIRE VFL SIMULATION REPORT**

### ⚡ **Simulation Live Dashboard**
| Metric | Value |
| :--- | :--- |
| **Virtual Bankroll** | ₦{current_bankroll:,.2f} |
| **Safe Vault (Profit Banked)** | ₦{perf.get('total_profit_banked', 0.0):,.2f} |
| **Total Parlays Placed** | {perf.get('total_placed', 0)} |
| **Total Settled** | {total_settled} ({perf.get('total_won', 0)}W - {perf.get('total_lost', 0)}L) |
| **Overall Hit Rate** | {perf.get('hit_rate', 0.0):.2f}% |
| **Total Net P&L** | {status_icon} ₦{total_net_pnl:+,.2f} |
| **ROI** | **{perf.get('roi_pct', 0.0):+.2f}%** |

---

### 📉 **Risk & Drawdown Metrics**
* **Average Stake:** ₦{avg_stake:,.2f}
* **Avg Stake-to-Bankroll Ratio:** {stake_to_bankroll_ratio:.2f}%
* **Average Profit Per Parlay:** ₦{avg_profit_per_parlay:+,.2f}
* **Max Historical Drawdown:** {perf.get('max_drawdown_pct', 0.0):.2f}%

---

### 🎯 **Streaks & Momentum**
* **Current Streak:** {streak_str}
* **Longest Winning Streak:** {streaks.get('longest_win_streak', 0)} consecutive wins
* **Longest Losing Streak:** {streaks.get('longest_loss_streak', 0)} consecutive losses
* **Average Odds:** @{perf.get('avg_odds', 0.0):.2f}

---

### 🧱 **Parlay Leg-Count Breakdown**
| Legs | Placed | Won | Hit Rate |
| :--- | :---: | :---: | :--- |
| **1-Leg (Singles)** | {perf.get('hit_rate_by_leg', {}).get('1', {}).get('placed', 0)} | {perf.get('hit_rate_by_leg', {}).get('1', {}).get('won', 0)} | {perf.get('hit_rate_by_leg', {}).get('1', {}).get('hit_rate', 0.0):.2f}% |
| **2-Leg Parlays** | {perf.get('hit_rate_by_leg', {}).get('2', {}).get('placed', 0)} | {perf.get('hit_rate_by_leg', {}).get('2', {}).get('won', 0)} | {perf.get('hit_rate_by_leg', {}).get('2', {}).get('hit_rate', 0.0):.2f}% |
| **3-Leg Parlays** | {perf.get('hit_rate_by_leg', {}).get('3', {}).get('placed', 0)} | {perf.get('hit_rate_by_leg', {}).get('3', {}).get('won', 0)} | {perf.get('hit_rate_by_leg', {}).get('3', {}).get('hit_rate', 0.0):.2f}% |

*Report generated at: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}*
"""
    print(report)

if __name__ == "__main__":
    generate_report()
