import csv
from collections import defaultdict
import sys
from pathlib import Path

EMPIRE = Path("/home/ubuntu/faith-workspace/vfl-empire")
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

def normalize_team(name):
    name = name.strip()
    mapping = {
        "Man Blue": "Man Blue", "Man Red": "Man Red",
        "Merseyside Red": "Merseyside Red", "London Reds": "London Reds"
    }
    return mapping.get(name, name)

def get_md_hash(fixtures):
    for f in fixtures:
        f["home_team"] = normalize_team(f["home_team"])
        f["away_team"] = normalize_team(f["away_team"])
    fixtures.sort(key=lambda x: x["home_team"])
    md_str = "|".join([f"{f['home_team']}{f['home_goals']}-{f['away_goals']}{f['away_team']}" for f in fixtures])
    import hashlib
    return hashlib.md5(md_str.encode()).hexdigest()

def main():
    print("Loading actual historical deep market odds from CSV...")
    odds_data = {}
    csv_path = "/home/ubuntu/faith-workspace/vfl-truth-engine/data/vfl_rich_features.csv"
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            s = row["season_name"]
            md = int(row["matchday"]) if row["matchday"] else 0
            ht = normalize_team(row["home_team"])
            at = normalize_team(row["away_team"])
            
            odds_data[(s, md, ht, at)] = {
                "1": float(row["odds_home"]) if row["odds_home"] else 2.0,
                "X": float(row["odds_draw"]) if row["odds_draw"] else 3.2,
                "2": float(row["odds_away"]) if row["odds_away"] else 3.0,
                "O25": float(row["odds_over_25"]) if row["odds_over_25"] else 1.85,
                "U25": float(row["odds_under_25"]) if row["odds_under_25"] else 1.85,
                "GG": float(row["odds_gg"]) if row["odds_gg"] else 1.7,
                "NG": float(row["odds_ng"]) if row["odds_ng"] else 2.1
            }

    print("Loading DB history...")
    sql = """
        SELECT season_name, matchday_number, home_team, away_team, home_goals, away_goals 
        FROM v_results_odd_even_ready 
        ORDER BY season_name ASC, matchday_number ASC, home_team ASC
    """
    with get_db() as cur:
        cur.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        
    seasons = defaultdict(lambda: defaultdict(list))
    for r in rows:
        seasons[r["season_name"]][r["matchday_number"]].append(r)
        
    ordered_seasons = sorted(list(seasons.keys()))
    # Ensure we scan deep enough to hit the seasons that are fully in the CSV too, or at least the last 12
    evaluation_start_idx = max(0, len(ordered_seasons) - 12)
    
    history_md1_hashes = {}
    
    total_tapes_bet = 0
    total_1x2_acca_profit = 0.0
    total_goals_acca_profit = 0.0
    
    STAKE = 500  # 500 Naira
    
    print("\nEvaluating PARLAY (Accumulator) bets over the last 12 seasons...")
    print("===================================================================")
    
    for idx, current_season in enumerate(ordered_seasons):
        mds = seasons[current_season]
        if 1 not in mds or len(mds[1]) != 8:
            continue
            
        current_md1_hash = get_md_hash(mds[1])
        is_evaluation_season = idx >= evaluation_start_idx
        
        if current_md1_hash in history_md1_hashes and is_evaluation_season:
            matched_historical_season = history_md1_hashes[current_md1_hash]
            hist_mds = seasons[matched_historical_season]
            
            total_tapes_bet += 1
            print(f"\n🚨 TAPE MATCH! Live Season: {current_season} matches History: {matched_historical_season}")
            
            streak = 0
            
            for target_md in range(2, 31):
                if target_md not in mds or target_md not in hist_mds:
                    break
                if len(mds[target_md]) != 8 or len(hist_mds[target_md]) != 8:
                    break
                
                # Check if this MD breaks the tape
                curr_hash = get_md_hash(mds[target_md])
                hist_hash = get_md_hash(hist_mds[target_md])
                
                is_perfect_md = (curr_hash == hist_hash)
                
                # Build the 8-Game Parlays
                acca_1x2_odds = 1.0
                acca_goals_odds = 1.0 # Combining Over/Under 2.5 and GG/NG depending on prediction
                
                all_odds_found = True
                
                for f_hist in hist_mds[target_md]:
                    ht = normalize_team(f_hist["home_team"])
                    at = normalize_team(f_hist["away_team"])
                    hg_pred = f_hist["home_goals"]
                    ag_pred = f_hist["away_goals"]
                    
                    # 1X2 Prediction
                    pred_1x2 = "1" if hg_pred > ag_pred else "2" if ag_pred > hg_pred else "X"
                    # Goals Prediction
                    pred_o25 = "O25" if (hg_pred + ag_pred) > 2.5 else "U25"
                    
                    odds = odds_data.get((current_season, target_md, ht, at))
                    if not odds:
                        # Fallback average if not in CSV
                        odds = {"1": 2.2, "X": 3.2, "2": 2.8, "O25": 1.85, "U25": 1.85}
                        
                    acca_1x2_odds *= odds[pred_1x2]
                    acca_goals_odds *= odds[pred_o25]
                
                if is_perfect_md:
                    streak += 1
                    win_1x2 = (acca_1x2_odds * STAKE) - STAKE
                    win_goals = (acca_goals_odds * STAKE) - STAKE
                    
                    total_1x2_acca_profit += win_1x2
                    total_goals_acca_profit += win_goals
                    print(f"  ✅ MD {target_md}: TAPE HELD! 8-Game Parlay WON.")
                    print(f"     1X2 Acca Odds: @{acca_1x2_odds:.2f} | Payout: ₦{acca_1x2_odds * STAKE:,.2f}")
                else:
                    # Divergence! Parley loses.
                    total_1x2_acca_profit -= STAKE
                    total_goals_acca_profit -= STAKE
                    print(f"  ❌ MD {target_md}: TAPE DIVERGED (Broke). Parlay Lost (-₦500).")
                    print(f"  🛑 Ending bet cycle for this tape. Winning Streak: {streak} perfect Matchdays.")
                    break # Stop betting this tape
                    
        history_md1_hashes[current_md1_hash] = current_season

    print("\n=======================================================")
    print("📈 DEEP MARKET PARLAY RESULTS (LAST 12 SEASONS)")
    print("=======================================================")
    print(f"Total Tapes Found & Bet: {total_tapes_bet}")
    print(f"1X2 Parlay Net Profit: ₦{total_1x2_acca_profit:,.2f}")
    print(f"Over/Under 2.5 Parlay Net Profit: ₦{total_goals_acca_profit:,.2f}")
    print("=======================================================")

if __name__ == "__main__":
    main()
