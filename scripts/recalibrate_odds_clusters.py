#!/usr/bin/env python3
"""
Recalibrate Odds Clusters (Team-Match Join)
===========================================
Analyzes recent match history to update the hit rates and best recommendations
for each of the 8 odds fingerprints (archetypes).

Joins odds and results based on team names, matchday, and season ID.
"""

import sqlite3
import json
import os
import sys
from datetime import datetime

# Import classifier logic
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')
from odds_cluster_classifier import (
    CLUSTER_CENTROIDS, classify_match_full_odds, MARKET_VERIFY,
    CLUSTER_CONFIG_PATH, NUM_CLUSTERS
)

# Database Paths
BASE_DIR = '/home/ubuntu/faith-workspace/vfl-complete-data'
ODDS_DB = os.path.join(BASE_DIR, 'databases', 'vfl_odds.db')
RESULTS_DB = os.path.join(BASE_DIR, 'databases', 'vfl_results.db')

def recalibrate(lookback=5000):
    print(f"--- Recalibrating Odds Clusters (Lookback: {lookback} matches) ---")
    
    conn_odds = sqlite3.connect(ODDS_DB)
    conn_res = sqlite3.connect(RESULTS_DB)
    conn_odds.row_factory = sqlite3.Row
    conn_res.row_factory = sqlite3.Row
    
    # 1. Load results into memory
    res_query = f"""
        SELECT event_id, home_team, away_team, match_day, season_id, 
               total_goals, home_goals, away_goals
        FROM results
        ORDER BY captured_at DESC
        LIMIT {lookback}
    """
    res_rows = conn_res.execute(res_query).fetchall()
    results_map = {}
    for r in res_rows:
        key = (r['home_team'], r['away_team'], r['match_day'], r['season_id'])
        results_map[key] = r
    
    print(f"Loaded {len(results_map)} results.")
    
    # 2. Load events with deep odds
    # We first find which seasons we are looking at to narrow down the query
    season_ids = list(set(r['season_id'] for r in res_rows))
    placeholders = ','.join('?' * len(season_ids))
    
    odds_events_query = f"""
        SELECT event_id, home_team, away_team, match_day, season_id
        FROM event_details
        WHERE season_id IN ({placeholders})
    """
    odds_events = conn_odds.execute(odds_events_query, season_ids).fetchall()
    
    # 3. Join and get deep odds
    joined_data = []
    for oe in odds_events:
        key = (oe['home_team'], oe['away_team'], oe['match_day'], oe['season_id'])
        if key in results_map:
            # We have a match! Now get the odds for this event_id
            joined_data.append({
                'odds_eid': oe['event_id'],
                'res': results_map[key]
            })
            
    print(f"Joined {len(joined_data)} matches with results and odds events.")
    
    if not joined_data:
        print("No matches joined. Check team name consistency.")
        return
        
    # 4. Fetch deep odds in batches
    batch_size = 500
    all_event_odds = {}
    for i in range(0, len(joined_data), batch_size):
        batch = joined_data[i:i+batch_size]
        eids = [m['odds_eid'] for m in batch]
        placeholders = ','.join('?' * len(eids))
        
        odds_query = f"""
            SELECT event_id, market_name, specifiers, selection_name, odds
            FROM deep_markets
            WHERE event_id IN ({placeholders})
              AND (market_name = 'Over/Under' OR market_name = 'GG/NG')
        """
        rows = conn_odds.execute(odds_query, eids).fetchall()
        for row in rows:
            eid = row['event_id']
            if eid not in all_event_odds: all_event_odds[eid] = {}
            
            mkt, spec, sel, odds = row['market_name'], row['specifiers'], row['selection_name'], row['odds']
            if mkt == 'Over/Under':
                if spec == 'total=1.5' and sel == 'Over 1.5': all_event_odds[eid]['o15'] = odds
                if spec == 'total=1.5' and sel == 'Under 1.5': all_event_odds[eid]['u15'] = odds
                if spec == 'total=2.5' and sel == 'Over 2.5': all_event_odds[eid]['o25'] = odds
                if spec == 'total=2.5' and sel == 'Under 2.5': all_event_odds[eid]['u25'] = odds
                if spec == 'total=3.5' and sel == 'Under 3.5': all_event_odds[eid]['u35'] = odds
            elif mkt == 'GG/NG':
                if sel == 'Yes': all_event_odds[eid]['gg'] = odds
                if sel == 'No': all_event_odds[eid]['ng'] = odds

    # 5. Process and Aggregate
    stats = {i: {'total': 0, 'wins': {m: 0 for m in MARKET_VERIFY}, 'sum_odds': {m: 0 for m in MARKET_VERIFY}} 
             for i in range(NUM_CLUSTERS)}
    
    # Map MARKET_VERIFY keys to all_event_odds keys
    MARKET_TO_OD_KEY = {
        'O1.5': 'o15', 'O2.5': 'o25', 'U2.5': 'u25', 'U3.5': 'u35', 'GG': 'gg', 'NG': 'ng'
    }

    count = 0
    for item in joined_data:
        eid = item['odds_eid']
        od = all_event_odds.get(eid)
        if not od or not all(k in od for k in ['o15', 'o25', 'gg', 'u35']):
            continue
            
        res_cls = classify_match_full_odds(od)
        cid = res_cls['cluster_id']
        if cid == -1: continue
        
        stats[cid]['total'] += 1
        count += 1
        
        res = item['res']
        tg, hg, ag = res['total_goals'], res['home_goals'], res['away_goals']
        for market, verify_fn in MARKET_VERIFY.items():
            if verify_fn(tg, hg, ag):
                stats[cid]['wins'][market] += 1
            
            od_key = MARKET_TO_OD_KEY.get(market)
            if od_key in od:
                stats[cid]['sum_odds'][market] += od[od_key]

    print(f"Classified {count} matches.")
    
    # 6. Generate Recommendations
    new_recs = []
    for cid in range(NUM_CLUSTERS):
        c_stats = stats[cid]
        total = c_stats['total']
        
        if total < 50: # Increased threshold for reliability
            print(f"Cluster {cid}: Insufficient data ({total}), keeping defaults.")
            new_recs.append(None)
            continue
            
        best_market = None
        best_edge = -999
        best_hit_rate = 0
        best_avg_odds = 0
        
        for market in MARKET_VERIFY:
            hit_rate = c_stats['wins'][market] / total
            avg_odds = c_stats['sum_odds'][market] / total if c_stats['sum_odds'][market] > 0 else 1.5
            edge = hit_rate - (1.0 / avg_odds)
            
            if edge > best_edge:
                best_edge = edge
                best_market = market
                best_hit_rate = hit_rate
                best_avg_odds = avg_odds
                
        new_recs.append({
            'market': best_market,
            'hit_rate': round(best_hit_rate, 3),
            'avg_odds': round(best_avg_odds, 2),
            'label': f"{best_market} {best_hit_rate*100:.1f}% @{best_avg_odds:.2f} (Edge: {best_edge*100:+.1f}%)"
        })
        print(f"Cluster {cid}: {new_recs[-1]['label']} [N={total}]")

    # 7. Save Config
    final_recs = []
    from odds_cluster_classifier import DEFAULT_CLUSTER_RECOMMENDATIONS
    for i, rec in enumerate(new_recs):
        if rec:
            final_recs.append(rec)
        else:
            final_recs.append(DEFAULT_CLUSTER_RECOMMENDATIONS[i])
            
    config = {
        'last_updated': datetime.now().isoformat(),
        'lookback': lookback,
        'recommendations': final_recs
    }
    
    os.makedirs(os.path.dirname(CLUSTER_CONFIG_PATH), exist_ok=True)
    with open(CLUSTER_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"Successfully saved recalibrated config to {CLUSTER_CONFIG_PATH}")

if __name__ == "__main__":
    recalibrate()
