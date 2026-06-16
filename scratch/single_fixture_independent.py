import json

def main():
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", "r") as f:
        data = json.load(f)
        
    target_home = "Everton"
    target_away = "Manchester Blue"
    
    hw_scenarios = []
    dr_scenarios = []
    aw_scenarios = []

    for row in data:
        if row['home'] == target_home and row['away'] == target_away:
            # We don't filter out by occurrence here to show the full scope, 
            # but we show occurrences so they can judge the weight.
            mac_t = f"T{row['home_tier'][-1]} vs T{row['away_tier'][-1]}"
            hw_pct = row['w_1_rate'] * 100
            dr_pct = row['w_x_rate'] * 100
            aw_pct = row['w_2_rate'] * 100
            matches = row['occurrences']
            
            hw_scenarios.append((mac_t, hw_pct, matches))
            dr_scenarios.append((mac_t, dr_pct, matches))
            aw_scenarios.append((mac_t, aw_pct, matches))

    hw_scenarios.sort(key=lambda x: x[1], reverse=True)
    dr_scenarios.sort(key=lambda x: x[1], reverse=True)
    aw_scenarios.sort(key=lambda x: x[1], reverse=True)

    print(f"\n========================================================")
    print(f" INDEPENDENT 1X2 MARKET BREAKDOWN: {target_home} vs {target_away}")
    print(f"========================================================")
    
    print("\n 🏠 CONDITIONS FAVORING: HOME WIN (Everton)")
    print("-" * 50)
    for s in hw_scenarios:
        if s[1] > 0: print(f"Tier: {s[0]:<10} | HW: {s[1]:>5.1f}% | Matches: {s[2]}")

    print("\n 🤝 CONDITIONS FAVORING: DRAW")
    print("-" * 50)
    for s in dr_scenarios:
        if s[1] > 0: print(f"Tier: {s[0]:<10} | DR: {s[1]:>5.1f}% | Matches: {s[2]}")

    print("\n 🚌 CONDITIONS FAVORING: AWAY WIN (Manchester Blue)")
    print("-" * 50)
    for s in aw_scenarios:
        if s[1] > 0: print(f"Tier: {s[0]:<10} | AW: {s[1]:>5.1f}% | Matches: {s[2]}")

if __name__ == '__main__':
    main()
