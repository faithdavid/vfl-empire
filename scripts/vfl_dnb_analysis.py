#!/usr/bin/env python3
"""
vfl_dnb_analysis.py
Backtest Draw No Bet (DNB) strategy on history.db matches.
"""

import sqlite3
import json
import sys
import re

DB_PATH = "/home/ubuntu/faith-workspace/vfl-complete-dataset/databases/history.db"

def parse_season_num(season_str):
    if not season_str:
        return None
    match = re.search(r'\d+', season_str)
    if match:
        return int(match.group())
    return None

def normalize_outcome(outcome_str):
    if not outcome_str:
        return None
    o = outcome_str.strip().upper()
    if o in ('H', 'HOME'):
        return 'H'
    if o in ('D', 'DRAW'):
        return 'D'
    if o in ('A', 'AWAY'):
        return 'A'
    return None

def get_odds_bracket(odds):
    if odds < 1.50:
        return "<1.50"
    elif odds < 2.00:
        return "1.50-1.99"
    elif odds < 3.00:
        return "2.00-2.99"
    else:
        return "3.00+"

def compute_metrics(bets):
    n = len(bets)
    if n == 0:
        return {
            "n": 0,
            "win_rate_excl_push": 0.0,
            "push_rate": 0.0,
            "roi_flat_stake": 0.0,
            "avg_dnb_fair_odds": 0.0
        }
    
    wins = sum(1 for b in bets if b['settlement'] == 'WIN')
    pushes = sum(1 for b in bets if b['settlement'] == 'PUSH')
    losses = sum(1 for b in bets if b['settlement'] == 'LOSS')
    
    total_profit = sum(b['profit'] for b in bets)
    total_fair_odds = sum(b['dnb_fair_odds'] for b in bets)
    
    win_loss_total = wins + losses
    win_rate_excl_push = (wins / win_loss_total) if win_loss_total > 0 else 0.0
    push_rate = pushes / n
    roi_flat_space = total_profit / n
    avg_dnb_fair_odds = total_fair_odds / n
    
    return {
        "n": n,
        "win_rate_excl_push": round(win_rate_excl_push, 4),
        "push_rate": round(push_rate, 4),
        "roi_flat_stake": round(roi_flat_space, 4),
        "avg_dnb_fair_odds": round(avg_dnb_fair_odds, 4)
    }

def main():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
    except Exception as e:
        print(f"Error opening database: {e}", file=sys.stderr)
        sys.exit(1)
        
    query = """
        SELECT id, season, day, home, away, oh, od, oa, outcome, h, a 
        FROM matches 
        WHERE oh > 0 AND od > 0 AND oa > 0 AND oh IS NOT NULL AND outcome IS NOT NULL
    """
    
    try:
        rows = cursor.execute(query).fetchall()
    except Exception as e:
        print(f"Error running query: {e}", file=sys.stderr)
        conn.close()
        sys.exit(1)
        
    conn.close()
    
    bets = []
    
    for row in rows:
        oh = row['oh']
        od = row['od']
        oa = row['oa']
        outcome_raw = row['outcome']
        season_raw = row['season']
        
        normalized_o = normalize_outcome(outcome_raw)
        if not normalized_o:
            continue
            
        season_num = parse_season_num(season_raw)
        if season_num is None:
            continue
            
        # 2. Strip margin
        sum_inv = (1.0 / oh) + (1.0 / od) + (1.0 / oa)
        margin = sum_inv - 1.0
        
        fair_p_home = (1.0 / oh) / sum_inv
        fair_p_draw = (1.0 / od) / sum_inv
        fair_p_away = (1.0 / oa) / sum_inv
        
        # 3. DNB Home/Away implied & fair odds
        sum_home_away = fair_p_home + fair_p_away
        if sum_home_away <= 0:
            continue
            
        dnb_home_implied = fair_p_home / sum_home_away
        dnb_away_implied = fair_p_away / sum_home_away
        
        # Determine the Naive Favorite: lower 1X2 odds
        # If they are equal, we break the tie by choosing Home as favorite
        if oh <= oa:
            fav_side = 'H'
            fav_odds = oh
            dnb_implied = dnb_home_implied
        else:
            fav_side = 'A'
            fav_odds = oa
            dnb_implied = dnb_away_implied
            
        if dnb_implied <= 0:
            continue
            
        dnb_fair_odds = 1.0 / dnb_implied
        
        # 4. DNB settlement
        if normalized_o == 'D':
            settlement = 'PUSH'
            profit = 0.0
        elif normalized_o == fav_side:
            settlement = 'WIN'
            profit = dnb_fair_odds - 1.0
        else:
            settlement = 'LOSS'
            profit = -1.0
            
        bets.append({
            'season_num': season_num,
            'fav_odds': fav_odds,
            'dnb_fair_odds': dnb_fair_odds,
            'settlement': settlement,
            'profit': profit
        })
        
    # Categorize and aggregate
    total_matches_analyzed = len(bets)
    
    # Overall
    overall = compute_metrics(bets)
    
    # Brackets
    bracket_keys = ["<1.50", "1.50-1.99", "2.00-2.99", "3.00+"]
    by_bracket = {k: [] for k in bracket_keys}
    for b in bets:
        br = get_odds_bracket(b['fav_odds'])
        by_bracket[br].append(b)
        
    by_odds_bracket_results = {}
    for br in bracket_keys:
        by_odds_bracket_results[br] = compute_metrics(by_bracket[br])
        
    # Season Types
    by_season_type = {
        "<=5047": [],
        ">5047": []
    }
    for b in bets:
        if b['season_num'] <= 5047:
            by_season_type["<=5047"].append(b)
        else:
            by_season_type[">5047"].append(b)
            
    by_season_type_results = {
        "<=5047": compute_metrics(by_season_type["<=5047"]),
        ">5047": compute_metrics(by_season_type[">5047"])
    }
    
    # Output report
    report = {
        "total_matches_analyzed": total_matches_analyzed,
        "overall_results": overall,
        "by_odds_bracket": by_odds_bracket_results,
        "by_season_type": by_season_type_results,
        "naive_favorite_results": by_odds_bracket_results  # Same per bracket since they both analyze the naive favorite strategy
    }
    
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
