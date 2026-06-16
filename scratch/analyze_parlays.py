import json

LEGS_FILE = '/home/ubuntu/faith-workspace/vfl-empire/scratch/vflm_5115_legs.json'

with open(LEGS_FILE, 'r') as f:
    legs = json.load(f)

# Group legs by matchday
md_legs = {}
for leg in legs:
    md = leg['md']
    if md not in md_legs:
        md_legs[md] = []
    md_legs[md].append(leg)

def evaluate_combination_type(name, filter_m1, filter_m2):
    """
    Evaluates a specific parlay combination type over all matchdays.
    For each matchday, finds all pairs of matches where match1 satisfies filter_m1 and match2 satisfies filter_m2.
    """
    total_parlays = 0
    wins = 0
    leg1_hits = 0
    leg2_hits = 0
    total_return = 0.0
    
    # We want to keep track of individual legs' properties
    all_odds_1 = []
    all_odds_2 = []
    all_probs_1 = []
    all_probs_2 = []
    
    for md, mlegs in md_legs.items():
        # Find candidates for leg 1
        candidates_1 = [l for l in mlegs if filter_m1(l)]
        # Find candidates for leg 2
        candidates_2 = [l for l in mlegs if filter_m2(l)]
        
        for c1 in candidates_1:
            for c2 in candidates_2:
                # Must be different matches!
                if c1['ev_id'] == c2['ev_id']:
                    continue
                
                # Check if total odds is around ~1.6 (say between 1.45 and 1.75)
                comb_odds = c1['odds'] * c2['odds']
                if not (1.45 <= comb_odds <= 1.75):
                    continue
                
                total_parlays += 1
                all_odds_1.append(c1['odds'])
                all_odds_2.append(c2['odds'])
                all_probs_1.append(c1['prob'])
                all_probs_2.append(c2['prob'])
                
                l1_hit = c1['hit']
                l2_hit = c2['hit']
                
                if l1_hit:
                    leg1_hits += 1
                if l2_hit:
                    leg2_hits += 1
                    
                if l1_hit and l2_hit:
                    wins += 1
                    total_return += comb_odds
                    
    if total_parlays == 0:
        return None
        
    avg_odds_1 = sum(all_odds_1) / total_parlays
    avg_odds_2 = sum(all_odds_2) / total_parlays
    avg_prob_1 = sum(all_probs_1) / total_parlays
    avg_prob_2 = sum(all_probs_2) / total_parlays
    
    hit_rate_1 = leg1_hits / total_parlays
    hit_rate_2 = leg2_hits / total_parlays
    parlay_hit_rate = wins / total_parlays
    roi = ((total_return - total_parlays) / total_parlays) * 100.0
    
    return {
        'name': name,
        'count': total_parlays,
        'avg_odds_1': avg_odds_1,
        'avg_odds_2': avg_odds_2,
        'avg_prob_1': avg_prob_1,
        'avg_prob_2': avg_prob_2,
        'hit_rate_1': hit_rate_1,
        'hit_rate_2': hit_rate_2,
        'parlay_hit_rate': parlay_hit_rate,
        'roi_pct': roi
    }

# Define the filters
# 1. Over 1.5 + Over 1.5
filter_o15 = lambda l: l['market'] == 'Over 1.5'

# 2. Over 1.5 + Double Chance 1X
filter_dc1x = lambda l: l['market'] == 'Double Chance 1X'

# 3. Double Chance 1X + Double Chance X2
filter_dcx2 = lambda l: l['market'] == 'Double Chance X2'

# 4. Over 1.5 + Under 3.5
filter_u35 = lambda l: l['market'] == 'Under 3.5'

# 5. Home Win (strong favorite) + Over 1.5
# Strong favorite Home Win is typically defined as Home Win odds < 1.70 or so (let's say 1.15 to 1.50)
filter_home_fav = lambda l: l['market'] == 'Home Win' and (1.15 <= l['odds'] <= 1.45)

# 6. Manchester Blue at home Over 1.5 + Liverpool at home Over 1.5
filter_mb_home_o15 = lambda l: l['market'] == 'Over 1.5' and l['home'] == 'Manchester Blue'
filter_liv_home_o15 = lambda l: l['market'] == 'Over 1.5' and l['home'] == 'Liverpool'

combinations = [
    ('Over 1.5 + Over 1.5', filter_o15, filter_o15),
    ('Over 1.5 + Double Chance 1X', filter_o15, filter_dc1x),
    ('Double Chance 1X + Double Chance X2', filter_dc1x, filter_dcx2),
    ('Over 1.5 + Under 3.5', filter_o15, filter_u35),
    ('Home Win (Strong Fav) + Over 1.5', filter_home_fav, filter_o15),
    ('Man Blue Home O1.5 + Liverpool Home O1.5', filter_mb_home_o15, filter_liv_home_o15)
]

print(f"{'Combination Type':<45} | {'Count':<6} | {'Leg 1 HR':<10} | {'Leg 2 HR':<10} | {'Parlay HR':<10} | {'ROI':<10}")
print("-" * 97)
for name, f1, f2 in combinations:
    res = evaluate_combination_type(name, f1, f2)
    if res:
        print(f"{res['name']:<45} | {res['count']:<6} | {res['hit_rate_1']*100:<9.2f}% | {res['hit_rate_2']*100:<9.2f}% | {res['parlay_hit_rate']*100:<9.2f}% | {res['roi_pct']:+8.2f}%")
