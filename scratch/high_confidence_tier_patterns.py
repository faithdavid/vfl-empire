import json

def main():
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", "r") as f:
        data = json.load(f)
        
    print("\n--- TIER ANALYSIS OF 90%+ LOCKS ---")
    
    tier_lock_counts = {}
    
    for row in data:
        if row['occurrences'] < 5:
            continue
            
        hw = row['w_1_rate']
        dr = row['w_x_rate']
        aw = row['w_2_rate']
        
        dominant = max(hw, dr, aw)
        if dominant >= 0.90:
            mac_t = f"{row['home_tier']} vs {row['away_tier']}"
            
            if dominant == hw: market = "Home Win"
            elif dominant == aw: market = "Away Win"
            else: market = "Draw"
            
            if mac_t not in tier_lock_counts:
                tier_lock_counts[mac_t] = {'Home Win': 0, 'Draw': 0, 'Away Win': 0, 'Examples': []}
                
            tier_lock_counts[mac_t][market] += 1
            if len(tier_lock_counts[mac_t]['Examples']) < 3:
                tier_lock_counts[mac_t]['Examples'].append(f"{row['home']} vs {row['away']} ({dominant*100:.0f}% {market})")
                
    # Sort by total locks produced
    sorted_tiers = sorted(tier_lock_counts.items(), key=lambda x: x[1]['Home Win'] + x[1]['Draw'] + x[1]['Away Win'], reverse=True)
    
    print(f"{'MACRO TIER':<12} | {'TOTAL 90%+ LOCKS':<18} | {'BREAKDOWN':<30} | EXAMPLES")
    print("-" * 100)
    
    for mac_t, stats in sorted_tiers:
        total = stats['Home Win'] + stats['Draw'] + stats['Away Win']
        breakdown = f"HW: {stats['Home Win']}, DR: {stats['Draw']}, AW: {stats['Away Win']}"
        examples = ", ".join(stats['Examples'])
        print(f"{mac_t:<12} | {total:<18} | {breakdown:<30} | {examples}")

if __name__ == '__main__':
    main()
