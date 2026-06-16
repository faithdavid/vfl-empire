#!/usr/bin/env python3
"""
VFL Positional Behavioural Analysis — Build & Query
=====================================================
Analyzes how league position affects match outcomes across 80+ seasons.

Usage:
    python3 vfl_positional_analysis.py --build          # Build/rebuild the position matrix
    python3 vfl_positional_analysis.py --query           # Interactive query mode
    python3 vfl_positional_analysis.py --stats           # Print summary stats
"""

import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
WORKSPACE = Path("/home/ubuntu/faith-workspace/vfl-complete-data")
RESULTS_DB = WORKSPACE / "databases" / "vfl_results.db"
SIGNALS_DIR = WORKSPACE / "signals"
POSITION_MATRIX_FILE = SIGNALS_DIR / "position_matrix.json"

# ── Team Name Normalisation (mirrors season_tracker.py) ──────────────────────
TEAM_ALIASES = {
    "MANCHESTER RED": "Manchester Red", "MANCHESTER BLUE": "Manchester Blue",
    "MANCHESTER CITY": "Manchester Blue", "MANCHESTER UNITED": "Manchester Red",
    "LONDON GUNS": "London Guns", "LONDON GUNNERS": "London Guns",
    "ARSENAL": "London Guns", "CHELSEA": "Chelsea", "LIVERPOOL": "Liverpool",
    "ASTON VILLA": "Aston Villa", "TOTTENHAM": "Tottenham",
    "EVERTON": "Everton", "WOLVERHAMPTON": "Wolverhampton",
    "NEWCASTLE": "Newcastle", "LEEDS": "Leeds",
    "FULHAM": "Fulham", "WEST HAM": "West Ham",
    "BOURNEMOUTH": "Bournemouth", "BRIGHTON": "Brighton",
    "CRYSTAL PALACE": "Crystal Palace",
}

def normalize(name: str) -> str:
    n = name.strip().upper()
    return TEAM_ALIASES.get(n, name.strip().title())

# ── Position Zones ────────────────────────────────────────────────────────────
# Zones: (start_pos, end_pos, zone_name)
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


# ── League Table Builder ──────────────────────────────────────────────────────

def build_table_from_results(results: list) -> list:
    """Build a sorted league table from a list of completed result dicts.
    
    Each result dict has: home_team, away_team, home_goals, away_goals.
    Returns sorted list of dicts with position assigned.
    """
    teams = {}
    for r in results:
        for side in ["home_team", "away_team"]:
            t = normalize(r[side])
            if t not in teams:
                teams[t] = {"team": t, "played": 0, "wins": 0, "draws": 0,
                            "losses": 0, "goals_for": 0, "goals_against": 0,
                            "gd": 0, "points": 0}

        home = normalize(r["home_team"])
        away = normalize(r["away_team"])
        hg = r["home_goals"]
        ag = r["away_goals"]

        teams[home]["played"] += 1
        teams[away]["played"] += 1
        teams[home]["goals_for"] += hg
        teams[home]["goals_against"] += ag
        teams[away]["goals_for"] += ag
        teams[away]["goals_against"] += hg

        if hg > ag:
            teams[home]["wins"] += 1
            teams[home]["points"] += 3
            teams[away]["losses"] += 1
        elif ag > hg:
            teams[away]["wins"] += 1
            teams[away]["points"] += 3
            teams[home]["losses"] += 1
        else:
            teams[home]["draws"] += 1
            teams[away]["draws"] += 1
            teams[home]["points"] += 1
            teams[away]["points"] += 1

    table = []
    for t, d in teams.items():
        d["gd"] = d["goals_for"] - d["goals_against"]
        table.append(d)

    # Sort by points, then GD, then goals scored
    table.sort(key=lambda x: (-x["points"], -x["gd"], -x["goals_for"]))

    # Assign positions
    for i, entry in enumerate(table, 1):
        entry["position"] = i

    return table


# ── Build Position Dataset ────────────────────────────────────────────────────

def build_position_dataset() -> list:
    """Build a complete positional dataset from vfl_results.db.
    
    For each season, iterates through matchdays in order.
    Before each matchday, builds the league table from PREVIOUS results.
    Records position data for each fixture.
    
    Returns a list of record dicts.
    """
    print(f"Connecting to {RESULTS_DB}...")
    conn = sqlite3.connect(str(RESULTS_DB))
    conn.row_factory = sqlite3.Row

    # Get all seasons with completed results
    seasons = conn.execute(
        "SELECT DISTINCT season_id, season_name FROM results WHERE status=3 ORDER BY season_name"
    ).fetchall()
    
    print(f"Found {len(seasons)} seasons total")
    
    all_records = []
    total_fixtures = 0
    season_count = 0
    
    for s_idx, s in enumerate(seasons):
        sid = s["season_id"]
        sname = s["season_name"]
        
        # Get all completed results for this season, ordered by match_day
        all_season_results = conn.execute(
            "SELECT * FROM results WHERE season_id=? AND status=3 ORDER BY match_day, captured_at",
            (sid,)
        ).fetchall()
        
        if not all_season_results:
            continue
        
        # Get distinct matchdays
        matchdays = sorted(set(r["match_day"] for r in all_season_results))
        
        if not matchdays:
            continue
        
        # Group results by matchday
        results_by_md = defaultdict(list)
        for r in all_season_results:
            results_by_md[r["match_day"]].append(r)
        
        # Build league table incrementally
        results_so_far = []
        season_fixtures = 0
        
        for md in matchdays:
            md_fixtures = results_by_md.get(md, [])
            if not md_fixtures:
                continue
            
            # Build league table from results BEFORE this matchday
            table = build_table_from_results(results_so_far)
            table_by_team = {entry["team"]: entry for entry in table}
            
            for fx in md_fixtures:
                home = normalize(fx["home_team"])
                away = normalize(fx["away_team"])
                
                home_data = table_by_team.get(home, {"position": 99, "points": 0})
                away_data = table_by_team.get(away, {"position": 99, "points": 0})
                
                home_pos = home_data["position"]
                away_pos = away_data["position"]
                home_pts = home_data["points"]
                away_pts = away_data["points"]
                
                home_zone = get_zone(home_pos)
                away_zone = get_zone(away_pos)
                
                # Determine which zone is "higher" (lower number = better)
                zone_matchup = f"{home_zone}_vs_{away_zone}"
                
                tg = fx["total_goals"] if fx["total_goals"] is not None else 0
                hg = fx["home_goals"] if fx["home_goals"] is not None else 0
                ag = fx["away_goals"] if fx["away_goals"] is not None else 0
                
                # Reverse matchup (for symmetrically analyzing away zone effects)
                rev_zone_matchup = f"{away_zone}_vs_{home_zone}"
                
                record = {
                    "season_id": sid,
                    "season_name": sname,
                    "matchday": md,
                    "home": home,
                    "away": away,
                    "home_position": home_pos,
                    "away_position": away_pos,
                    "home_points": home_pts,
                    "away_points": away_pts,
                    "points_gap": home_pts - away_pts,
                    "points_gap_category": get_points_gap_category(home_pts, away_pts),
                    "home_zone": home_zone,
                    "away_zone": away_zone,
                    "zone_matchup": zone_matchup,
                    "rev_zone_matchup": rev_zone_matchup,
                    "total_goals": tg,
                    "home_goals": hg,
                    "away_goals": ag,
                    "o1_5": 1 if tg > 1.5 else 0,
                    "o2_5": 1 if tg > 2.5 else 0,
                    "o3_5": 1 if tg > 3.5 else 0,
                    "gg": 1 if (hg > 0 and ag > 0) else 0,
                    "home_win": 1 if hg > ag else 0,
                    "away_win": 1 if ag > hg else 0,
                    "draw": 1 if hg == ag else 0,
                }
                all_records.append(record)
                season_fixtures += 1
                total_fixtures += 1
            
            # Add these results for next matchday's table
            results_so_far.extend(md_fixtures)
        
        season_count += 1
        if season_count % 10 == 0 or season_count == len(seasons) or s_idx == 0:
            print(f"  Season {season_count}/{len(seasons)}: {sname} ({sid}) — {season_fixtures} fixtures, running total: {total_fixtures}")
    
    conn.close()
    print(f"\nTotal records built: {total_fixtures}")
    return all_records


# ── Build Statistical Matrix ──────────────────────────────────────────────────

def build_statistical_matrix(records: list) -> dict:
    """Build a statistical matrix from the position dataset.
    
    Returns nested dict with stats for each zone_matchup, points_gap_category,
    and overall baselines.
    """
    # Overall baselines
    total = len(records)
    if total == 0:
        return {"error": "No records to analyze"}
    
    baseline = {
        "n_matches": total,
        "o1_5_rate": sum(r["o1_5"] for r in records) / total,
        "o2_5_rate": sum(r["o2_5"] for r in records) / total,
        "o3_5_rate": sum(r["o3_5"] for r in records) / total,
        "gg_rate": sum(r["gg"] for r in records) / total,
        "home_win_rate": sum(r["home_win"] for r in records) / total,
        "away_win_rate": sum(r["away_win"] for r in records) / total,
        "draw_rate": sum(r["draw"] for r in records) / total,
        "avg_total_goals": sum(r["total_goals"] for r in records) / total,
        "avg_home_goals": sum(r["home_goals"] for r in records) / total,
        "avg_away_goals": sum(r["away_goals"] for r in records) / total,
    }
    
    # Group by zone_matchup
    zone_groups = defaultdict(list)
    for r in records:
        zone_groups[r["zone_matchup"]].append(r)
    
    zone_matrix = {}
    for matchup, group in sorted(zone_groups.items()):
        n = len(group)
        if n < 10:
            continue  # Skip matchups with too few samples
        
        o1_5_rate = sum(r["o1_5"] for r in group) / n
        o2_5_rate = sum(r["o2_5"] for r in group) / n
        o3_5_rate = sum(r["o3_5"] for r in group) / n
        gg_rate = sum(r["gg"] for r in group) / n
        home_win_rate = sum(r["home_win"] for r in group) / n
        away_win_rate = sum(r["away_win"] for r in group) / n
        draw_rate = sum(r["draw"] for r in group) / n
        avg_total = sum(r["total_goals"] for r in group) / n
        
        zone_matrix[matchup] = {
            "n_matches": n,
            "o1_5_rate": round(o1_5_rate, 4),
            "o2_5_rate": round(o2_5_rate, 4),
            "o3_5_rate": round(o3_5_rate, 4),
            "gg_rate": round(gg_rate, 4),
            "home_win_rate": round(home_win_rate, 4),
            "away_win_rate": round(away_win_rate, 4),
            "draw_rate": round(draw_rate, 4),
            "avg_total_goals": round(avg_total, 4),
            "baseline_o1_5": round(baseline["o1_5_rate"], 4),
            "baseline_o2_5": round(baseline["o2_5_rate"], 4),
            "baseline_gg": round(baseline["gg_rate"], 4),
            "position_effect_o1_5": round(o1_5_rate - baseline["o1_5_rate"], 4),
            "position_effect_o2_5": round(o2_5_rate - baseline["o2_5_rate"], 4),
            "position_effect_gg": round(gg_rate - baseline["gg_rate"], 4),
        }
    
    # Group by points_gap_category
    gap_groups = defaultdict(list)
    for r in records:
        gap_groups[r["points_gap_category"]].append(r)
    
    gap_matrix = {}
    for category, group in sorted(gap_groups.items()):
        n = len(group)
        if n < 10:
            continue
        
        o1_5_rate = sum(r["o1_5"] for r in group) / n
        o2_5_rate = sum(r["o2_5"] for r in group) / n
        gg_rate = sum(r["gg"] for r in group) / n
        home_win_rate = sum(r["home_win"] for r in group) / n
        avg_total = sum(r["total_goals"] for r in group) / n
        
        gap_matrix[category] = {
            "n_matches": n,
            "o1_5_rate": round(o1_5_rate, 4),
            "o2_5_rate": round(o2_5_rate, 4),
            "gg_rate": round(gg_rate, 4),
            "home_win_rate": round(home_win_rate, 4),
            "avg_total_goals": round(avg_total, 4),
            "position_effect_o1_5": round(o1_5_rate - baseline["o1_5_rate"], 4),
            "position_effect_o2_5": round(o2_5_rate - baseline["o2_5_rate"], 4),
            "position_effect_gg": round(gg_rate - baseline["gg_rate"], 4),
        }
    
    # Home position analysis (how does home team's position affect outcomes?)
    home_pos_groups = defaultdict(list)
    for r in records:
        bucket = get_position_bucket(r["home_position"])
        home_pos_groups[bucket].append(r)
    
    home_pos_matrix = {}
    for bucket, group in sorted(home_pos_groups.items()):
        n = len(group)
        if n < 20:
            continue
        home_pos_matrix[bucket] = {
            "n_matches": n,
            "o1_5_rate": round(sum(r["o1_5"] for r in group) / n, 4),
            "o2_5_rate": round(sum(r["o2_5"] for r in group) / n, 4),
            "gg_rate": round(sum(r["gg"] for r in group) / n, 4),
            "home_win_rate": round(sum(r["home_win"] for r in group) / n, 4),
            "avg_total_goals": round(sum(r["total_goals"] for r in group) / n, 4),
        }
    
    return {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "total_seasons": len(set(r["season_id"] for r in records)),
        "total_matches": total,
        "baseline": baseline,
        "zone_matchups": zone_matrix,
        "points_gap": gap_matrix,
        "home_position": home_pos_matrix,
    }


def get_position_bucket(pos: int) -> str:
    """Bucket a position into a range string."""
    if pos <= 2:
        return "1-2"
    elif pos <= 4:
        return "3-4"
    elif pos <= 7:
        return "5-7"
    elif pos <= 12:
        return "8-12"
    elif pos <= 16:
        return "13-16"
    elif pos <= 18:
        return "17-18"
    elif pos <= 20:
        return "19-20"
    else:
        return "unknown"


# ── Query Mode ────────────────────────────────────────────────────────────────

def query_fixture(home: str, away: str, season_id: str = None, matchday: int = None) -> dict:
    """Get position context for a specific fixture."""
    try:
        from season_tracker import TeamTracker
        tracker = TeamTracker()
        
        # Load position matrix
        matrix = {}
        if POSITION_MATRIX_FILE.exists():
            try:
                matrix = json.loads(POSITION_MATRIX_FILE.read_text())
            except:
                pass
        
        result = {
            "home": home,
            "away": away,
            "season_id": season_id or "unknown",
            "matchday": matchday,
            "position_context": None,
            "matrix_lookup": None,
        }
        
        # Get league table for this season
        if season_id:
            table = tracker.build_league_table(season_id)
            home_data = None
            away_data = None
            
            for entry in table:
                if entry["team"].lower() == home.lower():
                    home_data = entry
                if entry["team"].lower() == away.lower():
                    away_data = entry
            
            if home_data and away_data:
                home_pos = home_data.get("position", home_data.get("rank", 99))
                away_pos = away_data.get("position", away_data.get("rank", 99))
                # Handle if position is stored differently
                if home_pos == 99 and "position" not in home_data:
                    # Calculate position from table index
                    for i, t in enumerate(table, 1):
                        if t["team"].lower() == home.lower():
                            home_pos = i
                        if t["team"].lower() == away.lower():
                            away_pos = i
                
                home_zone = get_zone(home_pos)
                away_zone = get_zone(away_pos)
                matchup = f"{home_zone}_vs_{away_zone}"
                
                context = {
                    "home_position": home_pos,
                    "away_position": away_pos,
                    "home_points": home_data.get("points", 0),
                    "away_points": away_data.get("points", 0),
                    "points_gap": home_data.get("points", 0) - away_data.get("points", 0),
                    "home_zone": home_zone,
                    "away_zone": away_zone,
                    "zone_matchup": matchup,
                }
                result["position_context"] = context
                
                # Look up in matrix
                if "zone_matchups" in matrix and matchup in matrix["zone_matchups"]:
                    result["matrix_lookup"] = matrix["zone_matchups"][matchup]
                    # Also try reverse
                    rev_matchup = f"{away_zone}_vs_{home_zone}"
                    if rev_matchup in matrix["zone_matchups"]:
                        result["matrix_lookup_reverse"] = matrix["zone_matchups"][rev_matchup]
                
                # Also check points_gap
                if context.get("points_gap_category") and "points_gap" in matrix:
                    cat = context["points_gap_category"]
                    if cat in matrix["points_gap"]:
                        result["gap_lookup"] = matrix["points_gap"][cat]
        
        tracker.close()
        return result
    
    except ImportError:
        return {"error": "Cannot import season_tracker"}
    except Exception as e:
        return {"error": str(e)}


# ── Print Summary Stats ──────────────────────────────────────────────────────

def print_summary(matrix: dict):
    """Print a human-readable summary of the position matrix."""
    if not matrix or "error" in matrix:
        print("No matrix data available.")
        return
    
    b = matrix.get("baseline", {})
    print(f"\n{'='*70}")
    print(f"VFL POSITIONAL BEHAVIOURAL ANALYSIS")
    print(f"{'='*70}")
    print(f"Built at:     {matrix.get('built_at', 'unknown')}")
    print(f"Total seasons: {matrix.get('total_seasons', 0)}")
    print(f"Total matches: {matrix.get('total_matches', 0)}")
    print(f"\n── BASELINE (overall VFL averages) ──")
    print(f"  O1.5 rate:     {b.get('o1_5_rate', 0)*100:5.1f}%")
    print(f"  O2.5 rate:     {b.get('o2_5_rate', 0)*100:5.1f}%")
    print(f"  GG rate:       {b.get('gg_rate', 0)*100:5.1f}%")
    print(f"  Home win rate: {b.get('home_win_rate', 0)*100:5.1f}%")
    print(f"  Avg goals:     {b.get('avg_total_goals', 0):5.2f}")
    
    zm = matrix.get("zone_matchups", {})
    if zm:
        print(f"\n── ZONE MATCHUPS (n >= 10) ──")
        print(f"  {'Matchup':<35} {'n':<6} {'O1.5':<8} {'O2.5':<8} {'GG':<8} {'HW%':<8} {'AvgG':<6} {'EffO1.5':<10}")
        print(f"  {'-'*35} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6} {'-'*10}")
        for matchup, data in sorted(zm.items(), key=lambda x: -x[1]["n_matches"]):
            eff = data.get("position_effect_o1_5", 0)
            eff_str = f"{eff*100:+5.1f}%" if abs(eff) > 0.001 else " 0.0%"
            print(f"  {matchup:<35} {data['n_matches']:<6} {data['o1_5_rate']*100:<8.1f} {data['o2_5_rate']*100:<8.1f} {data['gg_rate']*100:<8.1f} {data['home_win_rate']*100:<8.1f} {data['avg_total_goals']:<6.2f} {eff_str:<10}")
    
    pg = matrix.get("points_gap", {})
    if pg:
        print(f"\n── POINTS GAP CATEGORIES ──")
        print(f"  {'Category':<30} {'n':<6} {'O1.5':<8} {'O2.5':<8} {'GG':<8} {'HW%':<8} {'AvgG':<6}")
        print(f"  {'-'*30} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")
        for cat, data in sorted(pg.items(), key=lambda x: -x[1]["n_matches"]):
            print(f"  {cat:<30} {data['n_matches']:<6} {data['o1_5_rate']*100:<8.1f} {data['o2_5_rate']*100:<8.1f} {data['gg_rate']*100:<8.1f} {data['home_win_rate']*100:<8.1f} {data['avg_total_goals']:<6.2f}")
    
    hp = matrix.get("home_position", {})
    if hp:
        print(f"\n── HOME POSITION ANALYSIS ──")
        print(f"  {'Pos':<8} {'n':<6} {'O1.5':<8} {'O2.5':<8} {'GG':<8} {'HW%':<8} {'AvgG':<6}")
        print(f"  {'-'*8} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")
        for bucket, data in sorted(hp.items()):
            print(f"  {bucket:<8} {data['n_matches']:<6} {data['o1_5_rate']*100:<8.1f} {data['o2_5_rate']*100:<8.1f} {data['gg_rate']*100:<8.1f} {data['home_win_rate']*100:<8.1f} {data['avg_total_goals']:<6.2f}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="VFL Positional Behavioural Analysis"
    )
    parser.add_argument("--build", action="store_true", help="Build/rebuild the position matrix")
    parser.add_argument("--query", nargs=4, metavar=("HOME", "AWAY", "SEASON", "MATCHDAY"),
                        help="Query position context for a fixture: --query Chelsea Leeds vf:season:3092265 9")
    parser.add_argument("--stats", action="store_true", help="Print summary stats from existing matrix")
    
    args = parser.parse_args()
    
    if args.build:
        print("Building VFL Positional Behavioural Model...")
        print("=" * 60)
        
        start_time = time.time()
        records = build_position_dataset()
        build_time = time.time() - start_time
        print(f"\nDataset built in {build_time:.1f}s: {len(records)} records")
        
        if records:
            print("\nBuilding statistical matrix...")
            matrix = build_statistical_matrix(records)
            
            # Save
            SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
            POSITION_MATRIX_FILE.write_text(
                json.dumps(matrix, indent=2, default=str)
            )
            print(f"\nMatrix saved to {POSITION_MATRIX_FILE}")
            print(f"  Zone matchups: {len(matrix.get('zone_matchups', {}))}")
            print(f"  Points gap categories: {len(matrix.get('points_gap', {}))}")
            
            # Print summary
            print_summary(matrix)
            
            # Save raw records as cache (for re-analysis)
            cache_file = SIGNALS_DIR / "position_records_cache.json"
            cache_file.write_text(json.dumps(records, indent=1, default=str))
            print(f"\nRecords cache saved to {cache_file}")
    
    elif args.query:
        home, away, season, matchday = args.query
        try:
            md = int(matchday)
        except ValueError:
            md = None
        result = query_fixture(home, away, season, md)
        print(json.dumps(result, indent=2, default=str))
    
    elif args.stats:
        if POSITION_MATRIX_FILE.exists():
            matrix = json.loads(POSITION_MATRIX_FILE.read_text())
            print_summary(matrix)
        else:
            print(f"No position matrix found at {POSITION_MATRIX_FILE}")
            print("Run with --build first")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
