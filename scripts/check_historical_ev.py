import sys
from pathlib import Path
import csv

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

def load_historical_pmf():
    csv_path = EMPIRE / "surge-findings" / "scoreline_by_table_cell_x1.csv"
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
    pmf = load_historical_pmf()
    
    # We will get the last 40 seasons
    sql_seasons = """
        SELECT DISTINCT season_name FROM v_results_odd_even_ready 
        ORDER BY season_name DESC LIMIT 40
    """
    
    sql_events = """
        SELECT season_name, event_id, matchday_number, home_team, away_team, 
               home_goals, away_goals 
        FROM v_results_odd_even_ready 
        WHERE season_name IN (
            SELECT DISTINCT season_name FROM v_results_odd_even_ready 
            ORDER BY season_name DESC LIMIT 40
        )
    """
    
    with get_db() as cur:
        cur.execute(sql_events)
        rows = [dict(r) for r in cur.fetchall()]
        
        # Now we need odds. We will pull CS odds for these events.
        # This might be massive so we only pull CS odds
        event_ids = tuple(r['event_id'] for r in rows if r['event_id'])
        if not event_ids:
            print("No events found.")
            return
            
        # Due to tuple size limits, we fetch in chunks or just join
        cur.execute("""
            SELECT event_id, selection_name, odds 
            FROM vfl_prematch_odds 
            WHERE market_name = 'Correct Score' AND event_id = ANY(%s)
        """, (list(event_ids),))
        
        odds_rows = cur.fetchall()

    odds_map = {}
    for r in odds_rows:
        eid = r['event_id']
        if eid not in odds_map:
            odds_map[eid] = {}
        # MSport CS selection format is usually "1:0"
        odds_map[eid][r['selection_name']] = float(r['odds'])

    # Compute X-1 ranks naively by summing up to MD
    # This is heavy for python, let's just use a simple heuristic for testing or properly do it
    # Actually, we can just use the provided rank computation logic, but for 40 seasons it's 9600 matches.
    # It's fast enough in python.
    
    from collections import defaultdict
    by_season = defaultdict(list)
    for r in rows:
        by_season[r['season_name']].append(r)
        
    TEAMS_16 = [
        "London Guns", "Liverpool", "Manchester Blue", "Manchester Red",
        "Chelsea", "Tottenham", "Aston Villa", "Everton",
        "West Ham", "Brighton", "Leeds", "Wolverhampton",
        "Crystal Palace", "Newcastle", "Fulham", "Bournemouth",
    ]
    
    def compute_table(points, gd, gf):
        def key(t):
            return (-points[t], -gd[t], -gf[t], t)
        ordered = sorted(points.keys(), key=key)
        return {t: i + 1 for i, t in enumerate(ordered)}

    ev_bets_found = 0
    ev_bets_won = 0
    total_ev = 0.0
    total_profit = 0.0
    
    for season, fixtures in by_season.items():
        points = {t: 0 for t in TEAMS_16}
        gd = {t: 0 for t in TEAMS_16}
        gf = {t: 0 for t in TEAMS_16}
        
        for md in range(1, 31):
            ranks = compute_table(points, gd, gf)
            md_fix = [f for f in fixtures if f["matchday_number"] == md]
            
            for f in md_fix:
                h, a = f["home_team"], f["away_team"]
                hr, ar = ranks.get(h, 9), ranks.get(a, 9)
                
                cell = f"H{hr}_A{ar}"
                eid = f["event_id"]
                
                if cell in pmf and eid in odds_map:
                    target_scoreline = pmf[cell]["scoreline"]
                    true_prob = pmf[cell]["prob"]
                    
                    book_odds = odds_map[eid].get(target_scoreline)
                    if not book_odds:
                        hyphen_sl = target_scoreline.replace(":", "-")
                        book_odds = odds_map[eid].get(hyphen_sl)
                        
                    if book_odds and book_odds > 1.0:
                        ev = (true_prob * book_odds) - 1.0
                        if ev > 0.05:
                            ev_bets_found += 1
                            total_ev += ev
                            
                            actual_scoreline = f"{f['home_goals']}:{f['away_goals']}"
                            if actual_scoreline == target_scoreline:
                                ev_bets_won += 1
                                total_profit += (book_odds - 1.0)
                            else:
                                total_profit -= 1.0

            # Update tables for next MD
            for f in md_fix:
                h, a = f["home_team"], f["away_team"]
                hg, ag = int(f["home_goals"]), int(f["away_goals"])
                gf[h] += hg
                gf[a] += ag
                gd[h] += hg - ag
                gd[a] += ag - hg
                if hg > ag:
                    points[h] += 3
                elif hg < ag:
                    points[a] += 3
                else:
                    points[h] += 1
                    points[a] += 1

    print(f"Over the last 40 seasons (9,600 matches):")
    print(f"Total +EV Bets found (>5% Edge): {ev_bets_found}")
    if ev_bets_found > 0:
        print(f"Total Won: {ev_bets_won} (Win Rate: {(ev_bets_won/ev_bets_found)*100:.1f}%)")
        print(f"Average EV identified: +{(total_ev/ev_bets_found)*100:.1f}%")
        print(f"Net Profit (Flat 1u Staking): {total_profit:.2f} units")
        print(f"ROI: {(total_profit/ev_bets_found)*100:.1f}%")

if __name__ == "__main__":
    main()
