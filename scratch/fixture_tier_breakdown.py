import json
import sys

def main():
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", "r") as f:
        data = json.load(f)
        
    target_home = "Everton"
    target_away = "Manchester Blue"
    
    print(f"\n--- 1X2 MARKET BREAKDOWN FOR: {target_home} vs {target_away} ---")
    print(f"{'TIERS':<12} | {'MATCHES':<7} | {'HOME WIN':<10} | {'DRAW':<10} | {'AWAY WIN':<10}")
    print("-" * 65)
    
    results = []
    for row in data:
        if row['home'] == target_home and row['away'] == target_away:
            if row['occurrences'] >= 3: # Lowered threshold slightly just to see the spread
                results.append(row)
                
    # Sort by Home Tier, then Away Tier
    results.sort(key=lambda x: (x['home_tier'], x['away_tier']))
    
    total_matches = 0
    total_hw = 0
    total_dr = 0
    total_aw = 0
    
    for r in results:
        t = f"{r['home_tier']} vs {r['away_tier']}"
        hw = r['w_1_rate'] * 100
        dr = r['w_x_rate'] * 100
        aw = r['w_2_rate'] * 100
        matches = r['occurrences']
        
        total_matches += matches
        total_hw += int(r['w_1_rate'] * matches)
        total_dr += int(r['w_x_rate'] * matches)
        total_aw += int(r['w_2_rate'] * matches)
        
        print(f"{t:<12} | {matches:<7} | {hw:>5.1f}%     | {dr:>5.1f}%     | {aw:>5.1f}%")
        
    print("-" * 65)
    if total_matches > 0:
        avg_hw = (total_hw / total_matches) * 100
        avg_dr = (total_dr / total_matches) * 100
        avg_aw = (total_aw / total_matches) * 100
        print(f"{'OVERALL':<12} | {total_matches:<7} | {avg_hw:>5.1f}%     | {avg_dr:>5.1f}%     | {avg_aw:>5.1f}%")

if __name__ == '__main__':
    main()
