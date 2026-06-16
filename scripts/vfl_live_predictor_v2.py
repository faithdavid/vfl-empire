#!/usr/bin/env python3
"""
vfl_live_predictor_v2.py — VFL Live Matchday Predictor (Gating V2)
===================================================================
Fetches upcoming VFL matchday fixture data, runs Gating V2 (Robust Bayesian),
scores markets, and outputs a rich Markdown prediction report.

Usage:
    python vfl_live_predictor_v2.py
    python vfl_live_predictor_v2.py --dry-run
    python vfl_live_predictor_v2.py --force
"""

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add paths
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, "/home/ubuntu/faith-workspace/vfl-empire/services")

from common.db_manager import get_db
from prediction_gate_v2 import RobustGatingEngine
from odds_cluster_classifier import classify_match

STATE_FILE = BASE_DIR / "signals" / "live_predictor_v2_state.json"
LOG_FILE = "/tmp/vfl_live_predictor_v2.log"

logger = logging.getLogger("vfl_live_predictor_v2")

def setup_logging(debug: bool = False):
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG if debug else logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

DEFAULT_STATE = {
    "last_season_id": None,
    "last_match_day": None,
    "last_processed_at": None,
}

def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            for k, v in DEFAULT_STATE.items():
                if k not in data:
                    data[k] = v
            return data
        except Exception:
            pass
    return dict(DEFAULT_STATE)

def save_state(state: Dict[str, Any]) -> None:
    state["last_processed_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)

def log_prediction_to_db(entry: Dict[str, Any], season_id: str, match_day: int):
    sql = """
        INSERT INTO vfl_predictions (
            iso_time, season, match_day, home_team, away_team, 
            prediction, confidence, odds, engine, metadata
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    try:
        with get_db() as cur:
            cur.execute(sql, (
                datetime.now(timezone.utc).isoformat(),
                season_id,
                match_day,
                entry.get("home"),
                entry.get("away"),
                entry.get("market"),
                int(entry.get("probability", 0.5) * 100),
                entry.get("odds"),
                "live_predictor_v2",
                json.dumps({
                    "edge": entry.get("edge"),
                    "stake_fraction": entry.get("recommended_stake"),
                    "status": "LOGGED"
                })
            ))
    except Exception as e:
        logger.error("Failed to log prediction to DB: %s", e)

# Team Name Normalization Map
from vfl_live_predictor import TEAM_NAME_MAP, TEAM_ALIASES, normalize_team, extract_odds

ALL_MARKETS = [
    ("O1.5", "Over 1.5 Goals"),
    ("O2.5", "Over 2.5 Goals"),
    ("U3.5", "Under 3.5 Goals"),
    ("GG", "Goal-Goal (BTTS Yes)"),
]

def analyze_fixture_v2(home: str, away: str, odds_dict: Dict[str, Optional[float]], engine: RobustGatingEngine, match_day: Optional[int] = None) -> Dict[str, Any]:
    result = {
        "home": home,
        "away": away,
        "odds": odds_dict,
        "markets": [],
        "best_pick": None,
    }
    
    # Classify Cluster
    c_res = classify_match(odds_dict.get("o15"), odds_dict.get("o25"), odds_dict.get("gg"), odds_dict.get("u35"))
    result["cluster"] = c_res
    
    scored_markets = []
    for mkt_key, mkt_display in ALL_MARKETS:
        odds_val = odds_dict.get(mkt_key.lower().replace('.', ''))
        if not odds_val or odds_val <= 1.0:
            continue
            
        gate_res = engine.evaluate_bet(
            home_team=home,
            away_team=away,
            market=mkt_key,
            odds=odds_val,
            o15=odds_dict.get("o15"),
            o25=odds_dict.get("o25"),
            gg=odds_dict.get("gg"),
            u35=odds_dict.get("u35"),
            match_day=match_day
        )
        
        is_lock = gate_res.get("is_deterministic_lock", False)
        # Locks bypass the 6% edge requirement — they always qualify
        is_passed = gate_res.get("verdict") == "PASS" and (
            is_lock or gate_res.get("edge", 0.0) >= 0.06
        )
        
        scored_markets.append({
            "market": mkt_key,
            "display": mkt_display,
            "odds": odds_val,
            "probability": gate_res.get("probability_ensemble", {}).get("combined", 0.5),
            "edge": gate_res.get("edge", 0.0),
            "recommended_stake": gate_res.get("recommended_stake_fraction", 0.0),
            "verdict": "PASS" if is_passed else "FAIL",
            "reasons": gate_res.get("fail_reasons", []),
            "is_lock": is_lock,
            "lock_n": gate_res.get("lock_n", 0),
        })
        
    result["markets"] = scored_markets
    
    # Pick the best bet — prioritize locks, then highest edge
    passed = [m for m in scored_markets if m["verdict"] == "PASS"]
    if passed:
        # Locks first, then highest edge
        locks_first = sorted(passed, key=lambda x: (x["is_lock"], x["edge"]), reverse=True)
        result["best_pick"] = locks_first[0]
        
    return result

def build_v2_report(season_name: str, match_day: int, match_day_start: int, fixture_analyses: List[Dict[str, Any]]) -> str:
    lines = []
    lines.append(f"## 👑 VFL Live Predictor V2 (Robust Bayesian) — {season_name}")
    lines.append(f"**Matchday {match_day}** — {datetime.fromtimestamp(match_day_start/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(f"**Fixtures Analyzed: {len(fixture_analyses)}**")
    lines.append("")
    
    for fa in fixture_analyses:
        home, away = fa["home"], fa["away"]
        lines.append(f"### {home} vs {away}")
        
        # Display Cluster
        c = fa.get("cluster", {})
        if c and c.get("cluster_id", -1) >= 0:
            lines.append(f"📊 *Odds Cluster C{c['cluster_id']}:* {c.get('label')}")
            
        scored = fa.get("markets", [])
        if scored:
            for m in scored:
                if m["verdict"] == "PASS":
                    if m.get("is_lock"):
                        icon = "🔒"
                        lock_label = f" 🔒 DETERMINISTIC LOCK (n={m['lock_n']})"
                    else:
                        icon = "✅"
                        lock_label = ""
                else:
                    icon = "❌"
                    lock_label = ""
                lines.append(
                    f"  {icon} {m['display']} @{m['odds']:.2f} "
                    f"— prob {m['probability']*100:.1f}%, edge {m['edge']*100:+.1f}%, stake {m['recommended_stake']*100:.1f}%{lock_label}"
                )
        else:
            lines.append("  _No qualifying picks_")
            
        # 1X2 odds
        od = fa.get("odds", {})
        hw = f"{od.get('home_win'):.2f}" if od.get("home_win") else "—"
        dw = f"{od.get('draw'):.2f}" if od.get("draw") else "—"
        aw = f"{od.get('away_win'):.2f}" if od.get("away_win") else "—"
        lines.append(f"  🏆 1X2: {hw} / {dw} / {aw}")
        lines.append("")
        
    # Find overall best pick for the matchday — locks get priority
    best_picks = []
    for fa in fixture_analyses:
        if fa.get("best_pick"):
            best_picks.append({**fa["best_pick"], "fixture": f"{fa['home']} vs {fa['away']}"})
            
    if best_picks:
        # Sort: locks first, then highest edge
        best_picks.sort(key=lambda x: (x.get("is_lock", False), x["edge"]), reverse=True)
        top = best_picks[0]
        lock_badge = " 🔒 DETERMINISTIC LOCK" if top.get("is_lock") else ""
        lines.append("---")
        lines.append("## ⭐ Top Bayesian Pick Recommendation")
        lines.append(f"**{top['fixture']} → {top['display']} @{top['odds']:.2f}{lock_badge}**")
        lines.append(f"Probability: {top['probability']*100:.1f}% | Value Edge: {top['edge']*100:+.1f}% | Stake Size: {top['recommended_stake']*100:.1f}%")
        lines.append("")
        
    lines.append("---")
    lines.append(f"_Generated by Gating V2 at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    lines.append("")
    return "\n".join(lines)

def run_predictor_v2(dry_run: bool = False, force: bool = False) -> bool:
    try:
        from msport_api import get_current_match_day_info, get_event_list
        info = get_current_match_day_info()
        if not info:
            logger.warning("Could not fetch current match day info from MSport API")
            return False
            
        season_id = str(info.get("seasonId", ""))
        season_name = str(info.get("seasonName", ""))
        match_day = int(info.get("matchDay", 0))
        match_day_start = info.get("matchDayStartTime", 0)
    except Exception as e:
        logger.error("Failed to fetch match day info: %s", e)
        return False
        
    state = load_state()
    if not force and state.get("last_season_id") == season_id and state.get("last_match_day") == match_day:
        logger.info("Matchday already processed. Exiting.")
        return True
        
    try:
        match_days = get_event_list()
        if not match_days:
            return False
    except Exception as e:
        logger.error("Failed to fetch event list: %s", e)
        return False
        
    from msport_api import find_upcoming_match_day
    target_md = find_upcoming_match_day(match_days, min_seconds=30)
            
    if not target_md:
        logger.warning("No upcoming matchday found.")
        return False
        
    match_day = int(target_md.get("matchDay") or target_md.get("matchday") or match_day)
    match_day_start = target_md.get("matchDayStartTime", match_day_start)
        
    events = target_md.get("events") or []
    logger.info("Processing matchday %d with Gating V2...", match_day)
    
    engine = RobustGatingEngine()
    fixture_analyses = []
    
    for event in events:
        home_raw = event.get("homeTeam") or event.get("homeName") or ""
        away_raw = event.get("awayTeam") or event.get("awayName") or ""
        home = normalize_team(home_raw) or home_raw
        away = normalize_team(away_raw) or away_raw
        
        if not home or not away:
            continue
            
        odds_dict = extract_odds(event)
        # Pass match_day so the engine can check deterministic locks
        fa = analyze_fixture_v2(home, away, odds_dict, engine, match_day=match_day)
        fixture_analyses.append(fa)
        
        # Log best pick to database if valid
        best = fa.get("best_pick")
        if best and not dry_run:
            log_prediction_to_db(best, season_id, match_day)
            
    # Output report
    report = build_v2_report(season_name, match_day, match_day_start, fixture_analyses)
    print(report)
    
    if not dry_run:
        state["last_season_id"] = season_id
        state["last_match_day"] = match_day
        save_state(state)
        
    return True

def main():
    parser = argparse.ArgumentParser(description="VFL Live Predictor V2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    
    setup_logging(args.debug)
    run_predictor_v2(dry_run=args.dry_run, force=args.force)

if __name__ == "__main__":
    main()
