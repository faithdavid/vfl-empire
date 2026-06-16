import json
import sys

def check_confluence():
    with open('/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json', 'r') as f:
        micro_data = json.load(f)
    micro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in micro_data }
    
    with open('/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json', 'r') as f:
        macro_data = json.load(f)
    macro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in macro_data }
    
    matches = [
        ('London Guns', 'Everton', 'T2', 'T3', 'T2', 'T3'), 
        ('Wolverhampton', 'Newcastle', 'T2', 'T3', 'T3', 'T4')
    ]
    # We need the exact tiers for the match to check.
    # From earlier:
    # London Guns vs Everton: macro T2 vs T3, micro ?
    # Let's just check the exact keys that match home and away.
    
    for home, away in [('London Guns', 'Everton'), ('Wolverhampton', 'Newcastle')]:
        print(f"\nChecking Confluence for {home} vs {away}:")
        mac_rows = [r for r in macro_data if r['home'] == home and r['away'] == away]
        mic_rows = [r for r in micro_data if r['home'] == home and r['away'] == away]
        
        for mac_r in mac_rows:
            for mic_r in mic_rows:
                if mac_r['home_tier'] == mic_r['home_tier'] and mac_r['away_tier'] == mic_r['away_tier']:
                    # Check confluence
                    markets = [
                        ('Under 1.5', 'w_u15_rate'), ('Over 1.5', 'w_o15_rate'),
                        ('Under 2.5', 'w_u25_rate'), ('Over 2.5', 'w_o25_rate'),
                        ('Under 3.5', 'w_u35_rate'), ('Over 3.5', 'w_o35_rate'),
                        ('GG (BTTS)', 'w_gg_rate'),
                        ('Home Win (1)', 'w_1_rate'), ('Draw (X)', 'w_x_rate'), ('Away Win (2)', 'w_2_rate')
                    ]
                    for pick_name, rate_key in markets:
                        mac_val = mac_r.get(rate_key, 0)
                        mic_val = mic_r.get(rate_key, 0)
                        if mac_val >= 0.80 and mic_val >= 0.80:
                            print(f"  -> CONFLUENCE LOCK: {pick_name} | Macro: {mac_val:.2f}, Micro: {mic_val:.2f} (Tiers: {mac_r['home_tier']} vs {mac_r['away_tier']})")

if __name__ == '__main__':
    check_confluence()
