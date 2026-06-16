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

# In this version, let's calculate the EV for each leg: EV = (prob * odds) - 1.0
for leg in legs:
    leg['ev'] = leg['prob'] * leg['odds'] - 1.0

md_selections_ev = {}

for md in sorted(md_legs.keys()):
    mlegs = md_legs[md]
    
    # Filter legs with odds in safe zone [1.15, 1.38]
    candidates = [l for l in mlegs if 1.15 <= l['odds'] <= 1.38 and l['market'] in ('Over 1.5', 'Double Chance 1X', 'Double Chance X2', 'Under 3.5')]
    
    # Sort candidates by EV descending
    candidates_sorted = sorted(candidates, key=lambda x: x['ev'], reverse=True)
    
    # Select top 2 on different matches
    best_2 = []
    seen_matches = set()
    for c in candidates_sorted:
        if c['ev_id'] not in seen_matches:
            best_2.append(c)
            seen_matches.add(c['ev_id'])
        if len(best_2) == 2:
            break
            
    md_selections_ev[md] = best_2

# Now let's calculate performance metrics
parlay_wins = 0
parlay_losses = 0
total_parlay_return = 0.0
bankroll_parlay = [100.0]

single_wins = 0
single_losses = 0
total_single_return = 0.0
bankroll_single = [100.0]

hits_distribution = {2: 0, 1: 0, 0: 0}

for md in sorted(md_selections_ev.keys()):
    picks = md_selections_ev[md]
    p1, p2 = picks[0], picks[1]
    
    # Parlay
    comb_odds = p1['odds'] * p2['odds']
    parlay_hit = p1['hit'] and p2['hit']
    
    if parlay_hit:
        parlay_wins += 1
        total_parlay_return += comb_odds
        bankroll_parlay.append(bankroll_parlay[-1] + (comb_odds - 1.0))
    else:
        parlay_losses += 1
        bankroll_parlay.append(bankroll_parlay[-1] - 1.0)
        
    # Singles
    md_wins = p1['hit'] + p2['hit']
    hits_distribution[md_wins] += 1
    
    md_single_return = 0.0
    if p1['hit']:
        single_wins += 1
        md_single_return += p1['odds']
    else:
        single_losses += 1
        
    if p2['hit']:
        single_wins += 1
        md_single_return += p2['odds']
    else:
        single_losses += 1
        
    total_single_return += md_single_return
    bankroll_single.append(bankroll_single[-1] + (md_single_return - 2.0))

def calc_max_drawdown(bankroll):
    peak = bankroll[0]
    max_dd = 0.0
    for val in bankroll:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd * 100.0

parlay_roi = ((total_parlay_return - 30) / 30) * 100.0
single_roi = ((total_single_return - 60) / 60) * 100.0

parlay_max_dd = calc_max_drawdown(bankroll_parlay)
single_max_dd = calc_max_drawdown(bankroll_single)

print(f"\n--- EV-BASED PARLAY PERFORMANCE ---")
print(f"Total Parlays Placed:       30")
print(f"Parlay Wins / Losses:       {parlay_wins} / {parlay_losses}")
print(f"Parlay Hit Rate:            {(parlay_wins / 30)*100:.2f}%")
print(f"Total Net Profit/Loss:      {bankroll_parlay[-1] - 100.0:+.2f} units")
print(f"Parlay ROI:                 {parlay_roi:+.2f}%")
print(f"Parlay Max Drawdown:        {parlay_max_dd:.2f}%")

print(f"\n--- EV-BASED SINGLE BETS PERFORMANCE ---")
print(f"Total Single Bets Placed:   60")
print(f"Single Wins / Losses:       {single_wins} / {single_losses}")
print(f"Single Pick Hit Rate:       {(single_wins / 60)*100:.2f}%")
print(f"Total Net Profit/Loss:      {bankroll_single[-1] - 100.0:+.2f} units")
print(f"Singles ROI:                {single_roi:+.2f}%")
print(f"Singles Max Drawdown:       {single_max_dd:.2f}%")

print(f"\n--- Matchday Hit Distribution ---")
for hits, count in hits_distribution.items():
    pct = (count / 30) * 100.0
    print(f"  {hits}/2 picks correct: {count:<2} matchdays ({pct:.1f}%)")
