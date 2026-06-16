import sys
import json
import os
from collections import defaultdict

sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/scripts')
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')

from common.db_manager import get_db
from odds_cluster_classifier import classify_match

# Market definitions
MARKET_VERIFY = {
    "O1.5": lambda tg, hg, ag: 1 if tg > 1.5 else 0,
    "O2.5": lambda tg, hg, ag: 1 if tg > 2.5 else 0,
    "U2.5": lambda tg, hg, ag: 1 if tg < 2.5 else 0,
    "U3.5": lambda tg, hg, ag: 1 if tg < 3.5 else 0,
    "GG":   lambda tg, hg, ag: 1 if hg > 0 and ag > 0 else 0,
    "NG":   lambda tg, hg, ag: 1 if hg == 0 or ag == 0 else 0,
}

def calculate():
    print("Loading matches from PostgreSQL...")
    with get_db() as cur:
        # Load last 100,000 matches to have a highly recent yet large sample
        cur.execute("""
            SELECT r.home_team, r.away_team, r.total_goals, r.home_goals, r.away_goals,
                   o.o15, o.o25, o.gg, o.u35, o.u25, o.ng
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
            ORDER BY r.id DESC
            LIMIT 100000
        """)
        rows = cur.fetchall()
    
    print(f"Loaded {len(rows)} matches. Classifying into clusters...")
    
    cluster_counts = defaultdict(int)
    cluster_wins = defaultdict(lambda: defaultdict(int))
    cluster_odds_sum = defaultdict(lambda: defaultdict(float))
    cluster_odds_count = defaultdict(lambda: defaultdict(int))
    
    for row in rows:
        home_team, away_team, total_goals, home_goals, away_goals, o15, o25, gg, u35, u25, ng = row
        
        # Classify
        res = classify_match(o15, o25, gg, u35)
        cid = res['cluster_id']
        if cid == -1:
            continue
            
        cluster_counts[cid] += 1
        
        # Verify outcomes and record odds
        odds_dict = {
            "O1.5": o15,
            "O2.5": o25,
            "U2.5": u25 or (1.0 / (1.0/o25) if o25 else None), # fallback
            "U3.5": u35,
            "GG": gg,
            "NG": ng or (1.0 / (1.0/gg) if gg else None), # fallback
        }
        
        for mkt, verify_fn in MARKET_VERIFY.items():
            hit = verify_fn(total_goals, home_goals, away_goals)
            if hit:
                cluster_wins[cid][mkt] += 1
                
            odds_val = odds_dict.get(mkt)
            if odds_val and odds_val > 1.0:
                cluster_odds_sum[cid][mkt] += odds_val
                cluster_odds_count[cid][mkt] += 1
                
    # Build results
    rates = {}
    for cid in range(8):
        count = cluster_counts[cid]
        rates[cid] = {
            "count": count,
            "markets": {}
        }
        print(f"\nCluster {cid} (n={count} matches):")
        for mkt in MARKET_VERIFY.keys():
            wins = cluster_wins[cid][mkt]
            hit_rate = wins / count if count > 0 else 0
            
            avg_odds = 0
            odds_c = cluster_odds_count[cid][mkt]
            if odds_c > 0:
                avg_odds = cluster_odds_sum[cid][mkt] / odds_c
                
            edge = hit_rate - (1.0 / avg_odds) if avg_odds > 0 else 0
            
            rates[cid]["markets"][mkt] = {
                "hit_rate": round(hit_rate, 4),
                "avg_odds": round(avg_odds, 2),
                "edge": round(edge, 4)
            }
            print(f"  - {mkt:5s}: Hit Rate = {hit_rate*100:5.1f}%, Avg Odds = {avg_odds:.2f}, Edge = {edge*100:+5.1f}%")
            
    # Save to file
    out_path = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis/cluster_market_rates.json'
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(rates, f, indent=2)
    print(f"\nSaved cluster market rates to {out_path}")

if __name__ == "__main__":
    calculate()
