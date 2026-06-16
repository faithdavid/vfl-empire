#!/usr/bin/env python3
"""
VFL Position Integration Module
================================
Provides position-conditional adjustment for H2H predictions.
Used by vfl_rapid_daemon.py to factor league position into betting decisions.

Key function: get_position_adjustment(home, away, season_id, matchday)
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("vfl_positional")

# ── Paths ─────────────────────────────────────────────────────────────────────
WORKSPACE = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
POSITION_MATRIX_FILE = WORKSPACE / "signals" / "position_matrix.json"

# ── Zone definitions (mirrors vfl_positional_analysis.py) ────────────────────
ZONE_DEFS = [
    (1, 2, "title"),
    (3, 4, "ucl"),
    (5, 7, "europa"),
    (8, 12, "upper_mid"),
    (13, 16, "lower_mid"),
    (17, 18, "relegation"),
    (19, 20, "bottom"),
]

def get_zone(position: int) -> str:
    if position < 1:
        return "unknown"
    for start, end, name in ZONE_DEFS:
        if start <= position <= end:
            return name
    return "unknown"

def get_points_gap_category(home_points: int, away_points: int) -> str:
    gap = home_points - away_points
    if gap > 20:
        return "huge"
    elif gap > 10:
        return "significant"
    elif gap > 3:
        return "moderate"
    elif gap >= -3:
        return "close"
    elif gap >= -10:
        return "moderate_disadvantage"
    elif gap >= -20:
        return "significant_disadvantage"
    else:
        return "huge_disadvantage"


def _load_matrix() -> dict:
    """Load the position matrix from disk."""
    if not POSITION_MATRIX_FILE.exists():
        logger.warning(f"Position matrix not found at {POSITION_MATRIX_FILE}")
        return {}
    try:
        return json.loads(POSITION_MATRIX_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load position matrix: {e}")
        return {}


def get_position_adjustment(home: str, away: str, season_id: str = None,
                            matchday: int = None, league_table: list = None) -> dict:
    """Get position-conditional adjustment factors for a fixture.
    
    Args:
        home: Home team name (normalized)
        away: Away team name (normalized)
        season_id: Season ID (optional, used for table lookup)
        matchday: Matchday number (optional)
        league_table: Pre-built league table (optional, avoids extra DB call)
        
    Returns:
        Dict with adjustment factors or zero-effect defaults.
    """
    matrix = _load_matrix()
    if not matrix:
        return _zero_adjustment("NO_MATRIX")
    
    # Get team positions from league table
    home_pos = None
    away_pos = None
    home_pts = 0
    away_pts = 0
    
    if league_table:
        for i, entry in enumerate(league_table, 1):
            team = entry.get("team", "")
            if team.lower() == home.lower():
                home_pos = i
                home_pts = entry.get("points", 0)
            if team.lower() == away.lower():
                away_pos = i
                away_pts = entry.get("points", 0)
    
    if home_pos is None or away_pos is None:
        # Try DB lookup
        try:
            from season_tracker import TeamTracker
            tracker = TeamTracker()
            table = tracker.build_league_table(season_id) if season_id else []
            tracker.close()
            
            if not table and league_table:
                table = league_table
            
            for i, entry in enumerate(table, 1):
                team = entry.get("team", "")
                if team.lower() == home.lower():
                    home_pos = i
                    home_pts = entry.get("points", 0)
                if team.lower() == away.lower():
                    away_pos = i
                    away_pts = entry.get("points", 0)
        except Exception as e:
            logger.debug(f"Could not look up positions: {e}")
    
    if home_pos is None or away_pos is None:
        return _zero_adjustment("NO_POSITION_DATA")
    
    # Determine zones and matchup
    home_zone = get_zone(home_pos)
    away_zone = get_zone(away_pos)
    matchup = f"{home_zone}_vs_{away_zone}"
    rev_matchup = f"{away_zone}_vs_{home_zone}"
    gap_category = get_points_gap_category(home_pts, away_pts)
    
    result = {
        "has_position_data": True,
        "home_position": home_pos,
        "away_position": away_pos,
        "home_zone": home_zone,
        "away_zone": away_zone,
        "zone_matchup": matchup,
        "points_gap_category": gap_category,
        "home_points": home_pts,
        "away_points": away_pts,
        "points_gap": home_pts - away_pts,
    }
    
    # Look up zone matchup stats
    zone_matchups = matrix.get("zone_matchups", {})
    zone_data = zone_matchups.get(matchup, {})
    
    # Also check the reverse matchup (for away zone effects)
    rev_zone_data = zone_matchups.get(rev_matchup, {})
    
    if zone_data:
        result["zone_stats"] = zone_data
        result["zone_n_matches"] = zone_data.get("n_matches", 0)
        result["zone_effect_o1_5"] = zone_data.get("position_effect_o1_5", 0)
        result["zone_effect_o2_5"] = zone_data.get("position_effect_o2_5", 0)
        result["zone_effect_gg"] = zone_data.get("position_effect_gg", 0)
        result["zone_o1_5_rate"] = zone_data.get("o1_5_rate", 0)
        result["zone_o2_5_rate"] = zone_data.get("o2_5_rate", 0)
        result["zone_gg_rate"] = zone_data.get("gg_rate", 0)
        result["zone_home_win_rate"] = zone_data.get("home_win_rate", 0)
    else:
        result["zone_stats"] = None
    
    # Look up points gap stats
    gap_data = matrix.get("points_gap", {}).get(gap_category, {})
    if gap_data:
        result["gap_stats"] = gap_data
        result["gap_n_matches"] = gap_data.get("n_matches", 0)
        result["gap_effect_o1_5"] = gap_data.get("position_effect_o1_5", 0)
        result["gap_effect_o2_5"] = gap_data.get("position_effect_o2_5", 0)
    else:
        result["gap_stats"] = None
    
    # Compute combined adjustment factors
    # Weight: zone matchup is primary, points gap is secondary
    zone_eff_o15 = result.get("zone_effect_o1_5", 0)
    zone_eff_o25 = result.get("zone_effect_o2_5", 0)
    zone_eff_gg = result.get("zone_effect_gg", 0)
    
    gap_eff_o15 = result.get("gap_effect_o1_5", 0) if result.get("gap_stats") else 0
    gap_eff_o25 = result.get("gap_effect_o2_5", 0) if result.get("gap_stats") else 0
    
    # Weighted blend: 70% zone matchup, 30% points gap (if both available)
    has_gap = "gap_stats" in result and result["gap_stats"] is not None
    has_zone = "zone_stats" in result and result["zone_stats"] is not None
    
    if has_zone and has_gap:
        adj_o15 = zone_eff_o15 * 0.7 + gap_eff_o15 * 0.3
        adj_o25 = zone_eff_o25 * 0.7 + gap_eff_o25 * 0.3
    elif has_zone:
        adj_o15 = zone_eff_o15
        adj_o25 = zone_eff_o25
    elif has_gap:
        adj_o15 = gap_eff_o15
        adj_o25 = gap_eff_o25
    else:
        adj_o15 = 0.0
        adj_o25 = 0.0
    
    # For GG: only zone data, no gap data typically
    adj_gg = zone_eff_gg if has_zone else 0.0
    
    result["adjustment"] = {
        "o1_5": round(adj_o15, 4),
        "o2_5": round(adj_o25, 4),
        "gg": round(adj_gg, 4),
        "combined_signal": round(adj_o15 + adj_o25 + adj_gg, 4),
    }
    
    # Overall position confidence score (0-100)
    # Higher = position effect strongly supports this fixture
    confidence = _compute_position_confidence(result, matrix)
    result["position_confidence"] = confidence
    
    return result


def _compute_position_confidence(ctx: dict, matrix: dict) -> float:
    """Compute a confidence score (0-100) for the position data.
    
    Higher score = more reliable signal.
    """
    score = 50.0  # Neutral baseline
    
    n_zone = ctx.get("zone_n_matches", 0)
    n_gap = ctx.get("gap_n_matches", 0)
    
    # Sample size bonus (up to +20)
    score += min(n_zone / 500, 1.0) * 15
    score += min(n_gap / 500, 1.0) * 5
    
    # Signal strength bonus/penalty
    adj = ctx.get("adjustment", {})
    signal_magnitude = abs(adj.get("combined_signal", 0))
    score += min(signal_magnitude * 100, 15)  # Up to +15 for strong signals
    
    # Zone clarity bonus
    home_zone = ctx.get("home_zone", "unknown")
    away_zone = ctx.get("away_zone", "unknown")
    if home_zone != "unknown" and away_zone != "unknown" and home_zone != away_zone:
        score += 10  # Clear positional mismatch = more informative
    
    # Position data presence
    if ctx.get("home_position", 99) <= 20 and ctx.get("away_position", 99) <= 20:
        score += 10  # Both teams have valid positions
    
    return min(max(score, 0), 100)


def _zero_adjustment(reason: str) -> dict:
    """Return zero-effect adjustment when position data is unavailable."""
    return {
        "has_position_data": False,
        "reason": reason,
        "home_position": None,
        "away_position": None,
        "home_zone": "unknown",
        "away_zone": "unknown",
        "zone_matchup": "unknown_vs_unknown",
        "zone_stats": None,
        "gap_stats": None,
        "adjustment": {"o1_5": 0.0, "o2_5": 0.0, "gg": 0.0, "combined_signal": 0.0},
        "position_confidence": 0,
    }


def apply_position_adjustment(h2h_result: dict, position_adjustment: dict) -> dict:
    """Apply position adjustment to an H2H result.
    
    Modifies hit rates by the position effect.
    Returns updated H2H dict with post_adjustment fields.
    """
    if not h2h_result or not position_adjustment:
        return h2h_result or {}
    
    result = dict(h2h_result)
    adj = position_adjustment.get("adjustment", {})
    confidence = position_adjustment.get("position_confidence", 0)
    
    # Only apply if position confidence is meaningful (> 20)
    if confidence < 20:
        result["position_applied"] = False
        result["position_confidence"] = confidence
        return result
    
    # Apply adjustments to hit rates
    o1_5_rate = result.get("o1_5_rate", 50.0) / 100.0
    o2_5_rate = result.get("o2_5_rate", 50.0) / 100.0
    gg_rate = result.get("gg_rate", 50.0) / 100.0
    
    adj_o15 = adj.get("o1_5", 0.0)
    adj_o25 = adj.get("o2_5", 0.0)
    adj_gg = adj.get("gg", 0.0)
    
    # Blend: weight position effect by confidence
    weight = min(confidence / 100.0, 0.5)  # Max 50% weight for position
    
    result["adjusted_o1_5_rate"] = round((o1_5_rate * (1 - weight) + (o1_5_rate + adj_o15) * weight) * 100, 2)
    result["adjusted_o2_5_rate"] = round((o2_5_rate * (1 - weight) + (o2_5_rate + adj_o25) * weight) * 100, 2)
    result["adjusted_gg_rate"] = round((gg_rate * (1 - weight) + (gg_rate + adj_gg) * weight) * 100, 2)
    result["position_applied"] = True
    result["position_confidence"] = confidence
    result["position_weight"] = weight
    result["position_adjustment_raw"] = adj
    
    return result


# ── Quick test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) >= 3:
        home = sys.argv[1]
        away = sys.argv[2]
        season = sys.argv[3] if len(sys.argv) > 3 else None
        md = int(sys.argv[4]) if len(sys.argv) > 4 else None
    else:
        home, away = "Chelsea", "Leeds"
        season = None
        md = None
    
    print(f"\nPosition adjustment for: {home} vs {away}")
    if season:
        print(f"  Season: {season}, Matchday: {md}")
    
    adj = get_position_adjustment(home, away, season, md)
    print(f"\nResult:")
    print(json.dumps(adj, indent=2, default=str))
