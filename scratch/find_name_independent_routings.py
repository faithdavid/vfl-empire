import json
from collections import defaultdict

with open('/home/ubuntu/faith-workspace/vfl-complete-data/signals/results_last12h_compiled.json') as f:
    data = json.load(f)

matches = data.get('matches', [])
seasons = [matches[i:i+240] for i in range(0, len(matches), 240) if len(matches[i:i+240]) == 240]

def get_tier(rank):
    if rank <= 4: return "T1(1-4)"
    if rank <= 8: return "T2(5-8)"
    if rank <= 12: return "T3(9-12)"
    return "T4(13-16)"
    
def get_md_chunk(md):
    if md <= 5: return "MD 1-5"
    if md <= 10: return "MD 6-10"
    if md <= 15: return "MD 11-15"
    if md <= 20: return "MD 16-20"
    if md <= 25: return "MD 21-25"
    return "MD 26-30"

routing = defaultdict(lambda: {'1':0, 'X':0, '2':0, 'total':0})

for season_matches in seasons:
    team_pts = {t: 0 for t in set(m['home_team'] for m in season_matches)}
    
    for md in range(1, 31):
        # Update standings BEFORE the matchday begins
        ranks = {t: i+1 for i, (t, _) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))}
        
        for m in season_matches:
            if m['match_day'] != md: continue
            
            h, a = m['home_team'], m['away_team']
            if md == 1:
                h_rank, a_rank = "Start", "Start"
                h_tier, a_tier = "Start", "Start"
            else:
                h_rank, a_rank = ranks[h], ranks[a]
                h_tier, a_tier = get_tier(h_rank), get_tier(a_rank)
                
            chunk = get_md_chunk(md)
            key = f"[{chunk}] Home:{h_tier} vs Away:{a_tier}"
            
            hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
            routing[key]['total'] += 1
            if hg > ag: routing[key]['1'] += 1
            elif hg == ag: routing[key]['X'] += 1
            else: routing[key]['2'] += 1
            
        # Add MD points for next iteration
        for m in season_matches:
            if m['match_day'] == md:
                hg, ag = m.get('home_goals', 0), m.get('away_goals', 0)
                h, a = m['home_team'], m['away_team']
                if hg > ag: team_pts[h] += 3
                elif hg == ag: team_pts[h] += 1; team_pts[a] += 1
                else: team_pts[a] += 3

print("=== NAME-INDEPENDENT ROUTING MAP (100% Locks, Sample >= 5) ===")
found = 0
for key, stats in sorted(routing.items(), key=lambda x: x[1]['total'], reverse=True):
    t = stats['total']
    if t < 5: continue
    
    w1 = stats['1']/t
    wX = stats['X']/t
    w2 = stats['2']/t
    
    if w1 == 1.0:
        print(f"[ 100.0% ] HOME WIN | {key} (Sample: {t})")
        found += 1
    elif w2 == 1.0:
        print(f"[ 100.0% ] AWAY WIN | {key} (Sample: {t})")
        found += 1
    elif wX == 1.0:
        print(f"[ 100.0% ] RAW DRAW | {key} (Sample: {t})")
        found += 1

if found == 0:
    print("No 100% absolute hits found with just Tiers.")

print("\n=== HIGH PROBABILITY ROUTINGS (90%+ Hit Rate, Sample >= 15) ===")
for key, stats in sorted(routing.items(), key=lambda x: x[1]['total'], reverse=True):
    t = stats['total']
    if t < 15: continue
    
    w1 = stats['1']/t
    wX = stats['X']/t
    w2 = stats['2']/t
    
    if w1 >= 0.90:
        print(f"[ {w1*100:^5.1f}% ] HOME WIN | {key} (Sample: {t})")
    elif w2 >= 0.90:
        print(f"[ {w2*100:^5.1f}% ] AWAY WIN | {key} (Sample: {t})")
    elif (w1 + wX) >= 0.90:
        print(f"[ {(w1+wX)*100:^5.1f}% ] 1X (DC)  | {key} (Sample: {t})")
    elif (w2 + wX) >= 0.90:
        print(f"[ {(w2+wX)*100:^5.1f}% ] X2 (DC)  | {key} (Sample: {t})")

