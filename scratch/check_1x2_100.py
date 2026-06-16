import json

def find_high_rates(filepath, threshold=0.90):
    with open(filepath, 'r') as f:
        data = json.load(f)
        
    results = []
    for row in data:
        if row['occurrences'] >= 5:
            if row['w_1_rate'] >= threshold:
                results.append((row['home'], row['away'], 'Home Win', row['w_1_rate'], row['occurrences']))
            if row['w_x_rate'] >= threshold:
                results.append((row['home'], row['away'], 'Draw', row['w_x_rate'], row['occurrences']))
            if row['w_2_rate'] >= threshold:
                results.append((row['home'], row['away'], 'Away Win', row['w_2_rate'], row['occurrences']))
                
    return sorted(results, key=lambda x: (x[3], x[4]), reverse=True)

def main():
    print("--- MACRO PATTERNS (standings_patterns.json) >= 90% ---")
    macro_res = find_high_rates('/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json', 0.90)
    for res in macro_res:
        print(f"{res[0]} vs {res[1]} -> {res[2]}: {res[3]*100:.1f}% (from {res[4]} matches)")
        
    print("\n--- MICRO PATTERNS (micro_patterns.json) >= 90% ---")
    micro_res = find_high_rates('/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json', 0.90)
    for res in micro_res[:20]: # Top 20
        print(f"{res[0]} vs {res[1]} -> {res[2]}: {res[3]*100:.1f}% (from {res[4]} matches)")

if __name__ == '__main__':
    main()
