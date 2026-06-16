#!/usr/bin/env python3
"""
vfl_live_predictor.py — VFL Live Matchday Predictor
=====================================================
Fetches upcoming VFL matchday fixture data from MSport API, runs the full
prediction gate pipeline (H2H, cluster, finite-state, odds reasonableness,
regime), and outputs a structured Markdown prediction report (for Telegram).

Flow:
  1. get_current_match_day_info() → seasonId, matchDay, seasonName, matchDayStartTime
  2. Compare with last-processed state (signals/live_predictor_state.json)
  3. get_event_list() → list of matchDay dicts with events & markets
  4. For each event: extract odds (O1.5, O2.5, U2.5, U3.5, GG, NG, 1X2)
  5. For each market: run prediction_gate.run_all_gates()
  6. Apply odds cluster classifier & finite state filter
  7. Score markets, pick best per fixture
  8. Output Markdown report to stdout

Usage:
    python vfl_live_predictor.py
    python vfl_live_predictor.py --dry-run
    python vfl_live_predictor.py --force
    python vfl_live_predictor.py --debug

Author: VFL Engineering Team
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

# ──────────────────────────────────────────────────────────────────────
# PATHS (must be before services/common imports)
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
SCRIPTS_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/scripts")
SERVICES_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/services")

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SERVICES_DIR))

from common.db_manager import get_db  # noqa: E402
from common.deep_goals_predictor import (  # noqa: E402
    format_scorelines_short,
    predict_from_odds_dict,
)


# ──────────────────────────────────────────────────────────────────────
# PATHS (continued)
# ──────────────────────────────────────────────────────────────────────

STATE_FILE = BASE_DIR / "signals" / "live_predictor_state.json"
LOG_FILE = "/tmp/vfl_live_predictor.log"

# ──────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────
logger = logging.getLogger("vfl_live_predictor")


def setup_logging(debug: bool = False):
    """Configure file + stdout logging."""
    logger.setLevel(logging.DEBUG if debug else logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG if debug else logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)


# ──────────────────────────────────────────────────────────────────────
# STATE MANAGEMENT
# ──────────────────────────────────────────────────────────────────────
DEFAULT_STATE: Dict[str, Any] = {
    "last_season_id": None,
    "last_match_day": None,
    "last_processed_at": None,
    "processed_fixture_keys": [],
}


def load_state() -> Dict[str, Any]:
    """Load last-processed state from STATE_FILE."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            for k, v in DEFAULT_STATE.items():
                if k not in data:
                    data[k] = v
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not load state file: %s. Starting fresh.", e)
    return dict(DEFAULT_STATE)


def save_state(state: Dict[str, Any]) -> None:
    """Persist state to STATE_FILE."""
    state["last_processed_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)
    logger.debug("State saved to %s", STATE_FILE)


def write_predictions_latest(season_name: str, season_id: str, match_day: int, fixture_analyses: list):
    """Write latest predictions to the signals directory in the format expected by the API server."""
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline": "live_predictor_v2_deep_goals",
        "matchdays": [
            {
                "season": season_name,
                "season_id": season_id,
                "matchday": match_day,
                "fixtures": fixture_analyses
            }
        ]
    }
    
    # Save to the signals directory
    signals_path = BASE_DIR / "signals" / "predictions_latest.json"
    signals_path.parent.mkdir(parents=True, exist_ok=True)
    with open(signals_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
        
    # Also save to the local script directory
    local_path = SCRIPTS_DIR / "predictions_latest.json"
    with open(local_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
        
    logger.info("Saved latest predictions to %s and %s", signals_path, local_path)


# ──────────────────────────────────────────────────────────────────────
# DB HELPERS
# ──────────────────────────────────────────────────────────────────────
def log_prediction_to_db(entry: Dict[str, Any]):
    """Log prediction result to PostgreSQL vfl_predictions table."""
    sql = """
        INSERT INTO vfl_predictions (
            iso_time, season, match_day, home_team, away_team, 
            prediction, confidence, odds, engine, metadata
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    try:
        with get_db() as cur:
            cur.execute(sql, (
                entry.get("_logged_at"),
                entry.get("season_id"),
                entry.get("match_day"),
                entry.get("home"),
                entry.get("away"),
                entry.get("prediction"),
                entry.get("confidence"),
                json.dumps(entry.get("odds", {})),
                "live_predictor_v1",
                json.dumps({"status": "LOGGED"})
            ))
        logger.info("Prediction logged to Postgres: %s vs %s", entry.get("home"), entry.get("away"))
    except Exception as e:
        logger.error("Failed to log prediction to DB: %s", e)

# ──────────────────────────────────────────────────────────────────────
# TEAM NAME NORMALISATION
# ──────────────────────────────────────────────────────────────────────
TEAM_NAME_MAP = {
    "Manchester Red": "Manchester Red",
    "Manchester Blue": "Manchester Blue",
    "London Guns": "London Guns",
    "Chelsea": "Chelsea",
    "Liverpool": "Liverpool",
    "Aston Villa": "Aston Villa",
    "Tottenham": "Tottenham",
    "Everton": "Everton",
    "Wolverhampton": "Wolverhampton",
    "Newcastle": "Newcastle",
    "Leeds": "Leeds",
    "Fulham": "Fulham",
    "West Ham": "West Ham",
    "Bournemouth": "Bournemouth",
    "Brighton": "Brighton",
    "Crystal Palace": "Crystal Palace",
}

TEAM_ALIASES = {}
for k, v in TEAM_NAME_MAP.items():
    TEAM_ALIASES[k.lower()] = v
TEAM_ALIASES.update({
    "arsenal": "London Guns",
    "man city": "Manchester Blue",
    "manchester city": "Manchester Blue",
    "man united": "Manchester Red",
    "manchester united": "Manchester Red",
    "spurs": "Tottenham",
    "wolves": "Wolverhampton",
    "toon": "Newcastle",
    "magpies": "Newcastle",
    "hammers": "West Ham",
    "villans": "Aston Villa",
    "reds": "Liverpool",
    "blues": "Chelsea",
    "eagles": "Crystal Palace",
    "seagulls": "Brighton",
    "cherries": "Bournemouth",
    "whites": "Leeds",
    "cottagers": "Fulham",
    "toffees": "Everton",
    "gunners": "London Guns",
})


def normalize_team(name: str) -> Optional[str]:
    """Normalise a team name to the canonical form used across the codebase."""
    if not name:
        return None
    clean = name.strip()
    if clean in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[clean]
    low = clean.lower()
    if low in TEAM_ALIASES:
        return TEAM_ALIASES[low]
    for alias, canonical in TEAM_ALIASES.items():
        if low in alias or alias in low:
            return canonical
    try:
        from prediction_gate import validate_team
        validated = validate_team(clean)
        if validated:
            return validated
    except Exception:
        pass
    return clean  # fallback


# ──────────────────────────────────────────────────────────────────────
# ODDS EXTRACTION (mirrors vfl_rapid_daemon.py extract_odds)
# ──────────────────────────────────────────────────────────────────────
def extract_odds(event: dict) -> Dict[str, Optional[float]]:
    """Extract all relevant odds from an MSport event's markets.

    Returns dict with keys: o15, o25, u25, u35, gg, ng, dnb_home,
    plus 1X2 odds (home, draw, away).
    """
    odds: Dict[str, Optional[float]] = {
        "o15": None, "o25": None, "u25": None,
        "u35": None, "gg": None, "ng": None,
        "dnb_home": None,
        "home_win": None, "draw": None, "away_win": None,
    }
    markets = event.get("markets") or []

    for mk in markets:
        name = mk.get("name") or ""
        spec = (mk.get("specifiers") or "").strip()
        outcomes = mk.get("outcomes") or []

        for o in outcomes:
            desc = (o.get("description") or o.get("name") or "").strip()
            raw_val = o.get("odds") or o.get("price")
            if raw_val is None:
                continue
            try:
                val = float(raw_val)
            except (ValueError, TypeError):
                continue
            if val <= 1.0:
                continue

            if name == "Over/Under":
                if spec == "total=1.5":
                    if desc == "Over 1.5":
                        odds["o15"] = val
                elif spec == "total=2.5":
                    if desc == "Over 2.5":
                        odds["o25"] = val
                    elif desc == "Under 2.5":
                        odds["u25"] = val
                elif spec == "total=3.5":
                    if desc == "Under 3.5":
                        odds["u35"] = val
            elif name == "GG/NG":
                if desc == "Yes":
                    odds["gg"] = val
                elif desc == "No":
                    odds["ng"] = val
            elif name == "DNB":
                if desc == "Home" or o.get("id") in (4, "4"):
                    odds["dnb_home"] = val
            elif (
                mk.get("id") == 1
                or name.lower() in ("1x2", "match result", "full time result")
            ):
                dlow = desc.lower()
                if dlow == "home":
                    odds["home_win"] = val
                elif dlow == "draw":
                    odds["draw"] = val
                elif dlow == "away":
                    odds["away_win"] = val

    return odds


# ──────────────────────────────────────────────────────────────────────
# MARKETS WE SCORE
# ──────────────────────────────────────────────────────────────────────
ALL_MARKETS: List[Tuple[str, str, str]] = [
    ("O1.5", "Over 1.5 Goals", "o15"),
    ("O2.5", "Over 2.5 Goals", "o25"),
    ("U2.5", "Under 2.5 Goals", "u25"),
    ("U3.5", "Under 3.5 Goals", "u35"),
    ("GG", "Goal-Goal (BTTS Yes)", "gg"),
    ("NG", "No Goal (BTTS No)", "ng"),
]

# ──────────────────────────────────────────────────────────────────────
# FIXTURE ANALYSIS
# ──────────────────────────────────────────────────────────────────────
def analyze_fixture(
    home: str,
    away: str,
    odds_dict: Dict[str, Optional[float]],
    event_markets: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Run full analysis on a single fixture.

    Returns dict with:
      - home, away, odds
      - markets: list of scored market dicts
      - best_pick: the top-scoring market (or None)
      - cluster: odds cluster classification result
      - finite_state: finite state filter result
      - gate_results: per-market run_all_gates results
    """
    result: Dict[str, Any] = {
        "home": home,
        "away": away,
        "odds": odds_dict,
        "cluster": None,
        "finite_state": None,
        "markets": [],
        "best_pick": None,
        "gate_results": {},
        "deep_goals": None,
    }

    # ── 0. Deep goals + scorelines (O/U CDF, CS, H2H) ─────────────────
    try:
        result["deep_goals"] = predict_from_odds_dict(
            home, away, odds_dict, markets=event_markets
        )
    except Exception as e:
        logger.warning("deep_goals predict failed %s vs %s: %s", home, away, e)
        result["deep_goals"] = None

    # ── 1. Finite State Space filter (trap detection) ────────────────
    try:
        from finite_state_filter import FiniteStateFilter
        fsf = FiniteStateFilter()
        fs_result = fsf.check_pair(home, away, "O1.5")
        result["finite_state"] = fs_result
    except Exception as e:
        result["finite_state"] = {"verdict": "PASS", "details": f"Gate error: {e}"}
        logger.debug("Finite state check skipped: %s", e)

    # ── 2. Odds Cluster Classification ──────────────────────────────
    try:
        from odds_cluster_classifier import classify_match
        o15 = odds_dict.get("o15")
        o25 = odds_dict.get("o25")
        gg = odds_dict.get("gg")
        u35 = odds_dict.get("u35")
        if all(x is not None and x > 1.0 for x in [o15, o25, gg, u35]):
            cluster_result = classify_match(o15, o25, gg, u35)
            result["cluster"] = cluster_result
        else:
            result["cluster"] = {
                "cluster_id": -1,
                "error": "Insufficient odds for classification",
            }
    except Exception as e:
        result["cluster"] = {"cluster_id": -1, "error": str(e)}

    # ── 3. Score each market ──────────────────────────────────────────
    markets_scored = []
    for mkt_key, mkt_display, odds_key in ALL_MARKETS:
        mkt_odds = odds_dict.get(odds_key)

        if mkt_odds is None or mkt_odds <= 1.0:
            markets_scored.append({
                "market": mkt_key,
                "display": mkt_display,
                "odds": mkt_odds,
                "gate_verdict": None,
                "confidence": 0.0,
                "hit_rate": 0.0,
                "status": "NO_ODDS",
            })
            continue

        # Run prediction gate
        gate_result = run_gate_for_market(
            home, away, mkt_key, mkt_odds, odds_dict
        )
        result["gate_results"][mkt_key] = gate_result

        verdict = gate_result.get("verdict", "FAIL")
        h2h = gate_result.get("gates", {}).get("h2h", {})

        # Compute confidence & hit rate from H2H
        hit_rate = _get_h2h_hit_rate(h2h, mkt_key)
        confidence = _compute_confidence(h2h, mkt_key)

        markets_scored.append({
            "market": mkt_key,
            "display": mkt_display,
            "odds": mkt_odds,
            "gate_verdict": verdict,
            "confidence": confidence,
            "hit_rate": hit_rate,
            "status": h2h.get("status", "ERROR"),
            "n_matches": h2h.get("n_matches", 0),
            "gate_result": gate_result,
        })

    result["markets"] = markets_scored

    # ── 4. Pick best ──────────────────────────────────────────────────
    scored = [m for m in markets_scored if m.get("confidence", 0) > 0 and m.get("gate_verdict") == "PASS"]
    scored.sort(key=lambda m: m.get("confidence", 0), reverse=True)
    if scored:
        result["best_pick"] = scored[0]

    return result


def run_gate_for_market(
    home: str,
    away: str,
    market_key: str,
    odds: float,
    odds_dict: Dict[str, Optional[float]],
) -> Dict[str, Any]:
    """Run prediction_gate.run_all_gates for a single market."""
    try:
        from prediction_gate import run_all_gates
        return run_all_gates(
            home_team=home,
            away_team=away,
            market=market_key,
            odds=odds,
            confidence=None,
            o15=odds_dict.get("o15"),
            o25=odds_dict.get("o25"),
            gg=odds_dict.get("gg"),
            u35=odds_dict.get("u35"),
        )
    except Exception as e:
        logger.error("Gate error for %s vs %s %s: %s", home, away, market_key, e)
        return {
            "verdict": "ERROR",
            "error": str(e),
            "gates_passed": 0,
            "gates_failed": 0,
            "gates_total": 5,
        }


def _get_h2h_hit_rate(h2h_result: dict, market_key: str) -> float:
    """Extract relevant hit rate from H2H result based on market key."""
    if not h2h_result:
        return 0.0
    if market_key == "O1.5":
        return h2h_result.get("o1_5_rate", 0) / 100.0
    elif market_key == "O2.5":
        return h2h_result.get("o2_5_rate", 0) / 100.0
    elif market_key == "U2.5":
        u2_5 = 100.0 - h2h_result.get("o2_5_rate", 100)
        return u2_5 / 100.0
    elif market_key == "U3.5":
        avg = h2h_result.get("avg_total_goals", 0)
        if avg is None:
            return 0.0
        if avg <= 2.0:
            return 0.85
        elif avg <= 2.5:
            return 0.75
        elif avg <= 3.0:
            return 0.60
        else:
            return 0.40
    elif market_key == "GG":
        return h2h_result.get("gg_rate", 0) / 100.0
    elif market_key == "NG":
        ng = 100.0 - h2h_result.get("gg_rate", 100)
        return ng / 100.0
    return 0.0


def _compute_confidence(h2h_result: dict, market_key: str) -> float:
    """Compute confidence score (0-100) for a market based on H2H data."""
    if not h2h_result:
        return 0.0
    status = h2h_result.get("status", "INSUFFICIENT_DATA")
    n = h2h_result.get("n_matches", 0)

    if status in ("FAIL", "INSUFFICIENT_DATA") or n < 5:
        return 0.0
    if status != "PASS":
        return 0.0

    sample_conf = min(n / 20.0, 1.0) * 30
    hit_rate = _get_h2h_hit_rate(h2h_result, market_key)
    hit_conf = hit_rate * 70
    return min(sample_conf + hit_conf, 100.0)


# ──────────────────────────────────────────────────────────────────────
# PREDICTION REPORT
# ──────────────────────────────────────────────────────────────────────
def format_timestamp(ts_ms: Optional[int]) -> str:
    """Format a millisecond epoch timestamp to 'YYYY-MM-DD HH:MM UTC'."""
    if not ts_ms:
        return "Unknown"
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, OSError):
        return "Unknown"


def format_odds(val: Optional[float]) -> str:
    """Format odds value for display."""
    if val is None or val <= 0:
        return "—"
    return f"{val:.2f}"


def build_report(
    season_name: str,
    match_day: int,
    match_day_start_time: int,
    season_id: str,
    fixture_analyses: List[Dict[str, Any]],
    gates_passed_total: int,
    gates_failed_total: int,
    fixtures_total: int,
    top_pick: Optional[Dict[str, Any]],
) -> str:
    """Build a structured Markdown prediction report."""
    lines: List[str] = []

    lines.append(f"## 👑 VFL Live Predictor — {season_name}")
    lines.append(f"**Matchday {match_day}** — {format_timestamp(match_day_start_time)}")
    lines.append("")

    if not fixture_analyses:
        lines.append("_No fixtures available for analysis._")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"**Fixtures Analyzed: {fixtures_total}**")
    lines.append("")

    for fa in fixture_analyses:
        home = fa.get("home", "?")
        away = fa.get("away", "?")
        best = fa.get("best_pick")
        cluster = fa.get("cluster", {})
        fs = fa.get("finite_state", {})

        lines.append(f"### {home} vs {away}")

        dg = fa.get("deep_goals") or {}
        if dg:
            et = dg.get("E_total_blend")
            o25 = dg.get("o25_lean", "—")
            mood = dg.get("scoring_mood", "—")
            sl = format_scorelines_short(dg.get("top_scorelines") or [])
            lines.append(
                f"🎯 **E[goals]={et}** | {o25} | mood *{mood}*"
            )
            lines.append(f"📋 **Top scorelines:** {sl}")
            if dg.get("E_total_h2h") is not None:
                lines.append(f"↔️ H2H avg total: {dg['E_total_h2h']}")

        # Finite state
        fs_verdict = fs.get("verdict", "PASS")
        if fs_verdict == "FAIL":
            lines.append(f"🚫 *Trap:* {fs.get('reason', 'Unknown trap')}")
        else:
            lines.append(f"✅ *Passes finite-state filter*")

        # Cluster info
        if cluster and cluster.get("cluster_id", -1) >= 0:
            cid = cluster["cluster_id"]
            rec = cluster.get("rec_bet", "?")
            hit = cluster.get("hit_rate", 0)
            label = cluster.get("label", "")
            lines.append(f"📊 *Odds Cluster C{cid}:* {label}")
        elif cluster:
            lines.append(f"📊 *Odds Cluster:* Not classified ({cluster.get('error', 'N/A')})")
        else:
            lines.append(f"📊 *Odds Cluster:* N/A")

        # Market scores
        scored = [m for m in fa.get("markets", []) if m.get("confidence", 0) > 0]
        scored.sort(key=lambda m: m.get("confidence", 0), reverse=True)

        if scored:
            for m in scored:
                icon = "✅" if m.get("gate_verdict") == "PASS" else "❌"
                conf = m.get("confidence", 0)
                odds = m.get("odds", 0)
                hit = m.get("hit_rate", 0)
                gate_v = m.get("gate_verdict", "?")
                lines.append(
                    f"  {icon} {m['display']} @{format_odds(odds)} "
                    f"— conf {conf:.0f}%, hit {hit*100:.0f}%, gate={gate_v}"
                )
        else:
            lines.append("  _No qualifying picks_")

        # 1X2 odds
        odds_dict = fa.get("odds", {})
        hw = format_odds(odds_dict.get("home_win"))
        draw = format_odds(odds_dict.get("draw"))
        aw = format_odds(odds_dict.get("away_win"))
        lines.append(f"  🏆 1X2: {hw} / {draw} / {aw}")

        lines.append("")

    # Top pick recommendation
    if top_pick:
        lines.append("---")
        lines.append("## ⭐ Top Pick Recommendation")
        tp_fixture = top_pick.get("fixture", "?")
        tp_market = top_pick.get("market", "?")
        tp_odds = top_pick.get("odds", 0)
        tp_conf = top_pick.get("confidence", 0)
        tp_gate = top_pick.get("gate_verdict", "?")
        tp_home = top_pick.get("home", "?")
        tp_away = top_pick.get("away", "?")
        lines.append(f"**{tp_home} vs {tp_away} → {tp_market} @{format_odds(tp_odds)}**")
        lines.append(f"Confidence: {tp_conf:.0f}% | Gate: {tp_gate}")
        lines.append("")

    # Summary stats
    lines.append("---")
    lines.append(f"**Summary:** {fixtures_total} fixtures | "
                 f"Gates passed: {gates_passed_total} | "
                 f"Gates failed: {gates_failed_total}")

    lines.append("")
    lines.append(f"_Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────
# MAIN PREDICTOR
# ──────────────────────────────────────────────────────────────────────
def run_predictor(
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    """Main predictor logic.

    Returns True if new data was processed and output printed, False otherwise.
    """
    # ── 1. Fetch current match day info ─────────────────────────────
    try:
        from msport_api import get_current_match_day_info, get_event_list

        info = get_current_match_day_info()
        if not info:
            logger.warning("Could not fetch current match day info from MSport API")
            print("⚠️ Could not fetch current match day info from MSport API")
            return False

        season_id = str(info.get("seasonId", ""))
        season_name = str(info.get("seasonName", ""))
        md_val = info.get("matchDay", 0)
        match_day = int(md_val) if md_val is not None else 0
        match_day_start_time = info.get("matchDayStartTime", 0)
    except Exception as e:
        logger.error("Failed to fetch match day info: %s", e)
        print(f"⚠️ API error: {e}")
        return False

    logger.info(
        "Current: Season=%s (%s), MatchDay=%d, Start=%s",
        season_id, season_name, match_day,
        format_timestamp(match_day_start_time),
    )

    # ── 2. State comparison ──────────────────────────────────────────
    state = load_state()
    last_sid = state.get("last_season_id")
    last_md = state.get("last_match_day")

    if (
        not force
        and last_sid == season_id
        and last_md == match_day
    ):
        logger.info(
            "Matchday %s / Season %s already processed. Exiting silently. Producing minimal output for cronjob success.",
            match_day, season_id,
        )
        # Indicate successful (but silent) processing for cronjob status
        print("VFL Live Predictor: No new data to process. Exiting silently with success.")
        return True

    # ── 3. Fetch event list ──────────────────────────────────────────
    try:
        match_days = get_event_list()
        if not match_days:
            logger.warning("get_event_list() returned no data")
            print("⚠️ No event data returned from MSport API")
            return False
    except Exception as e:
        logger.error("Failed to fetch event list: %s", e)
        print(f"⚠️ Event list error: {e}")
        return False

    logger.info("Fetched %d matchday(s) from MSport", len(match_days))

    # ── 4. Find the matchday that matches ────────────────────────────
    target_md = None
    for md in match_days:
        md_num = md.get("matchDay") or md.get("matchday")
        if md_num == match_day:
            target_md = md
            break

    if not target_md:
        # Fallback: use the first matchday with events
        for md in match_days:
            events = md.get("events") or []
            if events:
                target_md = md
                break

    if not target_md:
        logger.warning("No matchday with events found")
        print("⚠️ No matchday with events found")
        return False

    events = target_md.get("events") or []
    logger.info("Processing matchday %d with %d event(s)", match_day, len(events))

    # ── 5. Analyze each fixture ──────────────────────────────────────
    fixture_analyses: List[Dict[str, Any]] = []
    gates_passed_total = 0
    gates_failed_total = 0
    fixtures_total = 0

    for event in events:
        home_raw = event.get("homeTeam") or event.get("homeName") or ""
        away_raw = event.get("awayTeam") or event.get("awayName") or ""
        home = normalize_team(home_raw) or home_raw
        away = normalize_team(away_raw) or away_raw

        if not home or not away:
            continue

        odds_dict = extract_odds(event)
        markets = event.get("markets") or []
        logger.debug(
            "Analyzing %s vs %s: O1.5=%s, O2.5=%s, U2.5=%s, U3.5=%s, GG=%s, NG=%s",
            home, away,
            odds_dict.get("o15"), odds_dict.get("o25"),
            odds_dict.get("u25"), odds_dict.get("u35"),
            odds_dict.get("gg"), odds_dict.get("ng"),
        )

        fa = analyze_fixture(home, away, odds_dict, event_markets=markets)
        fixture_analyses.append(fa)
        fixtures_total += 1

        # Count gates
        for mkt_result in fa.get("gate_results", {}).values():
            if mkt_result.get("verdict") == "PASS":
                gates_passed_total += 1
            elif mkt_result.get("verdict") == "FAIL":
                gates_failed_total += 1

        best = fa.get("best_pick")
        if best:
            logger.info(
                "%s vs %s → Best: %s @%.2f (conf=%.0f%%, gate=%s)",
                home, away,
                best["market"], best["odds"],
                best["confidence"], best["gate_verdict"],
            )
            # Log to DB
            log_prediction_to_db({
                "_logged_at": datetime.now(timezone.utc).isoformat(),
                "season_id": season_id,
                "match_day": match_day,
                "home": home,
                "away": away,
                "prediction": best["market"],
                "confidence": best["confidence"],
                "odds": best["odds"],
            })
        else:
            logger.info("%s vs %s → No qualifying pick", home, away)

    # ── 6. Determine top pick ────────────────────────────────────────
    top_pick: Optional[Dict[str, Any]] = None
    best_conf = 0.0

    for fa in fixture_analyses:
        best = fa.get("best_pick")
        if best and best["confidence"] > best_conf:
            best_conf = best["confidence"]
            top_pick = {
                "fixture": f"{fa['home']} vs {fa['away']}",
                "home": fa["home"],
                "away": fa["away"],
                "market": best["display"],
                "odds": best["odds"],
                "confidence": best["confidence"],
                "gate_verdict": best["gate_verdict"],
            }

    # ── 7. Build & print report ──────────────────────────────────────
    report = build_report(
        season_name=season_name,
        match_day=match_day,
        match_day_start_time=match_day_start_time,
        season_id=season_id,
        fixture_analyses=fixture_analyses,
        gates_passed_total=gates_passed_total,
        gates_failed_total=gates_failed_total,
        fixtures_total=fixtures_total,
        top_pick=top_pick,
    )
    print(report)

    # ── 8. Write predictions_latest.json & update state ─────────────────
    if not dry_run:
        write_predictions_latest(season_name, season_id, match_day, fixture_analyses)
        state["last_season_id"] = season_id
        state["last_match_day"] = match_day
        save_state(state)

    return True


def main():
    parser = argparse.ArgumentParser(description="VFL Live Predictor")
    parser.add_argument("--dry-run", action="store_true", help="Run without saving state or writing latest predictions")
    parser.add_argument("--force", action="store_true", help="Force prediction even if matchday already processed")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(args.debug)
    run_predictor(dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()