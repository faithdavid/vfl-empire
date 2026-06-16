#!/usr/bin/env python3
import csv
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
    from vfl_live_predictor import extract_odds, normalize_team
except ImportError as e:
    print(f"Could not import live modules: {e}")
    sys.exit(1)

TEAMS_16 = [
    "London Guns", "Liverpool", "Manchester Blue", "Manchester Red",
    "Chelsea", "Tottenham", "Aston Villa", "Everton",
    "West Ham", "Brighton", "Leeds", "Wolverhampton",
    "Crystal Palace", "Newcastle", "Fulham", "Bournemouth",
]

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("ev_sniper")

def compute_ranks_from_db():
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

def load_historical_pmf():
    csv_path = EMPIRE / "surge-findings" / "scoreline_by_table_cell_x1.csv"
    if not csv_path.exists():
        logger.error(f"Could not find historical PMF at {csv_path}")
        return {}
    
    pmf = {}
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            group = row["group"]
            scoreline = row["top1_scoreline"]
            pct = float(row["top1_pct"]) / 100.0
            pmf[group] = {"scoreline": scoreline, "prob": pct}
    return pmf

def main():
    logger.info("=========================================")
    logger.info("🎯 VFL CORRECT SCORE EV SNIPER ENGINE 🎯")
    logger.info("=========================================")
    
    ranks = compute_ranks_from_db()
    pmf = load_historical_pmf()
    
    match_days = get_event_list()
    if not match_days:
        logger.warning("No live events found from MSport API. Awaiting next matchday cycle.")
        return
        
    md = match_days[0]
    season = md.get("seasonId", "Unknown")
    matchday = md.get("matchDay", "Unknown")
    
    logger.info(f"\nScanning Upcoming MSport Matchday {matchday} (Season {season})...")
    
    found_edge = False
    
    for event in md.get("events", []):
        home_raw = event.get("homeTeamName", "Unknown")
        away_raw = event.get("awayTeamName", "Unknown")
        home = normalize_team(home_raw)
        away = normalize_team(away_raw)
        
        hr = ranks.get(home, 8)
        ar = ranks.get(away, 8)
        
        odds_dict = extract_odds(event)
        cell = f"H{hr}_A{ar}"
        
        if cell in pmf and "Correct Score" in odds_dict:
            target_scoreline = pmf[cell]["scoreline"]
            true_prob = pmf[cell]["prob"]
            true_odds = 1.0 / true_prob if true_prob > 0 else 0
            
            # MSport sometimes formats CS as "1:0" or "1-0"
            msport_cs_odds = odds_dict["Correct Score"]
            book_odds = None
            
            # Check for exactly "1:0"
            if target_scoreline in msport_cs_odds:
                book_odds = msport_cs_odds[target_scoreline]
            else:
                # Try hyphens "1-0"
                hyphen_sl = target_scoreline.replace(":", "-")
                if hyphen_sl in msport_cs_odds:
                    book_odds = msport_cs_odds[hyphen_sl]
            
            if book_odds and book_odds > 1.0:
                ev = (true_prob * book_odds) - 1.0
                if ev > 0.05:  # We found a +5% EV edge!
                    found_edge = True
                    logger.info(f"\n🚨 +EV SIGNAL DETECTED 🚨")
                    logger.info(f"Fixture: {home} (Rank {hr}) vs {away} (Rank {ar})")
                    logger.info(f"Target Scoreline: {target_scoreline}")
                    logger.info(f"Historical True Odds: {true_odds:.2f} ({true_prob*100:.1f}%)")
                    logger.info(f"MSport Book Odds: {book_odds:.2f}")
                    logger.info(f"Expected Value (EV): +{ev*100:.1f}%")
                    logger.info(f"Recommendation: Bet {target_scoreline} @ {book_odds:.2f}")

    if not found_edge:
        logger.info("\nNo edges > +5% EV found in this matchday. Patience is profitable. ⏳")
        
    logger.info("=========================================\n")

if __name__ == "__main__":
    main()
