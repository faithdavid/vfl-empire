import json

def main():
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", "r") as f:
        data = json.load(f)
        
    buckets = {
        'hw': {'100': 0, '90-99': 0, '80-89': 0, '70-79': 0, '60-69': 0, '50-59': 0},
        'dr': {'100': 0, '90-99': 0, '80-89': 0, '70-79': 0, '60-69': 0, '50-59': 0},
        'aw': {'100': 0, '90-99': 0, '80-89': 0, '70-79': 0, '60-69': 0, '50-59': 0}
    }
    
    examples = { 'hw': [], 'dr': [], 'aw': [] }
    analyzed = 0

    for row in data:
        if row['occurrences'] < 5:
            continue
            
        analyzed += 1
        
        hw_pct = row['w_1_rate'] * 100
        dr_pct = row['w_x_rate'] * 100
        aw_pct = row['w_2_rate'] * 100
        
        dominant_pct = max(hw_pct, dr_pct, aw_pct)
        if dominant_pct == hw_pct: dominant_market = 'hw'
        elif dominant_pct == aw_pct: dominant_market = 'aw'
        else: dominant_market = 'dr'
        
        if dominant_pct >= 50:
            tier_string = f"{row['home']} ({row['home_tier']}) vs {row['away']} ({row['away_tier']})"
            if dominant_pct == 100:
                buckets[dominant_market]['100'] += 1
                if len(examples[dominant_market]) < 5:
                    examples[dominant_market].append(tier_string)
            elif dominant_pct >= 90:
                buckets[dominant_market]['90-99'] += 1
                if len(examples[dominant_market]) < 5 and dominant_market != 'hw': # hw has too many 100s
                    examples[dominant_market].append(f"{tier_string} ({dominant_pct:.1f}%)")
            elif dominant_pct >= 80:
                buckets[dominant_market]['80-89'] += 1
            elif dominant_pct >= 70:
                buckets[dominant_market]['70-79'] += 1
            elif dominant_pct >= 60:
                buckets[dominant_market]['60-69'] += 1
            else:
                buckets[dominant_market]['50-59'] += 1

    print("\n--- FIXTURE + TIER DOMINANCE BUCKETS (Minimum 5 matches) ---")
    print(f"Total Unique Fixture+Tier Combinations Analyzed: {analyzed}")
    
    for mkt_name, mkt_key in [("HOME WIN", "hw"), ("AWAY WIN", "aw"), ("DRAW", "dr")]:
        print(f"\n[{mkt_name} DOMINANCE]")
        print(f"  100% Hit Rate: {buckets[mkt_key]['100']:>3} combinations")
        print(f"  90-99% Rate:   {buckets[mkt_key]['90-99']:>3} combinations")
        print(f"  80-89% Rate:   {buckets[mkt_key]['80-89']:>3} combinations")
        print(f"  70-79% Rate:   {buckets[mkt_key]['70-79']:>3} combinations")
        print(f"  60-69% Rate:   {buckets[mkt_key]['60-69']:>3} combinations")
        print(f"  50-59% Rate:   {buckets[mkt_key]['50-59']:>3} combinations")
        
        if len(examples[mkt_key]) > 0:
            print(f"  -> Examples: {', '.join(examples[mkt_key])}")

if __name__ == '__main__':
    main()
