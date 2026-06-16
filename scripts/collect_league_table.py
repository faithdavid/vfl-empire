#!/usr/bin/env python3
"""
collect_league_table.py — Automated Standings Collector & Feature Computation
=============================================================================
Fetches current standings from MSport API, computes team-level statistical
features, and saves structured data for the Oracle pipeline.

Output: ~/Documents/Projects/vfl-data/analysis/team_features.json
Usage:  python3 collect_league_table.py
"""

import json
import math
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timezone

from msport_api import get_standings, extract_standings_table, get_results, get_current_match_day_info

# ─── Paths ───────────────────────────────────────────────────────────────────

OUTPUT_FILE = os.path.expanduser(
    "~/Documents/Projects/vfl-data/analysis/team_features.json"
)
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)


# ─── Team Name Normalisation ─────────────────────────────────────────────────

TEAM_ALIASES = {
    "MANCHESTER RED": "MANCHESTER RED",
    "MANCHESTER BLUE": "MANCHESTER BLUE",
    "MANCHESTER CITY": "MANCHESTER BLUE",
    "MANCHESTER UNITED": "MANCHESTER RED",
    "LONDON GUNS": "LONDON GUNS",
    "LONDON GUNNERS": "LONDON GUNS",
    "ARSENAL": "LONDON GUNS",
    "CHELSEA": "CHELSEA",
    "LIVERPOOL": "LIVERPOOL",
    "ASTON VILLA": "ASTON VILLA",
    "TOTTENHAM": "TOTTENHAM",
    "EVERTON": "EVERTON",
    "WOLVERHAMPTON": "WOLVERHAMPTON",
    "WOLVES": "WOLVERHAMPTON",
    "NEWCASTLE": "NEWCASTLE",
    "LEEDS": "LEEDS",
    "FULHAM": "FULHAM",
    "WEST HAM": "WEST HAM",
    "BOURNEMOUTH": "BOURNEMOUTH",
    "BRIGHTON": "BRIGHTON",
    "CRYSTAL PALACE": "CRYSTAL PALACE",
}


def normalize(name: str) -> str:
    """Normalise team name to uppercase canonical form."""
    n = name.strip().upper()
    return TEAM_ALIASES.get(n, n)


# ─── Feature Computation ─────────────────────────────────────────────────────


def compute_form_score(last_five: list) -> float:
    """
    form_score = (wins * 1.0 + draws * 0.5) / 5
    Returns value between 0.0 and 1.0.
    """
    if not last_five:
        return 0.0
    wins = last_five.count("W")
    draws = last_five.count("D")
    return round((wins * 1.0 + draws * 0.5) / len(last_five), 4)


def compute_form_trend(team_stats: dict) -> str:
    """
    Compare lastFive win rate to overall win rate.
    - If lastFive win% > overall win% + margin → "rising"
    - If lastFive win% < overall win% - margin → "declining"
    - Otherwise → "stable"
    """
    played = team_stats["played"]
    won = team_stats["won"]
    last_five = team_stats.get("lastFive", [])
    if played == 0 or not last_five:
        return "stable"

    overall_win_rate = won / played
    last5_wins = last_five.count("W")
    last5_rate = last5_wins / len(last_five)

    margin = 0.08  # 8 percentage points buffer
    if last5_rate > overall_win_rate + margin:
        return "rising"
    elif last5_rate < overall_win_rate - margin:
        return "declining"
    else:
        return "stable"


def compute_rank_change(current_rank: int, team_name: str, standings: list) -> str:
    """Alias for compatibility."""
    return "SAME"


def fetch_live_results(season_id: str, max_md: int) -> dict:
    """Fetch ALL completed matchdays' results from the API and compute per-team actual rates.
    Returns dict: {team_upper: {over_15_rate, under_35_rate, ...}}
    """
    team_data = {}  # team -> {goals_scored[], goals_conceded[], total_goals[]}
    
    for md in range(1, max_md + 1):
        results = get_results(season_id, md)
        if not results:
            continue
        for r in results:
            home = normalize(r.get("homeTeam", ""))
            away = normalize(r.get("awayTeam", ""))
            ft = r.get("fullTime", "0:0")
            try:
                hg, ag = map(int, ft.split(":"))
            except (ValueError, AttributeError):
                continue
            tg = hg + ag
            
            for team, scored, conceded in [(home, hg, ag), (away, ag, hg)]:
                if team not in team_data:
                    team_data[team] = {"goals_scored": [], "goals_conceded": [], "total_goals": [], "btts": 0, "match_count": 0}
                team_data[team]["goals_scored"].append(scored)
                team_data[team]["goals_conceded"].append(conceded)
                team_data[team]["total_goals"].append(tg)
                team_data[team]["match_count"] += 1
            
            # BTTS
            if hg > 0 and ag > 0:
                for team in [home, away]:
                    team_data[team]["btts"] += 1
    
    # Compute rates
    computed = {}
    for team, d in team_data.items():
        n = d["match_count"]
        if n == 0:
            continue
        o15 = sum(1 for tg in d["total_goals"] if tg >= 2) / n
        u35 = sum(1 for tg in d["total_goals"] if tg <= 3) / n
        computed[team] = {
            "over_15_rate": round(o15, 4),
            "under_35_rate": round(u35, 4),
            "avg_goals_scored": round(sum(d["goals_scored"]) / n, 4),
            "avg_goals_conceded": round(sum(d["goals_conceded"]) / n, 4),
            "avg_total_goals": round(sum(d["total_goals"]) / n, 4),
            "btts_rate": round(d["btts"] / n, 4),
            "sample_size": n,
        }
    return computed


def estimate_over_under_rate(avg_total_goals: float, threshold: float) -> float:
    """
    Crude estimate of % of matches going Over/Under a threshold.
    Based on Poisson approximation using avg_total_goals.
    For over_1_5 rate: P(goals >= 2) = 1 - P(0) - P(1)
    where P(k) = (lambda^k * e^(-lambda)) / k!

    For under_3_5 rate: P(goals <= 3) = P(0) + P(1) + P(2) + P(3)
    """
    lam = avg_total_goals
    if lam <= 0:
        return 0.0

    # Poisson probabilities
    p0 = math.exp(-lam)
    p1 = lam * math.exp(-lam)
    p2 = (lam ** 2 / 2) * math.exp(-lam)
    p3 = (lam ** 3 / 6) * math.exp(-lam)

    if threshold == 1.5:
        # Over 1.5 = 1 - P(0) - P(1)
        rate = 1.0 - p0 - p1
    elif threshold == 3.5:
        # Under 3.5 = P(0) + P(1) + P(2) + P(3)
        rate = p0 + p1 + p2 + p3
    else:
        rate = 0.5

    return round(min(max(rate, 0.0), 1.0), 4)


def estimate_clean_sheet_rate(avg_goals_conceded: float) -> float:
    """
    Estimate clean sheet rate from avg goals conceded using Poisson.
    P(GA=0) = e^(-lambda) where lambda = avg_goals_conceded.
    """
    return round(math.exp(-avg_goals_conceded), 4)


def compute_scoring_streak(last_five: list) -> int:
    """
    Count consecutive matches where the team scored.
    Since we only have W/D/L form (not per-match scores), we use a
    conservative heuristic:
    - W implies team scored ≥1 (certain)
    - D is ambiguous (0-0 or scoring draw); exclude for conservatism
    - L is ambiguous; exclude

    Only trailing W's are counted.
    """
    if not last_five:
        return 0
    streak = 0
    for result in reversed(last_five):
        if result == "W":
            streak += 1
        else:
            break
    return streak


# ─── Main ────────────────────────────────────────────────────────────────────


def find_latest_completed_season():
    """Find the most recently completed season from the season selection API."""
    try:
        from msport_api import get_season_list
        seasons = get_season_list()
        if not seasons:
            return None
        # Filter to seasons with at least 1 matchday and sort by startTime descending
        valid = [s for s in seasons if s.get("matchDay") and len(s["matchDay"]) > 0]
        if not valid:
            return None
        valid.sort(key=lambda s: s.get("startTime", 0), reverse=True)
        latest = valid[0]
        mds = latest.get("matchDay", [])
        return {
            "seasonId": latest["seasonId"],
            "seasonName": latest.get("seasonName", "?"),
            "matchDay": max(mds) if mds else 0,
        }
    except Exception as e:
        print(f"   ⚠ Warning: could not fetch season list: {e}")
        return None


def main() -> int:
    print("=" * 58)
    print("  🏆 VFL Empire — League Table Collector")
    print("=" * 58)

    # ── 1. Fetch standings from API ─────────────────────────────────────────
    print("\n📡 Fetching current standings from MSport API...")
    standings_data = get_standings()
    using_pre_season_fallback = False

    if not standings_data:
        # Check if pre-season — try latest completed season as fallback
        print("   ⚠ Current season may be in PRE_SEASON, checking for latest completed season...")
        fallback = find_latest_completed_season()
        if fallback:
            print(f"   📋 Latest completed season: {fallback['seasonName']} ({fallback['seasonId']}) MD {fallback['matchDay']}")
            standings_data = get_standings(season_id=fallback["seasonId"], match_day=fallback["matchDay"])
            using_pre_season_fallback = True

    if not standings_data:
        print("❌ ERROR: Could not fetch standings from MSport API")
        return 1

    table = extract_standings_table(standings_data)
    if not table:
        print("❌ ERROR: Empty standings table")
        return 1

    season_name = standings_data.get("seasonName", "?")
    season_id = standings_data.get("seasonId", "?")
    matchday = standings_data.get("matchDay", 0)
    if using_pre_season_fallback:
        print(f"✅  Season: {season_name} ({season_id}) [PRE-SEASON FALLBACK]")
    else:
        print(f"✅  Season: {season_name} ({season_id})")
    print(f"   Match Day: {matchday}")
    print(f"   Teams in table: {len(table)}")

    # ── 2. Compute features per team ───────────────────────────────────────
    print("\n🧮 Computing team features...")
    
    # ── 2a. Fetch live results for actual goal rates ─────────────────────
    print("📡 Fetching live results for actual goal rates...")
    completed_mds = max(matchday - 1, 0)
    live_rates = fetch_live_results(season_id, completed_mds)  # completed MDs
    print(f"   ✅ Live rates computed for {len(live_rates)} teams")
    
    # Also fetch current MD info if available for more completed MDs
    try:
        md_info = get_current_match_day_info()
        if md_info:
            current_api_md = md_info.get("matchDay", matchday)
    except:
        pass

    teams_output = {}
    computation_buckets = {
        "over_1_5_rates": {},
        "under_3_5_rates": {},
        "avg_total_goals": {},
        "top_scorers": [],
        "worst_defences": [],
    }

    # Build name index for rank change estimation
    # Store previous ranks snapshot if available
    prev_ranks_path = os.path.join(
        os.path.dirname(OUTPUT_FILE), "..", "tables", "prev_ranks.json"
    )
    prev_ranks = {}
    prev_ranks_file = os.path.normpath(prev_ranks_path)
    if os.path.exists(prev_ranks_file):
        try:
            with open(prev_ranks_file) as f:
                prev_ranks = json.load(f)
        except (json.JSONDecodeError, OSError):
            prev_ranks = {}

    # ── Build per-team features ──────────────────────────────────────────────
    for entry in table:
        team_raw = entry.get("teamName", "")
        team_key = normalize(team_raw)

        played = entry.get("played", 0)
        won = entry.get("won", 0)
        draw = entry.get("draw", 0)
        lost = entry.get("lost", 0)
        goals_for = entry.get("goalsFor", 0)
        goals_against = entry.get("goalsAgainst", 0)
        goal_diff = entry.get("goalDifference", 0)
        rank = entry.get("rank", 0)
        points = entry.get("points", 0)
        last_five = entry.get("lastFive", []) or entry.get("form", [])

        # Played = won + draw + lost per spec
        played_computed = won + draw + lost

        # Averages
        avg_gs = round(goals_for / played_computed, 4) if played_computed > 0 else 0.0
        avg_gc = round(goals_against / played_computed, 4) if played_computed > 0 else 0.0
        avg_tg = round((goals_for + goals_against) / played_computed, 4) if played_computed > 0 else 0.0

        # Form features
        form_score = compute_form_score(last_five)
        form_trend = compute_form_trend({
            "played": played_computed,
            "won": won,
            "lastFive": last_five,
        })

        # Rank change
        prev_rank = prev_ranks.get(team_key)
        if prev_rank is not None:
            if rank < prev_rank:
                rank_change = "UP"
            elif rank > prev_rank:
                rank_change = "DOWN"
            else:
                rank_change = "SAME"
        else:
            rank_change = "SAME"

        # Use actual live rates from API results when available, fall back to Poisson
        live = live_rates.get(team_key, {})
        if live.get("sample_size", 0) >= 3:
            over_1_5_rate = live["over_15_rate"]
            under_3_5_rate = live["under_35_rate"]
            actual_avg_gs = live["avg_goals_scored"]
            actual_avg_gc = live["avg_goals_conceded"]
            actual_avg_tg = live["avg_total_goals"]
            btts_rate = live.get("btts_rate", 0.0)
        else:
            # Fall back to Poisson estimates from overall stats
            over_1_5_rate = estimate_over_under_rate(avg_tg, 1.5)
            under_3_5_rate = estimate_over_under_rate(avg_tg, 3.5)
            actual_avg_gs = avg_gs
            actual_avg_gc = avg_gc
            actual_avg_tg = avg_tg
            btts_rate = 0.0
        
        clean_sheet_rate = estimate_clean_sheet_rate(actual_avg_gc)
        scoring_streak = compute_scoring_streak(last_five)

        teams_output[team_key] = {
            "rank": rank,
            "points": points,
            "played": played_computed,
            "won": won,
            "draw": draw,
            "lost": lost,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "goal_diff": goal_diff,
            "form": last_five,
            "rank_change": rank_change,
            "avg_goals_scored": avg_gs,
            "avg_goals_conceded": avg_gc,
            "avg_total_goals": avg_tg,
            "over_1_5_rate": over_1_5_rate,
            "under_3_5_rate": under_3_5_rate,
            "form_score": form_score,
            "form_trend": form_trend,
            "scoring_streak": scoring_streak,
            "clean_sheet_rate": clean_sheet_rate,
        }

        # Bucket accumulators
        computation_buckets["over_1_5_rates"][team_key] = over_1_5_rate
        computation_buckets["under_3_5_rates"][team_key] = under_3_5_rate
        computation_buckets["avg_total_goals"][team_key] = avg_tg

    # ── Top scorers & worst defences ─────────────────────────────────────────
    # Top scorers = teams with highest avg_goals_scored + goals_for
    sorted_by_attack = sorted(
        teams_output.items(),
        key=lambda x: (x[1]["avg_goals_scored"], x[1]["goals_for"]),
        reverse=True,
    )
    computation_buckets["top_scorers"] = [t[0] for t in sorted_by_attack[:5]]

    # Worst defences = teams with highest avg_goals_conceded
    sorted_by_defence = sorted(
        teams_output.items(),
        key=lambda x: (x[1]["avg_goals_conceded"], x[1]["goals_against"]),
        reverse=True,
    )
    computation_buckets["worst_defences"] = [t[0] for t in sorted_by_defence[:5]]

    # ── Compute league averages ──────────────────────────────────────────────
    # Summing only goals_for because goals_for + goals_against counts each goal twice
    all_goals = sum(t["goals_for"] for t in teams_output.values())
    total_matches_entry = sum(t["played"] for t in teams_output.values()) // 2
    avg_goals_per_match = round(all_goals / total_matches_entry, 2) if total_matches_entry > 0 else 0.0

    # Compute home/draw/away rates from the standings data
    # We can get these from total results
    total_wins = sum(t["won"] for t in teams_output.values())
    total_draws = sum(t["draw"] for t in teams_output.values())
    total_matches_season = total_matches_entry  # each match counted twice in wins+losses

    # Each match has one win (home or away) + one loss
    # But we can't split home/away from standings alone
    # Use historical average as approximation
    home_win_rate = 44.89  # historical VFL average
    draw_rate = 23.88
    away_win_rate = 31.23

    # ── Build output ─────────────────────────────────────────────────────────
    timestamp = datetime.now(timezone.utc).isoformat()

    output = {
        "season": season_name,
        "matchday": matchday,
        "timestamp": timestamp,
        "teams": teams_output,
        "computations": computation_buckets,
    }

    # ── Save to file ─────────────────────────────────────────────────────────
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n💾 Saved team features to: {OUTPUT_FILE}")

    # ── Save current ranks for next diff ─────────────────────────────────────
    current_ranks = {team: data["rank"] for team, data in teams_output.items()}
    ranks_dir = os.path.dirname(prev_ranks_file)
    os.makedirs(ranks_dir, exist_ok=True)
    with open(prev_ranks_file, "w") as f:
        json.dump(current_ranks, f, indent=2)

    # ── Print human-readable report ──────────────────────────────────────────
    print("\n" + "=" * 58)
    print(f"  🏆 VFL LEAGUE TABLE — MD {matchday} ({season_name})")
    print("=" * 58)

    for team_key, t in sorted(
        teams_output.items(), key=lambda x: x[1]["rank"]
    ):
        trend_icon = {
            "rising": "🔥 HOT",
            "declining": "⬇ DECLINING",
            "stable": "➡ STABLE",
        }.get(t["form_trend"], "   ?   ")

        form_str = "".join(t["form"]) if t["form"] else "-"
        print(
            f"  {t['rank']:>2}. {team_key:<20} "
            f"{t['points']:>3}pts {t['goal_diff']:>+4}  "
            f"{trend_icon} ({form_str})"
        )

    # ── Form summary ────────────────────────────────────────────────────────
    print("\n📊 Team Form Summary:")
    hot_teams = [
        t for t in teams_output.items()
        if t[1]["form_score"] >= 0.8
    ]
    cold_teams = [
        t for t in teams_output.items()
        if t[1]["form_score"] <= 0.3
    ]
    if hot_teams:
        print(
            "  🔥 HOT (form ≥ 0.80): "
            + ", ".join(t[0] for t in hot_teams)
        )
    if cold_teams:
        print(
            "  🥶 COLD (form ≤ 0.30): "
            + ", ".join(t[0] for t in cold_teams)
        )

    # ── League averages ──────────────────────────────────────────────────────
    print("\n📈 League Averages:")
    print(f"  Avg goals per match: {avg_goals_per_match}")
    print(f"  Home win rate: {home_win_rate}%")
    print(f"  Draw rate: {draw_rate}%")
    print(f"  Away win rate: {away_win_rate}%")

    # ── Top/Bottom performers ────────────────────────────────────────────────
    print("\n⚽ Top Scoring Teams:")
    for t in computation_buckets["top_scorers"][:3]:
        data = teams_output[t]
        print(f"  {data['rank']:>2}. {t} — {data['avg_goals_scored']:.2f} avg/game")

    print("\n🛡️  Worst Defences:")
    for t in computation_buckets["worst_defences"][:3]:
        data = teams_output[t]
        print(f"  {data['rank']:>2}. {t} — {data['avg_goals_conceded']:.2f} conceded/game")

    print("\n✅ Done. Data saved.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
