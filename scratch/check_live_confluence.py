import sys
sys.path.append('/home/ubuntu/faith-workspace/vfl-empire/scripts')
from msport_api import get_results, _normalise_team_name
import json

def check_recent_confluence():
    with open('/home/ubuntu/faith-workspace/vfl-empire/data/micro_patterns.json', 'r') as f:
        micro_data = json.load(f)
    micro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in micro_data }
    
    with open('/home/ubuntu/faith-workspace/vfl-empire/data/standings_patterns.json', 'r') as f:
        macro_data = json.load(f)
    macro_lookup = { (r['home'], r['away'], r['home_tier'], r['away_tier']): r for r in macro_data }
    
    markets = [
        ('Under 1.5', 'w_u15_rate'), ('Over 1.5', 'w_o15_rate'),
        ('Under 2.5', 'w_u25_rate'), ('Over 2.5', 'w_o25_rate'),
        ('Under 3.5', 'w_u35_rate'), ('Over 3.5', 'w_o35_rate'),
        ('GG (BTTS)', 'w_gg_rate'),
        ('Home Win (1)', 'w_1_rate'), ('Draw (X)', 'w_x_rate'), ('Away Win (2)', 'w_2_rate')
    ]
    
    # We don't have the live standings from 5296 and 5297. 
    # The Discord predictor queries live standings. Since the season is over, we can't recreate the live table for each matchday!
    print("Cannot recreate live standings retrospectively without the database.")

if __name__ == '__main__':
    check_recent_confluence()
