import json

def main():
    with open("/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json", "r") as f:
        data = json.load(f)
        
    home_locks = []
    draw_locks = []
    away_locks = []

    for row in data:
        if row['occurrences'] < 5:
            continue
            
        fixture = f"{row['home']} vs {row['away']}"
        mac_t = f"({row['home_tier']} vs {row['away_tier']})"
        matches = row['occurrences']
        
        if row['w_1_rate'] >= 0.90:
            home_locks.append((fixture, mac_t, row['w_1_rate']*100, matches))
        if row['w_x_rate'] >= 0.90:
            draw_locks.append((fixture, mac_t, row['w_x_rate']*100, matches))
        if row['w_2_rate'] >= 0.90:
            away_locks.append((fixture, mac_t, row['w_2_rate']*100, matches))

    # Sort by percentage, then by occurrences
    home_locks.sort(key=lambda x: (x[2], x[3]), reverse=True)
    draw_locks.sort(key=lambda x: (x[2], x[3]), reverse=True)
    away_locks.sort(key=lambda x: (x[2], x[3]), reverse=True)

    print("\n" + "="*70)
    print(" 🏠 INDEPENDENT HOME WIN LOCKS (90%+) ")
    print("="*70)
    for l in home_locks:
        print(f"{l[0]:<35} | TIER: {l[1]:<12} | RATE: {l[2]:>5.1f}% | MATCHES: {l[3]}")

    print("\n" + "="*70)
    print(" 🤝 INDEPENDENT DRAW LOCKS (90%+) ")
    print("="*70)
    for l in draw_locks:
        print(f"{l[0]:<35} | TIER: {l[1]:<12} | RATE: {l[2]:>5.1f}% | MATCHES: {l[3]}")

    print("\n" + "="*70)
    print(" 🚌 INDEPENDENT AWAY WIN LOCKS (90%+) ")
    print("="*70)
    for l in away_locks:
        print(f"{l[0]:<35} | TIER: {l[1]:<12} | RATE: {l[2]:>5.1f}% | MATCHES: {l[3]}")

if __name__ == '__main__':
    main()
