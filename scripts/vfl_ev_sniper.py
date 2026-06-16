#!/usr/bin/env python3
import json
import logging
import sys
from pathlib import Path

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
try:
    from common.db_manager import get_db
except ImportError:
    print("Could not import get_db")
    sys.exit(1)

sys.path.insert(0, str(EMPIRE / "scripts"))
try:
    from msport_api import get_event_list
    from vfl_live_predictor import extract_odds, normalize_team, TEAMS_16
except ImportError as e:
    print(f"Could not import live modules: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ev_sniper")

def compute_ranks_from_db():
    # We fetch all results from the current active season to compute the X-1 table
    # For now, we will approximate by fetching the most recent results.
    sql = """
        SELECT home_team, away_team, home_goals, away_goals 
        FROM v_results_odd_even_ready 
        WHERE season_name = (SELECT season_name FROM v_results_odd_even_ready ORDER BY result_captured_at DESC LIMIT 1)
    """
    points = {t: 0 for t in TEAMS_16}
    gd = {t: 0 for t in TEAMS_16}
    gf = {t: 0 for t in TEAMS_16}
    
    with get_db() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        
    for r in rows:
        h, a = r['home_team'], r['away_team']
        hg, ag = r['home_goals'], r['away_goals']
        
        if h not in points: points[h] = 0
        if a not in points: points[a] = 0
        if h not in gd: gd[h] = 0
        if a not in gd: gd[a] = 0
        if h not in gf: gf[h] = 0
        if a not in gf: gf[a] = 0
        
        gf[h] += hg
        gf[a] += ag
        gd[h] += (hg - ag)
        gd[a] += (ag - hg)
        
        if hg > ag:
            points[h] += 3
        elif hg < ag:
            points[a] += 3
        else:
            points[h] += 1
            points[a] += 1

    def key(t):
        return (-points[t], -gd[t], -gf[t], t)
        
    ordered = sorted(points.keys(), key=key)
    ranks = {t: i + 1 for i, t in enumerate(ordered)}
    return ranks

def get_historical_pmf(hr, ar):
    # Fetch historical scoreline distribution for this table cell (e.g. H12_A1)
    # We will use rank_diff or exact cell to prevent small sample sizes
    sql = """
        WITH cte AS (
            SELECT home_goals, away_goals, COUNT(*) as c
            FROM (
                SELECT r.home_goals, r.away_goals,
                       (SELECT count(*) FROM v_results_odd_even_ready r2 WHERE r2.season_name=r.season_name AND r2.matchday_number < r.matchday_number) as dummy
                FROM v_results_odd_even_ready r
                -- We approximate cell grouping by rank difference to preserve N size
            ) x
            GROUP BY home_goals, away_goals
        )
        SELECT * FROM cte;
    """
    pass

def main():
    print("VFL +EV Sniper Engine Initiated...")
    ranks = compute_ranks_from_db()
    print("Current League Table Ranks Computed.")
    
    match_days = get_event_list()
    if not match_days:
        print("No live events found from MSport.")
        return
        
    md = match_days[0]
    print(f"Analyzing {len(md.get('events', []))} fixtures for +EV...")
    
    # Basic output for demonstration
    for event in md.get("events", []):
        home_raw = event.get("homeTeamName", "Unknown")
        away_raw = event.get("awayTeamName", "Unknown")
        home = normalize_team(home_raw)
        away = normalize_team(away_raw)
        
        hr = ranks.get(home, 8)
        ar = ranks.get(away, 8)
        
        odds_dict = extract_odds(event.get("markets", []))
        
        print(f"\n[Fixture] {home} (Rank {hr}) vs {away} (Rank {ar})")
        # Identify sharpest historical cell EV here
        cell = f"H{hr}_A{ar}"
        print(f"  Targeting Table Cell: {cell}")
        if "Correct Score" in odds_dict:
            # E.g. MSport 0:1 odds
            cs_odds = odds_dict["Correct Score"]
            print(f"  Live CS Odds detected.")

if __name__ == "__main__":
    main()
