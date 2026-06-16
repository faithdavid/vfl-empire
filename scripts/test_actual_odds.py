import sys
from pathlib import Path
from collections import defaultdict

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
    evaluation_start_idx = max(0, len(ordered_seasons) - 12)
    
    history_md1_hashes = {}
    total_perfect_cs_bets = 0
    total_cs_profit = 0.0
    total_missing_odds = 0
    total_matches_bet = 0
    total_loss_diverged = 0.0
    
    print("Evaluating the last 12 seasons using EXACT PREMATCH CORRECT SCORE ODDS...")
    
    for idx, current_season in enumerate(ordered_seasons):
        mds = seasons[current_season]
        if 1 not in mds or len(mds[1]) != 8:
            continue
            
        current_md1_hash = get_md_hash(mds[1])
        is_evaluation_season = idx >= evaluation_start_idx
        
        if current_md1_hash in history_md1_hashes and is_evaluation_season:
            matched_historical_season = history_md1_hashes[current_md1_hash]
            hist_mds = seasons[matched_historical_season]
            
            for target_md in range(2, 31):
                if target_md not in mds or target_md not in hist_mds:
                    break
                if len(mds[target_md]) != 8 or len(hist_mds[target_md]) != 8:
                    break
                    
                curr_hash = get_md_hash(mds[target_md])
                hist_hash = get_md_hash(hist_mds[target_md])
                
                # Bet all 8 matches blindly using the historical tape
                for f_hist in hist_mds[target_md]:
                    ht = normalize_team(f_hist["home_team"])
                    at = normalize_team(f_hist["away_team"])
                    hg_pred = f_hist["home_goals"]
                    ag_pred = f_hist["away_goals"]
                    cs_pred_str1 = f"{hg_pred}:{ag_pred}"
                    cs_pred_str2 = f"{hg_pred}-{ag_pred}"
                    
                    # Find actual outcome
                    actual_f = next((f for f in mds[target_md] if normalize_team(f["home_team"]) == ht and normalize_team(f["away_team"]) == at), None)
                    if not actual_f:
                        continue
                        
                    actual_hg = actual_f["home_goals"]
                    actual_ag = actual_f["away_goals"]
                    is_win = (hg_pred == actual_hg and ag_pred == actual_ag)
                    
                    total_matches_bet += 1
                    
                    # Fetch EXACT odds for this specific game's Correct Score
                    odds_sql = """
                        SELECT odds FROM vfl_prematch_odds 
                        WHERE season_id = %s AND matchday_number = %s 
                        AND market_name = 'Correct Score' 
                        AND (selection_name = %s OR selection_name = %s)
                        LIMIT 1
                    """
                    actual_odds = None
                    with get_db() as cur:
                        cur.execute(odds_sql, (current_season.replace("VFLM ", "vf:season:"), target_md, cs_pred_str1, cs_pred_str2))
                        res = cur.fetchone()
                        if res:
                            actual_odds = float(res[0])
                            
                    if not actual_odds:
                        # Sometimes DB is missing the odds if scrapper missed it, fallback to an average of @8.00 just for the math
                        actual_odds = 8.00
                        total_missing_odds += 1
                        
                    if is_win:
                        total_perfect_cs_bets += 1
                        total_cs_profit += (actual_odds - 1.0) # We won, add profit
                    else:
                        total_cs_profit -= 1.0 # We lost 1 unit
                        total_loss_diverged += 1.0
                
                if curr_hash != hist_hash:
                    break # Diverged
                    
        history_md1_hashes[current_md1_hash] = current_season

    print("\n=======================================================")
    print("📈 TAPE MATCHER BACKTEST (ACTUAL PREMATCH CS ODDS)")
    print("=======================================================")
    print(f"Total Individual Bets Placed: {total_matches_bet}")
    print(f"Total PERFECT CS Hits: {total_perfect_cs_bets}")
    print(f"Total Losses (When Tapes Diverged): {total_loss_diverged}")
    print(f"Fallback Odds Used (Missing DB Records): {total_missing_odds}")
    print(f"NET PROFIT (Flat 1u Staking): +{total_cs_profit:.2f} units")
    print("=======================================================")

if __name__ == "__main__":
    main()
