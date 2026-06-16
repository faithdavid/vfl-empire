import sys
from pathlib import Path
from collections import defaultdict
import datetime

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

def main():
    print("Initiating Deep Algebraic & Markov State Scanner...")
    
    sql = """
        SELECT season_name, matchday_number, home_team, away_team, 
               home_goals, away_goals 
        FROM v_results_odd_even_ready 
        ORDER BY season_name ASC, matchday_number ASC
    """
    
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        
    print(f"Loaded {len(rows)} fixtures for sequence modeling.")
    
    # We need to compute the running state (Points, Form) for every team, every season.
    # Group rows by season
    seasons = defaultdict(list)
    for r in rows:
        seasons[r["season_name"]].append(r)
        
    # Categorization buckets
    # State = (Matchday, Points_Diff, Home_Form_Last_3, Away_Form_Last_3)
    state_outcomes = defaultdict(list)
    
    # Points trigger state
    # State = (Matchday, Home_Points, Away_Points)
    points_outcomes = defaultdict(list)
    
    print("Computing X-1, X-2, X-3 Markov forms and Points Quotas...")

    for season, fixtures in seasons.items():
        points = defaultdict(int)
        form = defaultdict(list) # Stores last results as 'W', 'D', 'L'
        
        # Sort fixtures by matchday just in case
        fixtures.sort(key=lambda x: x["matchday_number"])
        
        # Group by matchday to process round by round
        by_md = defaultdict(list)
        for f in fixtures:
            by_md[f["matchday_number"]].append(f)
            
        for md in range(1, 31):
            if md not in by_md: continue
            
            for f in by_md[md]:
                h = f["home_team"]
                a = f["away_team"]
                hg = int(f["home_goals"])
                ag = int(f["away_goals"])
                
                # Current state (before this match is played, i.e., X-1)
                h_pts = points[h]
                a_pts = points[a]
                pts_diff = h_pts - a_pts
                
                # Get last 3 form
                h_form = "".join(form[h][-3:]) if form[h] else "NONE"
                a_form = "".join(form[a][-3:]) if form[a] else "NONE"
                
                # Record the outcome
                res = "H" if hg > ag else ("A" if hg < ag else "D")
                scoreline = f"{hg}:{ag}"
                o25 = 1 if (hg + ag) > 2 else 0
                
                outcome = {"res": res, "scoreline": scoreline, "o25": o25}
                
                # Only track form states if we are past MD 3 to have valid sequences
                if md > 3:
                    state_key = (md, pts_diff, h_form, a_form)
                    state_outcomes[state_key].append(outcome)
                
                # Points trigger key
                pts_key = (md, h_pts, a_pts)
                points_outcomes[pts_key].append(outcome)
                
                # Update points and form AFTER match
                if hg > ag:
                    points[h] += 3
                    form[h].append('W')
                    form[a].append('L')
                elif hg < ag:
                    points[a] += 3
                    form[h].append('L')
                    form[a].append('W')
                else:
                    points[h] += 1
                    points[a] += 1
                    form[h].append('D')
                    form[a].append('D')

    print("\n=========================================")
    print("🔍 PHASE 1: EXACT MARKOV FORM & POINTS DIFF LOCKS (>95% Consistency, n>=15)")
    print("=========================================")
    
    def analyze_bucket(buckets, desc_format):
        found = 0
        for state, outcomes in buckets.items():
            n = len(outcomes)
            if n < 15: continue
            
            hw = sum(1 for o in outcomes if o["res"] == "H") / n
            aw = sum(1 for o in outcomes if o["res"] == "A") / n
            dw = sum(1 for o in outcomes if o["res"] == "D") / n
            o25 = sum(o["o25"] for o in outcomes) / n
            
            msg = None
            if hw >= 0.95: msg = f"HOME WIN {hw*100:.1f}% (n={n})"
            elif aw >= 0.95: msg = f"AWAY WIN {aw*100:.1f}% (n={n})"
            elif dw >= 0.95: msg = f"DRAW {dw*100:.1f}% (n={n})"
            elif o25 >= 0.95: msg = f"OVER 2.5 {o25*100:.1f}% (n={n})"
            elif o25 <= 0.05: msg = f"UNDER 2.5 {(1-o25)*100:.1f}% (n={n})"
            
            if msg:
                desc = desc_format(state)
                print(f"🚨 {desc} -> {msg}")
                found += 1
        return found
        
    f1 = analyze_bucket(state_outcomes, lambda s: f"MD {s[0]} | PtsDiff: {s[1]:+d} | Home Form: {s[2]} | Away Form: {s[3]}")
    if f1 == 0: print("No extreme Markov sequences found meeting the strict thresholds.")
    
    print("\n=========================================")
    print("🎯 PHASE 2: POINT QUOTA RUBBER-BANDING (>95% Consistency, n>=15)")
    print("=========================================")
    
    f2 = analyze_bucket(points_outcomes, lambda s: f"MD {s[0]} | Home has {s[1]} pts, Away has {s[2]} pts")
    if f2 == 0: print("No exact point-quota limits found meeting the strict thresholds.")
    
    print("\nScan Complete.")

if __name__ == "__main__":
    main()
