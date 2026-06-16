import json
import pandas as pd
from collections import defaultdict

def analyze_odds_performance():
    with open('/home/ubuntu/faith-workspace/vfl-complete-data/master_mirror_index.json') as f:
        data = json.load(f)
    
    records = []
    for s_name, seasons in data.items():
        for md, fixes in seasons.items():
            for fx in fixes:
                hg, ag = map(int, fx["result"].split("-"))
                total = hg + ag
                odds = fx.get("odds", {})
                
                records.append({
                    "u25_odds": odds.get("u25"),
                    "o15_odds": odds.get("o15"),
                    "total_goals": total,
                    "is_u25": total < 2.5,
                    "is_o15": total > 1.5,
                    "home_win": hg > ag,
                    "away_win": ag > hg,
                    "draw": hg == ag
                })
    
    df = pd.DataFrame(records)
    df = df.dropna(subset=['u25_odds', 'o15_odds'])
    
    # 1. Under 2.5 Analysis by Odds Range
    print("=== Under 2.5 Performance by Odds Range ===")
    df['u25_range'] = pd.cut(df['u25_odds'], bins=[1.0, 1.5, 1.7, 1.9, 2.1, 3.0])
    u25_stats = df.groupby('u25_range', observed=True)['is_u25'].mean()
    print(u25_stats)
    
    # 2. Over 1.5 Performance by Odds Range
    print("\n=== Over 1.5 Performance by Odds Range ===")
    df['o15_range'] = pd.cut(df['o15_odds'], bins=[1.0, 1.15, 1.25, 1.35, 1.5, 2.0])
    o15_stats = df.groupby('o15_range', observed=True)['is_o15'].mean()
    print(o15_stats)
    
    # 3. Best "Lock" Candidates
    print("\n=== High Fidelity Odds States (N > 50) ===")
    # Look for specific odds where outcome is > 85%
    locks = df.groupby('u25_odds')['is_u25'].agg(['mean', 'count'])
    locks = locks[locks['count'] > 50].sort_values('mean', ascending=False)
    print("Top U2.5 Locks:")
    print(locks.head(10))

if __name__ == "__main__":
    analyze_odds_performance()
