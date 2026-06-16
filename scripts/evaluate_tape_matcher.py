import sys
from pathlib import Path
from collections import defaultdict
import hashlib

EMPIRE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EMPIRE / "services"))
from common.db_manager import get_db

def get_md_hash(fixtures):
    fixtures.sort(key=lambda x: x["home_team"])
    md_str = "|".join([f"{f['home_team']}{f['home_goals']}-{f['away_goals']}{f['away_team']}" for f in fixtures])
    return hashlib.md5(md_str.encode()).hexdigest()

def main():
    print("Initializing Tape Matcher Walk-Forward Backtest...")
    
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
        
    ordered_seasons = sorted(seasons.keys())
    
    history_md1_hashes = {}
    
    total_tapes_matched = 0
    total_perfect_matches_predicted = 0
    divergence_depths = []
    
    print(f"Building historical dictionary and evaluating the last 12 seasons (out of {len(ordered_seasons)} total)...")
    
    evaluation_start_idx = max(0, len(ordered_seasons) - 12)
    
    for idx, current_season in enumerate(ordered_seasons):
        mds = seasons[current_season]
        if 1 not in mds or len(mds[1]) != 8:
            continue
            
        current_md1_hash = get_md_hash(mds[1])
        
        is_evaluation_season = idx >= evaluation_start_idx
        
        # Did we see this MD1 tape in the past?
        if current_md1_hash in history_md1_hashes and is_evaluation_season:
            matched_historical_season = history_md1_hashes[current_md1_hash]
            hist_mds = seasons[matched_historical_season]
            
            total_tapes_matched += 1
            
            # We ride the tape until it diverges
            md_depth = 1
            for target_md in range(2, 31):
                if target_md not in mds or target_md not in hist_mds:
                    break
                
                if len(mds[target_md]) != 8 or len(hist_mds[target_md]) != 8:
                    break
                    
                curr_hash = get_md_hash(mds[target_md])
                hist_hash = get_md_hash(hist_mds[target_md])
                
                if curr_hash == hist_hash:
                    total_perfect_matches_predicted += 8
                    md_depth = target_md
                else:
                    break
                    
            divergence_depths.append(md_depth)
        
        # Always add to history for future matches
        history_md1_hashes[current_md1_hash] = current_season

    print("\n=======================================================")
    print("📈 TAPE MATCHER BACKTEST RESULTS (LAST 12 SEASONS ONLY)")
    print("=======================================================")
    print(f"Total Seasons Evaluated: {len(ordered_seasons)}")
    print(f"Total MD1 Tapes Matched (Triggered Bets): {total_tapes_matched}")
    
    if total_tapes_matched > 0:
        print(f"Total Individual Fixtures PERFECTLY Predicted (100% CS Hit): {total_perfect_matches_predicted}")
        avg_depth = sum(divergence_depths) / len(divergence_depths)
        max_depth = max(divergence_depths)
        print(f"Average Tape Divergence Depth: Matchday {avg_depth:.1f}")
        print(f"Deepest Tape Run: Matchday {max_depth} (That's {(max_depth-1)*8} perfect consecutive bets!)")
        
        # Contextualize Profit
        # Average CS odds are ~ 8.00.
        # Predicting 1 fixture gives +7 units profit.
        estimated_profit = total_perfect_matches_predicted * 7.0
        # Assume we lose 8 bets on the divergence matchday (where the tape breaks)
        estimated_losses = total_tapes_matched * 8.0 
        net = estimated_profit - estimated_losses
        
        print("\n💰 FINANCIAL ESTIMATION (Flat 1u Staking per match)")
        print(f"Estimated Units Won from perfect hits: +{estimated_profit:.1f}u")
        print(f"Estimated Units Lost when tapes diverge: -{estimated_losses:.1f}u")
        print(f"Net Profit: {net:+.1f} units")
    else:
        print("No tapes matched in a walk-forward scenario.")
        
    print("=======================================================\n")

if __name__ == "__main__":
    main()
