import sys
from pathlib import Path
from collections import defaultdict

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

def main():
    print("Fetching entire canonical history to find 100% (or near 100%) deterministic anomalies...")
    
    # Query all results
    sql = """
        SELECT season_name, matchday_number, home_team, away_team, 
               home_goals, away_goals 
        FROM v_results_odd_even_ready 
    """
    
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        
    print(f"Loaded {len(rows)} fixtures from history.")
    
    # 1. Categorization: Team vs Team on a Specific Matchday
    # dict key: (home_team, away_team, matchday)
    # value: list of outcomes
    
    matchday_clashes = defaultdict(list)
    team_matchdays = defaultdict(list)
    
    for r in rows:
        h = r["home_team"]
        a = r["away_team"]
        md = r["matchday_number"]
        hg = int(r["home_goals"])
        ag = int(r["away_goals"])
        
        scoreline = f"{hg}:{ag}"
        res = "H" if hg > ag else ("A" if hg < ag else "D")
        o25 = 1 if (hg + ag) > 2 else 0
        gg = 1 if (hg > 0 and ag > 0) else 0
        
        outcome = {
            "scoreline": scoreline,
            "res": res,
            "o25": o25,
            "gg": gg
        }
        
        matchday_clashes[(h, a, md)].append(outcome)
        team_matchdays[(h, md, "Home")].append(outcome)
        team_matchdays[(a, md, "Away")].append(outcome)

    print("\nScanning for Extreme Matchday Constraints (n >= 20)...")
    
    locks_found = 0
    
    def print_if_extreme(group_name, outcomes):
        nonlocal locks_found
        n = len(outcomes)
        if n < 20: return
        
        hw = sum(1 for o in outcomes if o["res"] == "H") / n
        aw = sum(1 for o in outcomes if o["res"] == "A") / n
        dw = sum(1 for o in outcomes if o["res"] == "D") / n
        o25 = sum(o["o25"] for o in outcomes) / n
        gg = sum(o["gg"] for o in outcomes) / n
        
        sl_counts = defaultdict(int)
        for o in outcomes:
            sl_counts[o["scoreline"]] += 1
            
        top_sl = max(sl_counts.items(), key=lambda x: x[1])
        top_sl_pct = top_sl[1] / n
        
        # Thresholds for "near 100% consistency"
        msg = None
        if hw >= 0.90: msg = f"{group_name} -> HOME WIN {hw*100:.1f}% (n={n})"
        elif aw >= 0.90: msg = f"{group_name} -> AWAY WIN {aw*100:.1f}% (n={n})"
        elif dw >= 0.70: msg = f"{group_name} -> DRAW {dw*100:.1f}% (n={n})"
        elif o25 >= 0.95: msg = f"{group_name} -> OVER 2.5 {o25*100:.1f}% (n={n})"
        elif o25 <= 0.05: msg = f"{group_name} -> UNDER 2.5 {(1-o25)*100:.1f}% (n={n})"
        elif top_sl_pct >= 0.40: msg = f"{group_name} -> SCORELINE {top_sl[0]} {top_sl_pct*100:.1f}% (n={n})"
        
        if msg:
            print(f"🚨 ANOMALY: {msg}")
            locks_found += 1

    # Check Specific Matchups on Specific Matchdays
    for (h, a, md), outcomes in matchday_clashes.items():
        print_if_extreme(f"MD {md} | {h} vs {a}", outcomes)
        
    # Check Specific Teams playing on Specific Matchdays (regardless of opponent)
    for (t, md, loc), outcomes in team_matchdays.items():
        print_if_extreme(f"MD {md} | {t} ({loc})", outcomes)
        
    if locks_found == 0:
        print("No hard-coded 90%+ deterministic locks found for these basic categorizations.")
        print("The RNG algorithm appears to distribute variance smoothly across matchdays.")

if __name__ == "__main__":
    main()
