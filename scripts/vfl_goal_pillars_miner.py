import json
import pandas as pd
import os

def mine_goal_pillars():
    print("🔍 RANSACKING THE ABANDONED PILLAR (GOALS MARKET)...")
    data_file = '/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json'
    
    with open(data_file, 'r') as f:
        data = json.load(f)
        
    df = pd.DataFrame(data)
    
    # CRITICAL RULES FOR A PILLAR
    # 1. Must have happened at least 10 times in history
    df = df[df['occurrences'] >= 10].copy()
    
    pillars = []
    
    for _, row in df.iterrows():
        key = {
            "home": row['home'],
            "away": row['away'],
            "home_tier": row['home_tier'],
            "away_tier": row['away_tier']
        }
        
        # We only take the absolute highest confidence limits
        
        # Under 3.5 Goals (100% ONLY)
        if row['w_u35_rate'] == 1.0:
            pillars.append({**key, "market": "Under 3.5", "confidence": "100%", "occurrences": row['occurrences']})
            
        # Over 1.5 Goals (>= 98%)
        if row['w_o15_rate'] >= 0.98:
            conf = f"{row['w_o15_rate']*100:.1f}%"
            pillars.append({**key, "market": "Over 1.5", "confidence": conf, "occurrences": row['occurrences']})
            
        # Under 2.5 Goals (>= 95%)
        if row['w_u25_rate'] >= 0.95:
            conf = f"{row['w_u25_rate']*100:.1f}%"
            pillars.append({**key, "market": "Under 2.5", "confidence": conf, "occurrences": row['occurrences']})
            
        # Over 2.5 Goals (>= 95%)
        if row['w_o25_rate'] >= 0.95:
            conf = f"{row['w_o25_rate']*100:.1f}%"
            pillars.append({**key, "market": "Over 2.5", "confidence": conf, "occurrences": row['occurrences']})
            
        # GG (Both Teams to Score) (>= 95%)
        if row['w_gg_rate'] >= 0.95:
            conf = f"{row['w_gg_rate']*100:.1f}%"
            pillars.append({**key, "market": "GG", "confidence": conf, "occurrences": row['occurrences']})

    pillars_df = pd.DataFrame(pillars)
    pillars_df = pillars_df.sort_values(by=['market', 'occurrences'], ascending=[True, False])
    
    print(f"✅ Extracted {len(pillars_df)} Unbreakable Goal Market Pillars.")
    
    # Save to a new JSON for the bot to read
    output_path = '/home/ubuntu/faith-workspace/vfl-empire/data/goal_pillars.json'
    pillars_df.to_json(output_path, orient='records', indent=4)
    print(f"💾 Saved to {output_path}")
    
    # Print a summary report
    print("\n🏆 THE ELITE 100% UNDER 3.5 PILLARS (Top 10 by Occurrences)")
    print(pillars_df[pillars_df['market'] == 'Under 3.5'].head(10).to_string(index=False))
    
    print("\n🔥 THE ELITE OVER 1.5 PILLARS (Top 10 by Occurrences)")
    print(pillars_df[pillars_df['market'] == 'Over 1.5'].head(10).to_string(index=False))
    
    print("\n🧱 THE ELITE UNDER 2.5 PILLARS (Top 10 by Occurrences)")
    print(pillars_df[pillars_df['market'] == 'Under 2.5'].head(10).to_string(index=False))

if __name__ == '__main__':
    mine_goal_pillars()
