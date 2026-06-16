import sys
import json
import math
import os
from collections import defaultdict
import pandas as pd
import numpy as np

sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')

from common.db_manager import get_db
from odds_cluster_classifier import classify_match
from finite_state_filter import FiniteStateFilter
from prediction_gate import TEAM_PROFILES

def run_best_pick_backtest():
    print("Loading data...")
    with get_db() as cur:
        cur.execute("""
            SELECT DISTINCT ON (r.id)
                   s.season_name, m.matchday_number, r.id as result_id,
                   r.home_team, r.away_team, r.total_goals, r.home_goals, r.away_goals,
                   o.o15, o.o25, o.gg, o.u35
            FROM vfl_results_v2 r
            JOIN vfl_matchdays m ON r.matchday_id = m.id
            JOIN vfl_seasons s ON m.season_id = s.id
            JOIN vfl_odds_v2 o ON (
                o.season_id = s.season_id
                AND o.matchday_number = m.matchday_number
                AND o.home_team = r.home_team
                AND o.away_team = r.away_team
            )
            WHERE o.o15 IS NOT NULL AND o.o25 IS NOT NULL AND o.u35 IS NOT NULL AND o.gg IS NOT NULL
              AND r.total_goals IS NOT NULL
            ORDER BY r.id ASC, o.id DESC
        """)
        rows = cur.fetchall()
        
    print(f"Loaded {len(rows)} matches.")
    
    START_SEASON_NUM = 5200
    END_SEASON_NUM = 5280
    
    warmup = []
    backtest = []
    
    for row in rows:
        s_name = row[0]
        try:
            s_num = int(s_name.split()[1])
        except:
            continue
        m_data = {
            "season_name": s_name,
            "season_num": s_num,
            "matchday": row[1],
            "result_id": row[2],
            "home": row[3],
            "away": row[4],
            "total_goals": row[5],
            "hg": row[6],
            "ag": row[7],
            "odds": {"O1.5": row[8], "O2.5": row[9], "GG": row[10], "U3.5": row[11]}
        }
        if s_num < START_SEASON_NUM:
            warmup.append(m_data)
        elif s_num <= END_SEASON_NUM:
            backtest.append(m_data)
            
    # Warmup H2H
    h2h_history = defaultdict(list)
    rolling_goals = []
    for m in warmup:
        key = frozenset([m["home"], m["away"]])
        h2h_history[key].append({"tg": m["total_goals"], "hg": m["hg"], "ag": m["ag"]})
        rolling_goals.append(m["total_goals"])
        if len(rolling_goals) > 500: rolling_goals.pop(0)
        
    # Load cluster rates V2
    cluster_rates = {}
    cluster_rates_path = "/home/ubuntu/faith-workspace/vfl-complete-data/analysis/cluster_market_rates.json"
    if os.path.exists(cluster_rates_path):
        with open(cluster_rates_path) as f:
            cluster_rates = {int(k): v for k, v in json.load(f).items()}
            
    fsf = FiniteStateFilter()
    
    markets = ["O1.5", "O2.5", "U3.5", "GG"]
    MARKET_BASELINES = {"O1.5": 0.704, "O2.5": 0.495, "U3.5": 0.730, "GG": 0.528}
    ODDS_RANGES_V2 = {"O1.5": (1.01, 1.55), "O2.5": (1.01, 2.70), "U3.5": (1.01, 2.10), "GG": (1.01, 2.40)}
    
    # Process matches by matchday round
    matchdays = defaultdict(list)
    for m in backtest:
        key = (m["season_name"], m["matchday"])
        matchdays[key].append(m)

    # Test different edge thresholds
    for min_edge in [0.025, 0.04, 0.06, 0.08]:
        v2_bankroll = 1000.0
        v2_placed, v2_won, v2_profit = 0, 0, 0.0
        
        # Reset H2H for new simulation
        h2h_history = defaultdict(list)
        rolling_goals = []
        for m in warmup:
            key = frozenset([m["home"], m["away"]])
            h2h_history[key].append({"tg": m["total_goals"], "hg": m["hg"], "ag": m["ag"]})
            rolling_goals.append(m["total_goals"])
            if len(rolling_goals) > 500: rolling_goals.pop(0)
            
        for md_key, fixtures in sorted(matchdays.items()):
            candidate_bets = []
            
            for m in fixtures:
                home, away = m["home"], m["away"]
                h2h_key = frozenset([home, away])
                
                effective_avg = np.mean(rolling_goals) if rolling_goals else 2.59
                h2h_list = h2h_history[h2h_key]
                n_h2h = len(h2h_list)
                odds_dict = m["odds"]
                
                res_c = classify_match(odds_dict["O1.5"], odds_dict["O2.5"], odds_dict["GG"], odds_dict["U3.5"])
                c_id = res_c["cluster_id"]
                
                for market in markets:
                    odds_val = odds_dict[market]
                    if not odds_val or odds_val <= 1.0: continue
                    
                    baseline = MARKET_BASELINES.get(market, 0.5)
                    alpha_0 = 8.0 * baseline
                    beta_0 = 8.0 * (1.0 - baseline)
                    if n_h2h > 0:
                        if market == "O1.5": k = sum(1 for x in h2h_list if x["tg"] > 1.5)
                        elif market == "O2.5": k = sum(1 for x in h2h_list if x["tg"] > 2.5)
                        elif market == "U3.5": k = sum(1 for x in h2h_list if x["tg"] < 3.5)
                        elif market == "GG": k = sum(1 for x in h2h_list if x["hg"] > 0 and x["ag"] > 0)
                        p_h2h = (k + alpha_0) / (n_h2h + 8.0)
                    else:
                        p_h2h = baseline
                        
                    p_cluster = baseline
                    if c_id >= 0 and cluster_rates:
                        c_info = cluster_rates.get(c_id)
                        if c_info and market in c_info.get("markets", {}):
                            p_cluster = c_info["markets"][market]["hit_rate"]
                            
                    p_fs = baseline
                    stats_fs = fsf.get_pair_stats(home, away)
                    if stats_fs and stats_fs.get('matches', 0) > 0:
                        n_fs = stats_fs['matches']
                        rate_fs = stats_fs.get('o15_rate' if market=="O1.5" else 'o25_rate' if market=="O2.5" else 'u35_rate' if market=="U3.5" else 'gg_rate', 50) / 100.0
                        p_fs = (rate_fs * n_fs + 8.0 * baseline) / (n_fs + 8.0)
                        
                    hp = TEAM_PROFILES.get(home, {"avg_goals": 2.59})["avg_goals"]
                    ap = TEAM_PROFILES.get(away, {"avg_goals": 2.59})["avg_goals"]
                    lambda_h = 1.35 * (hp / 2.59)
                    lambda_a = 1.24 * (ap / 2.59)
                    lam = lambda_h + lambda_a
                    
                    p_poisson = baseline
                    if market == "O1.5": p_poisson = 1.0 - math.exp(-lam) - lam * math.exp(-lam)
                    elif market == "O2.5": p_poisson = 1.0 - math.exp(-lam) - lam * math.exp(-lam) - (lam**2 / 2.0) * math.exp(-lam)
                    elif market == "U3.5": p_poisson = math.exp(-lam) * (1.0 + lam + (lam**2 / 2.0) + (lam**3 / 6.0))
                    elif market == "GG": p_poisson = (1.0 - math.exp(-lambda_h)) * (1.0 - math.exp(-lambda_a))
                    
                    p_combined = (0.30 * p_h2h) + (0.30 * p_cluster) + (0.20 * p_fs) + (0.20 * p_poisson)
                    edge = p_combined - (1.0 / odds_val)
                    
                    v2_verdict = True
                    if edge < min_edge: v2_verdict = False
                    limits_v2 = ODDS_RANGES_V2.get(market)
                    if limits_v2 and not (limits_v2[0] <= odds_val <= limits_v2[1]): v2_verdict = False
                    
                    fs_check = fsf.check_pair(home, away, market)
                    if fs_check['verdict'] == 'FAIL' and fs_check.get('rate', 0.8) < (baseline - 0.15):
                        v2_verdict = False
                        
                    if v2_verdict:
                        raw_k = (p_combined * odds_val - 1.0) / (odds_val - 1.0)
                        v2_stake = max(0.01, min(0.04, round(0.10 * raw_k, 3)))
                        
                        candidate_bets.append({
                            "match": m,
                            "market": market,
                            "odds": odds_val,
                            "edge": edge,
                            "stake": v2_stake,
                            "home": home,
                            "away": away
                        })
                        
            if candidate_bets:
                candidate_bets.sort(key=lambda x: x["edge"], reverse=True)
                best_bet = candidate_bets[0]
                
                m = best_bet["match"]
                market = best_bet["market"]
                odds_val = best_bet["odds"]
                stake = best_bet["stake"]
                
                tg, hg, ag = m["total_goals"], m["hg"], m["ag"]
                won = False
                if market == "O1.5": won = tg > 1.5
                elif market == "O2.5": won = tg > 2.5
                elif market == "U3.5": won = tg < 3.5
                elif market == "GG": won = hg > 0 and ag > 0
                
                multiplier = (odds_val - 1.0) if won else -1.0
                
                v2_placed += 1
                v2_stake_u = stake * v2_bankroll
                profit = v2_stake_u * multiplier
                v2_profit += profit
                v2_bankroll += profit
                if won: v2_won += 1
                
            for m in fixtures:
                home, away = m["home"], m["away"]
                key = frozenset([home, away])
                h2h_history[key].append({"tg": m["total_goals"], "hg": m["hg"], "ag": m["ag"]})
                rolling_goals.append(m["total_goals"])
                if len(rolling_goals) > 500: rolling_goals.pop(0)

        # Print summary for this threshold
        win_rate = v2_won / v2_placed * 100 if v2_placed > 0 else 0
        net_yield = v2_profit / (v2_placed * 25.0) * 100 if v2_placed > 0 else 0 # approx
        print(f"Edge Threshold: {min_edge*100:.1f}% -> Placed: {v2_placed:<4d} Win Rate: {win_rate:.2f}% Profit: {v2_profit:+.2f} units (Bankroll: {v2_bankroll:.2f})")

if __name__ == "__main__":
    run_best_pick_backtest()


if __name__ == "__main__":
    run_best_pick_backtest()
