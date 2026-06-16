import sys
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
import pandas as pd
import numpy as np

sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')

from common.db_manager import get_db
from odds_cluster_classifier import classify_match
from finite_state_filter import FiniteStateFilter

# ──────────────────────────────────────────────────────────────────────
# CONFIG & PATHS
# ──────────────────────────────────────────────────────────────────────
START_SEASON_NUM = 5150  # Backtest evaluation start
END_SEASON_NUM = 5280    # Backtest evaluation end
WARMUP_SEASON_NUM = 4964 # Load all prior matches for H2H warming

# Original Gate constants
ODDS_RANGES_V1 = {
    "O1.5": (1.01, 1.50),
    "O2.5": (1.01, 2.50),
    "U2.5": (1.01, 2.50),
    "U3.5": (1.01, 2.00),
    "GG":   (1.01, 2.20),
    "NG":   (1.01, 2.50),
}

# V2 Gate constants
MARKET_BASELINES = {
    "O1.5": 0.704,
    "O2.5": 0.495,
    "U3.5": 0.730,
    "GG": 0.528,
}

ODDS_RANGES_V2 = {
    "O1.5": (1.01, 1.55),
    "O2.5": (1.01, 2.70),
    "U3.5": (1.01, 2.10),
    "GG":   (1.01, 2.40),
}

# Elite Magnets
ELITE_MAGNETS = {
    frozenset(["Leeds", "Everton"]): {"U3.5": (97.5, "Extreme defensive stalemate history")},
    frozenset(["Leeds", "Fulham"]): {"U3.5": (95.0, "Defensive magnet")},
    frozenset(["Fulham", "Brighton"]): {"U3.5": (90.2, "Tactical stalemate")},
    frozenset(["Wolverhampton", "Manchester Blue"]): {"O1.5": (90.7, "Historically high scoring but watch for recent traps")},
    frozenset(["West Ham", "Fulham"]): {"U3.5": (76.9, "User identified safe magnet")},
    frozenset(["Leeds", "Chelsea"]): {"O1.5": (77.0, "User identified attacking magnet")},
    frozenset(["London Guns", "West Ham"]): {"O1.5": (85.5, "London Derby goal magnet")},
}

# Traps
INVERSE_GEMS = {
    frozenset(["Leeds", "Chelsea"]): {"U1.5": ("O1.5", 77.0, "User pivot to Over 1.5")},
    frozenset(["Everton", "Fulham"]): {"O1.5": ("NG", 75.0, "Historically one-sided or low scoring")},
    frozenset(["Fulham", "Brighton"]): {"O1.5": ("U2.5", 78.2, "Tactical stalemate")},
    frozenset(["West Ham", "Fulham"]): {"O2.5": ("U3.5", 76.9, "User pivot to Under 3.5")},
}

# Import TEAM_PROFILES for Poisson model
from prediction_gate import TEAM_PROFILES

class LeagueTable:
    def __init__(self):
        self.reset()
        
    def reset(self):
        self.teams = defaultdict(lambda: {
            "points": 0, "won": 0, "draw": 0, "lost": 0,
            "gf": 0, "ga": 0, "gd": 0, "form": "", "rank": 8
        })
        
    def update_match(self, home: str, away: str, hg: int, ag: int):
        ht = self.teams[home]
        at = self.teams[away]
        
        ht["gf"] += hg
        ht["ga"] += ag
        ht["gd"] += (hg - ag)
        
        at["gf"] += ag
        at["ga"] += hg
        at["gd"] += (ag - hg)
        
        if hg > ag:
            ht["points"] += 3
            ht["won"] += 1
            ht["form"] = (ht["form"] + "W")[-5:]
            
            at["lost"] += 1
            at["form"] = (at["form"] + "L")[-5:]
        elif ag > hg:
            at["points"] += 3
            at["won"] += 1
            at["form"] = (at["form"] + "W")[-5:]
            
            ht["lost"] += 1
            ht["form"] = (ht["form"] + "L")[-5:]
        else:
            ht["points"] += 1
            ht["draw"] += 1
            ht["form"] = (ht["form"] + "D")[-5:]
            
            at["points"] += 1
            at["draw"] += 1
            at["form"] = (at["form"] + "D")[-5:]
            
    def recompute_ranks(self):
        sorted_teams = sorted(
            self.teams.keys(),
            key=lambda t: (self.teams[t]["points"], self.teams[t]["gd"], self.teams[t]["gf"]),
            reverse=True
        )
        for i, t in enumerate(sorted_teams):
            self.teams[t]["rank"] = i + 1

def run_backtest():
    print("Initializing backtester...")
    fsf = FiniteStateFilter()
    
    # Load cluster rates V2
    cluster_rates = {}
    cluster_rates_path = "/home/ubuntu/faith-workspace/vfl-complete-data/analysis/cluster_market_rates.json"
    if os.path.exists(cluster_rates_path):
        with open(cluster_rates_path) as f:
            cluster_rates = {int(k): v for k, v in json.load(f).items()}
            
    # Step 1: Query all completed matches and their odds chronologically
    print("Querying historical matches and odds from Postgres...")
    with get_db() as cur:
        # First, query all matches with complete odds
        cur.execute("""
            SELECT s.season_name, m.matchday_number, r.id as result_id,
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
            ORDER BY s.season_name ASC, m.matchday_number ASC, r.id ASC
        """)
        all_rows = cur.fetchall()
        
    print(f"Total historical matches loaded: {len(all_rows)}")
    
    # Parse seasons and partition into Warmup vs Backtest
    warmup_matches = []
    backtest_matches = []
    
    for row in all_rows:
        s_name = row[0] # e.g. "VFLM 5182"
        try:
            s_num = int(s_name.split()[1])
        except Exception:
            continue
            
        match_data = {
            "season_name": s_name,
            "season_num": s_num,
            "matchday": row[1],
            "result_id": row[2],
            "home": row[3],
            "away": row[4],
            "total_goals": row[5],
            "hg": row[6],
            "ag": row[7],
            "odds": {
                "O1.5": row[8],
                "O2.5": row[9],
                "GG": row[10],
                "U3.5": row[11]
            }
        }
        
        if s_num < START_SEASON_NUM:
            warmup_matches.append(match_data)
        elif s_num <= END_SEASON_NUM:
            backtest_matches.append(match_data)
            
    print(f"Warmup dataset size: {len(warmup_matches)} matches (prior to Season {START_SEASON_NUM})")
    print(f"Backtest dataset size: {len(backtest_matches)} matches (Seasons {START_SEASON_NUM} to {END_SEASON_NUM})")
    
    # ──────────────────────────────────────────────────────────────────────
    # STATE WARMUP
    # ──────────────────────────────────────────────────────────────────────
    h2h_history = defaultdict(list) # Key: frozenset([home, away]), Val: list of dicts
    rolling_goals = []              # Goals of last 500 matches
    current_season_num = None
    league_table = LeagueTable()
    
    print("Warming up historical H2H and rolling goals...")
    for m in warmup_matches:
        h2h_key = frozenset([m["home"], m["away"]])
        h2h_history[h2h_key].append({
            "tg": m["total_goals"], "hg": m["hg"], "ag": m["ag"]
        })
        rolling_goals.append(m["total_goals"])
        if len(rolling_goals) > 500:
            rolling_goals.pop(0)
            
    # ──────────────────────────────────────────────────────────────────────
    # BACKTEST EVALUATION LOOP
    # ──────────────────────────────────────────────────────────────────────
    print("Running backtest simulation...")
    
    v1_bets_placed = 0
    v1_bets_won = 0
    v1_total_staked = 0.0
    v1_total_profit = 0.0
    v1_equity_curve = [1000.0] # start with 1000 units bankroll
    
    v2_bets_placed = 0
    v2_bets_won = 0
    v2_total_staked = 0.0
    v2_total_profit = 0.0
    v2_equity_curve = [1000.0] # start with 1000 units bankroll
    
    # Markets to test
    markets_to_test = ["O1.5", "O2.5", "U3.5", "GG"]

    
    # Track daily profit
    v1_matchday_profits = defaultdict(float)
    v2_matchday_profits = defaultdict(float)
    
    for idx, m in enumerate(backtest_matches):
        home, away = m["home"], m["away"]
        h2h_key = frozenset([home, away])
        
        # 1. Season change reset for league table
        if m["season_num"] != current_season_num:
            current_season_num = m["season_num"]
            league_table.reset()
            
        # 2. Get current state metrics
        # Rolling goals average (Regime)
        effective_avg = np.mean(rolling_goals) if rolling_goals else 2.59
        regime_name = "DEFENSIVE" if effective_avg < 2.2 else "STANDARD"
        
        # H2H list
        h2h_list = h2h_history[h2h_key]
        n_h2h = len(h2h_list)
        
        # League standing ranks & forms
        ht_data = league_table.teams[home]
        at_data = league_table.teams[away]
        h_rank, h_form = ht_data["rank"], ht_data["form"]
        a_rank, a_form = at_data["rank"], at_data["form"]
        
        # Odds
        odds_dict = m["odds"]
        
        # Evaluate each market
        for market in markets_to_test:
            odds_val = odds_dict.get(market)
            if not odds_val or odds_val <= 1.0:
                continue
                
            # Compute actual outcome of this market
            tg = m["total_goals"]
            hg = m["hg"]
            ag = m["ag"]
            
            won = False
            if market == "O1.5": won = tg > 1.5
            elif market == "O2.5": won = tg > 2.5
            elif market == "U2.5": won = tg < 2.5
            elif market == "U3.5": won = tg < 3.5
            elif market == "GG": won = hg > 0 and ag > 0
            elif market == "NG": won = hg == 0 or ag == 0
            
            # ──────────────────────────────────────────────────────
            # RUN ORIGINAL GATE (V1) IN-MEMORY SIMULATOR
            # ──────────────────────────────────────────────────────
            v1_pass = False
            v1_stake = 0.0
            
            # 1. H2H V1
            h2h_v1_pass = False
            if n_h2h >= 5:
                # Compute rates
                o15_count = sum(1 for x in h2h_list if x["tg"] > 1.5)
                o25_count = sum(1 for x in h2h_list if x["tg"] > 2.5)
                gg_count = sum(1 for x in h2h_list if x["hg"] > 0 and x["ag"] > 0)
                u35_count = sum(1 for x in h2h_list if x["tg"] < 3.5)
                hw_count = sum(1 for x in h2h_list if x["hg"] > x["ag"])
                aw_count = sum(1 for x in h2h_list if x["ag"] > x["hg"])
                
                o15_rate = o15_count / n_h2h
                o25_rate = o25_count / n_h2h
                gg_rate = gg_count / n_h2h
                u35_rate = u35_count / n_h2h
                avg_tg = sum(x["tg"] for x in h2h_list) / n_h2h
                
                if market == "O1.5" and o15_rate >= 0.65: h2h_v1_pass = True
                elif market == "O2.5" and avg_tg >= 2.5: h2h_v1_pass = True
                elif market == "U2.5" and avg_tg <= 2.5: h2h_v1_pass = True
                elif market == "U3.5" and (avg_tg <= 3.0 or (n_h2h >= 20 and u35_rate >= 0.85)): h2h_v1_pass = True
                elif market == "GG" and gg_rate >= 0.50: h2h_v1_pass = True
                elif market == "NG" and gg_rate < 0.50: h2h_v1_pass = True
                
            # 2. Cluster V1
            cluster_v1_pass = False
            res_c = classify_match(odds_dict["O1.5"], odds_dict["O2.5"], odds_dict["GG"], odds_dict["U3.5"])
            c_id = res_c["cluster_id"]
            if c_id >= 0:
                rec_bet = res_c["rec_bet"]
                c_hit_rate = res_c["hit_rate"]
                c_avg_odds = res_c["avg_odds"]
                c_edge = c_hit_rate - (1.0 / c_avg_odds)
                
                if rec_bet == market and c_edge > 0:
                    cluster_v1_pass = True
                elif market == "U3.5" and c_hit_rate >= 0.75:
                    cluster_v1_pass = True
                    
            # 3. Odds Reasonableness V1
            odds_v1_pass = False
            limits_v1 = ODDS_RANGES_V1.get(market)
            if limits_v1 and limits_v1[0] <= odds_val <= limits_v1[1]:
                odds_v1_pass = True
                
            # 4. Regime V1
            regime_v1_pass = False
            if market == "O1.5" and (regime_name != "DEFENSIVE" or effective_avg >= 2.0) and effective_avg >= 1.8:
                regime_v1_pass = True
            elif market == "O2.5" and effective_avg >= 2.4:
                regime_v1_pass = True
            elif market == "U2.5" and (effective_avg <= 2.4 or regime_name == "DEFENSIVE"):
                regime_v1_pass = True
            elif market == "U3.5" and effective_avg <= 2.8:
                regime_v1_pass = True
            elif market == "GG" and regime_name != "DEFENSIVE":
                regime_v1_pass = True
            elif market == "NG" and (regime_name == "DEFENSIVE" or effective_avg <= 2.0):
                regime_v1_pass = True
                
            # 5. Finite State V1
            fs_v1_pass = False
            fs_check = fsf.check_pair(home, away, market)
            if fs_check['verdict'] == 'PASS':
                fs_v1_pass = True
                
            # 6. League Standing V1
            standing_v1_pass = True
            h_last_3 = h_form[-3:]
            a_last_3 = a_form[-3:]
            if market in ["O1.5", "GG"] and h_last_3.count('L') >= 2 and a_last_3.count('L') >= 2:
                if h_rank > 8 and a_rank > 8:
                    standing_v1_pass = False
                    
            # Combine V1 verdict (Strict AND gate)
            v1_passed_gates = [h2h_v1_pass, cluster_v1_pass, odds_v1_pass, regime_v1_pass, fs_v1_pass, standing_v1_pass]
            v1_verdict = all(v1_passed_gates)
            
            # Apply Golden H2H Override
            if not v1_verdict and market in ("O1.5", "U3.5") and n_h2h >= 20:
                h2h_rate = sum(1 for x in h2h_list if (x["tg"] > 1.5 if market == "O1.5" else x["tg"] < 3.5)) / n_h2h
                if h2h_rate >= 0.90:
                    # override if failures are soft (cluster, regime)
                    failures = [i for i, x in enumerate(v1_passed_gates) if not x]
                    # indices: 0=h2h, 1=cluster, 2=odds, 3=regime, 4=fs, 5=standing
                    # soft failures are 1, 3
                    if all(f in (1, 3) for f in failures):
                        v1_verdict = True
                        
            # Apply Magnet Override
            if not v1_verdict:
                magnet_key = frozenset([home, away])
                if magnet_key in ELITE_MAGNETS and market in ELITE_MAGNETS[magnet_key]:
                    failures = [i for i, x in enumerate(v1_passed_gates) if not x]
                    if all(f in (1, 3) for f in failures):
                        v1_verdict = True
                        
            # Stake sizing V1
            if v1_verdict:
                v1_stake_pct = 0.04
                # Reduce for low confidence
                # Original confidence relies on sample size + hit rate. Let's approximate:
                h2h_hr = sum(1 for x in h2h_list if (x["tg"] > 1.5 if market == "O1.5" else x["tg"] < 3.5)) / n_h2h if n_h2h > 0 else 0.5
                conf = min(n_h2h / 20.0, 1.0) * 30 + h2h_hr * 70
                if conf < 70: v1_stake_pct -= 0.01
                v1_stake = max(0.01, v1_stake_pct)
                
            # ──────────────────────────────────────────────────────
            # RUN ROBUST BAYESIAN GATE (V2) IN-MEMORY SIMULATOR
            # ──────────────────────────────────────────────────────
            # 1. H2H Posterior (Beta-Binomial)
            baseline = MARKET_BASELINES.get(market, 0.5)
            N_prior = 8.0
            alpha_0 = N_prior * baseline
            beta_0 = N_prior * (1.0 - baseline)
            
            if n_h2h > 0:
                if market == "O1.5": k = sum(1 for x in h2h_list if x["tg"] > 1.5)
                elif market == "O2.5": k = sum(1 for x in h2h_list if x["tg"] > 2.5)
                elif market == "U2.5": k = sum(1 for x in h2h_list if x["tg"] < 2.5)
                elif market == "U3.5": k = sum(1 for x in h2h_list if x["tg"] < 3.5)
                elif market == "GG": k = sum(1 for x in h2h_list if x["hg"] > 0 and x["ag"] > 0)
                elif market == "NG": k = sum(1 for x in h2h_list if x["hg"] == 0 or x["ag"] == 0)
                p_h2h = (k + alpha_0) / (n_h2h + N_prior)
            else:
                p_h2h = baseline
                
            # 2. Cluster probability V2
            p_cluster = baseline
            if c_id >= 0 and cluster_rates:
                c_info = cluster_rates.get(c_id)
                if c_info:
                    m_info = c_info.get("markets", {}).get(market)
                    if m_info:
                        p_cluster = m_info["hit_rate"]
                        
            # 3. Finite State Probability V2 (smoothed)
            p_fs = baseline
            stats_fs = fsf.get_pair_stats(home, away)
            if stats_fs and stats_fs.get('matches', 0) > 0:
                n_fs = stats_fs.get('matches', 0)
                if market == "O1.5": rate_fs = stats_fs.get('o15_rate', 70.0) / 100.0
                elif market == "O2.5": rate_fs = stats_fs.get('o25_rate', 50.0) / 100.0
                elif market == "U2.5": rate_fs = (100.0 - stats_fs.get('o25_rate', 50.0)) / 100.0
                elif market == "U3.5": rate_fs = stats_fs.get('u35_rate', 73.0) / 100.0
                elif market == "GG": rate_fs = stats_fs.get('gg_rate', 53.0) / 100.0
                elif market == "NG": rate_fs = (100.0 - stats_fs.get('gg_rate', 53.0)) / 100.0
                k_fs = round(rate_fs * n_fs)
                p_fs = (k_fs + 8.0 * baseline) / (n_fs + 8.0)
                
            # 4. Poisson Probability V2
            hp_avg = TEAM_PROFILES.get(home, {"avg_goals": 2.59})["avg_goals"]
            ap_avg = TEAM_PROFILES.get(away, {"avg_goals": 2.59})["avg_goals"]
            lambda_h = 1.35 * (hp_avg / 2.59)
            lambda_a = 1.24 * (ap_avg / 2.59)
            lam = lambda_h + lambda_a
            
            p_poisson = baseline
            if market == "O1.5": p_poisson = 1.0 - math.exp(-lam) - lam * math.exp(-lam)
            elif market == "O2.5": p_poisson = 1.0 - math.exp(-lam) - lam * math.exp(-lam) - (lam**2 / 2.0) * math.exp(-lam)
            elif market == "U2.5": p_poisson = math.exp(-lam) * (1.0 + lam + (lam**2 / 2.0))
            elif market == "U3.5": p_poisson = math.exp(-lam) * (1.0 + lam + (lam**2 / 2.0) + (lam**3 / 6.0))
            elif market == "GG": p_poisson = (1.0 - math.exp(-lambda_h)) * (1.0 - math.exp(-lambda_a))
            elif market == "NG": p_poisson = 1.0 - (1.0 - math.exp(-lambda_h)) * (1.0 - math.exp(-lambda_a))
            
            # Combine Ensemble Probability
            p_combined = (0.30 * p_h2h) + (0.30 * p_cluster) + (0.20 * p_fs) + (0.20 * p_poisson)
            
            # Edge
            edge = p_combined - (1.0 / odds_val)
            
            # Evaluate V2 Gate Verdict
            v2_verdict = True
            
            # Hard filter A: Value Edge requirement (>= 2.5%)
            if edge < 0.025:
                v2_verdict = False
                
            # Hard filter B: Odds boundaries
            limits_v2 = ODDS_RANGES_V2.get(market)
            if limits_v2 and not (limits_v2[0] <= odds_val <= limits_v2[1]):
                v2_verdict = False
                
            # Hard filter C: Finite State block if strictly failed with extremely low rate
            if fs_check['verdict'] == 'FAIL' and fs_check.get('rate', 0.8) < (baseline - 0.15):
                v2_verdict = False
                
            # Stake sizing V2 (Fractional Kelly clamped 1-4%)
            v2_stake = 0.0
            if v2_verdict:
                raw_k = (p_combined * odds_val - 1.0) / (odds_val - 1.0)
                fractional_k = 0.10 * raw_k
                v2_stake = max(0.01, min(0.04, round(fractional_k, 3)))
                
            # ──────────────────────────────────────────────────────
            # SIMULATE BETS & RECORD P&L
            # ──────────────────────────────────────────────────────
            # Compute result multiplier: Odds - 1 if won, -1 if lost
            multiplier = (odds_val - 1.0) if won else -1.0
            
            if v1_verdict:
                v1_bets_placed += 1
                v1_stake_units = v1_stake * v1_equity_curve[-1]
                profit = v1_stake_units * multiplier
                v1_total_staked += v1_stake_units
                v1_total_profit += profit
                v1_matchday_profits[f"{m['season_name']}_MD{m['matchday']}"] += profit
                if won:
                    v1_bets_won += 1
                    
            if v2_verdict:
                v2_bets_placed += 1
                v2_stake_units = v2_stake * v2_equity_curve[-1]
                profit = v2_stake_units * multiplier
                v2_total_staked += v2_stake_units
                v2_total_profit += profit
                v2_matchday_profits[f"{m['season_name']}_MD{m['matchday']}"] += profit
                if won:
                    v2_bets_won += 1
                    
        # 3. Post-matchday updates (once all fixtures are processed)
        # Update H2H history
        h2h_history[h2h_key].append({
            "tg": tg, "hg": hg, "ag": ag
        })
        # Update rolling goals
        rolling_goals.append(tg)
        if len(rolling_goals) > 500:
            rolling_goals.pop(0)
            
        # Update league table
        league_table.update_match(home, away, hg, ag)
        
        # Re-compute ranks at end of each matchday round (every 8 matches)
        if idx % 8 == 0:
            league_table.recompute_ranks()
            
        # Matchday equity curves (update at the end of each round)
        if idx % 8 == 0:
            v1_equity_curve.append(1000.0 + v1_total_profit)
            v2_equity_curve.append(1000.0 + v2_total_profit)

    # ──────────────────────────────────────────────────────────────────────
    # SUMMARIZE RESULTS
    # ──────────────────────────────────────────────────────────────────────
    v1_yield = v1_total_profit / v1_total_staked * 100.0 if v1_total_staked > 0 else 0.0
    v2_yield = v2_total_profit / v2_total_staked * 100.0 if v2_total_staked > 0 else 0.0
    
    v1_win_rate = v1_bets_won / v1_bets_placed * 100.0 if v1_bets_placed > 0 else 0.0
    v2_win_rate = v2_bets_won / v2_bets_placed * 100.0 if v2_bets_placed > 0 else 0.0
    
    # Drawdowns
    def calc_max_drawdown(equity_series):
        peak = equity_series[0]
        max_dd = 0.0
        for val in equity_series:
            if val > peak:
                peak = val
            dd = (peak - val) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd * 100.0

    v1_max_dd = calc_max_drawdown(v1_equity_curve)
    v2_max_dd = calc_max_drawdown(v2_equity_curve)
    
    print("\n==========================================")
    print("BACKTEST RESULTS (Seasons 5150 to 5280)")
    print("==========================================")
    print(f"Gating Engine V1 (Original):")
    print(f"  - Bets Placed:   {v1_bets_placed}")
    print(f"  - Win Rate:      {v1_win_rate:.2f}% ({v1_bets_won}/{v1_bets_placed})")
    print(f"  - Total Staked:  {v1_total_staked:.2f} units")
    print(f"  - Total Profit:  {v1_total_profit:.2f} units")
    print(f"  - Net Yield:     {v1_yield:+.2f}%")
    print(f"  - Max Drawdown:  {v1_max_dd:.2f}%")
    print(f"  - Final Bankroll: {v1_equity_curve[-1]:.2f} units (Initial: 1000)")
    
    print("\nGating Engine V2 (Robust Bayesian):")
    print(f"  - Bets Placed:   {v2_bets_placed}")
    print(f"  - Win Rate:      {v2_win_rate:.2f}% ({v2_bets_won}/{v2_bets_placed})")
    print(f"  - Total Staked:  {v2_total_staked:.2f} units")
    print(f"  - Total Profit:  {v2_total_profit:.2f} units")
    print(f"  - Net Yield:     {v2_yield:+.2f}%")
    print(f"  - Max Drawdown:  {v2_max_dd:.2f}%")
    print(f"  - Final Bankroll: {v2_equity_curve[-1]:.2f} units (Initial: 1000)")
    print("==========================================")
    
    # Save backtest statistics
    out_data = {
        "v1": {
            "bets_placed": v1_bets_placed,
            "win_rate": round(v1_win_rate, 2),
            "total_staked": round(v1_total_staked, 2),
            "total_profit": round(v1_total_profit, 2),
            "yield": round(v1_yield, 2),
            "max_dd": round(v1_max_dd, 2),
            "final_bankroll": round(v1_equity_curve[-1], 2),
            "equity_curve": [round(x, 2) for x in v1_equity_curve[::50]] # downsampled for size
        },
        "v2": {
            "bets_placed": v2_bets_placed,
            "win_rate": round(v2_win_rate, 2),
            "total_staked": round(v2_total_staked, 2),
            "total_profit": round(v2_total_profit, 2),
            "yield": round(v2_yield, 2),
            "max_dd": round(v2_max_dd, 2),
            "final_bankroll": round(v2_equity_curve[-1], 2),
            "equity_curve": [round(x, 2) for x in v2_equity_curve[::50]] # downsampled for size
        }
    }
    
    out_file = "/home/ubuntu/faith-workspace/vfl-complete-data/analysis/backtest_comparison.json"
    with open(out_file, 'w') as f:
        json.dump(out_data, f, indent=2)
    print(f"Results saved to {out_file}")

if __name__ == "__main__":
    run_backtest()
