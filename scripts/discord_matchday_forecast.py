#!/usr/bin/env python3
"""Discord Matchday Forecast — Formats predictions for Discord/Slack via Hermes."""
import requests
import sys
import os
from datetime import datetime

# Add scripts to path for hermes
sys.path.insert(0, os.path.dirname(__file__))
from hermes_notifier import notify
from finite_state_filter import FiniteStateFilter

PREDICTOR_URL = "http://localhost:8002/predictions/latest"

def generate_forecast():
    try:
        resp = requests.get(PREDICTOR_URL, timeout=10)
        data = resp.json()
        
        matchdays = data.get("matchdays", [])
        if not matchdays:
            print("No matchdays found.")
            return

        from msport_api import get_current_match_day_info
        
        info = get_current_match_day_info()
        if not info:
            print("Could not fetch current match day info.")
            return
            
        current_md = int(info.get("matchDay", 0))
        status = info.get("status", "")
        # If the matchday hasn't started, target it. Otherwise, target the next upcoming one.
        target_md_num = current_md if status == "NOT_STARTED" else current_md + 1

        target_md = None
        for md in matchdays:
            if md.get("matchday") == target_md_num:
                target_md = md
                break
                
        if not target_md:
            # Fallback to the first available matchday in the list
            target_md = matchdays[0]
            
        md_num = target_md.get("matchday")
        season = target_md.get("season", "VFLM")
        fixtures = target_md.get("fixtures", [])

        fsf = FiniteStateFilter()

        lines = [
            f"🏆 **VFL MATCHDAY {md_num} FORECAST ({season})**",
            f"📅 *Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
            ""
        ]

        # 1. Collect Locks
        locks = []
        market_map = {
            "Over 1.5 Goals": "O1.5",
            "Over 2.5 Goals": "O2.5",
            "Goal-Goal (BTTS Yes)": "GG",
            "Under 3.5 Goals": "U3.5",
            "No Goal (BTTS No)": "NG",
            "Under 2.5 Goals": "U2.5"
        }

        for f in fixtures:
            home = f.get("home")
            away = f.get("away")
            for p in f.get("predictions", []):
                market = p.get("market")
                odds = p.get("odds")
                conf = p.get("confidence")
                strength = p.get("strength")
                
                # Check trap status
                std_market = market_map.get(market)
                if std_market:
                    gate_res = fsf.check_pair(home, away, std_market)
                    if gate_res['verdict'] == 'FAIL':
                        continue # Skip traps from Locks section
                
                if strength == "STRONG" and conf >= 80:
                    locks.append((home, away, market, odds, conf))

        if locks:
            lines.append("🔥 **HIGH-CONFIDENCE LOCKS**")
            for home, away, market, odds, conf in locks:
                lines.append(f"• 🟢 **{home} vs {away}** ➔ **{market}** @{odds} (Conf: {conf}%)")
            lines.append("")

        # 2. Detail Forecast for All Fixtures
        lines.append("📊 **ALL FIXTURE FORECASTS**")
        for f in fixtures:
            home = f.get("home")
            away = f.get("away")
            score = f.get("predicted_score", "?-?")
            pick = f.get("pick_1x2", "?")
            
            lines.append(f"• ⚽ **{home} vs {away}**")
            lines.append(f"    *Predicted Score:* `{score}` | *Primary 1X2:* **{pick}**")
            
            # Group predictions for this fixture
            preds = f.get("predictions", [])
            valid_preds = []
            trap_preds = []
            
            for p in preds:
                market = p.get("market")
                odds = p.get("odds")
                conf = p.get("confidence")
                
                std_market = market_map.get(market)
                if std_market:
                    gate_res = fsf.check_pair(home, away, std_market)
                    if gate_res['verdict'] == 'FAIL':
                        trap_preds.append((market, odds, conf, gate_res['reason']))
                    else:
                        valid_preds.append((market, odds, conf))
                else:
                    valid_preds.append((market, odds, conf))
            
            # Sort valid predictions by confidence desc
            valid_preds.sort(key=lambda x: x[2], reverse=True)
            
            if valid_preds:
                valid_str = ", ".join([f"**{m}** @{o} ({c}%)" for m, o, c in valid_preds[:3]])
                lines.append(f"    *Qualifying Bets:* {valid_str}")
            
            if trap_preds:
                for m, o, c, reason in trap_preds:
                    lines.append(f"    *⚠️ Trap Warning:* **{m}** @{o} ({c}%) ➔ `{reason}`")
            
            lines.append("")

        lines.append("🚀 *Powered by Antigravity Sequence Oracle*")
        
        full_message = "\n".join(lines)
        notify(full_message)
        print("Forecast sent to Hermes.")

    except Exception as e:
        print(f"Error generating forecast: {e}")

if __name__ == "__main__":
    generate_forecast()
