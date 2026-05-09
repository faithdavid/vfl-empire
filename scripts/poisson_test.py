import sqlite3, math, json
from collections import defaultdict

conn = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')
rows = conn.execute("""
  SELECT home, away, oh, od, oa, outcome, h, a FROM matches 
  WHERE outcome IS NOT NULL AND oh IS NOT NULL AND h IS NOT NULL
""").fetchall()

# Compute team attack/defense strength
team_gf = defaultdict(list)
team_ga = defaultdict(list)
for r in rows:
    home, away, _, _, _, _, hg, ag = r
    team_gf[home].append(hg)
    team_gf[away].append(ag)
    team_ga[home].append(ag)
    team_ga[away].append(hg)

def mean(lst):
    return sum(lst) / len(lst) if lst else 0

avg_hg = mean([r[6] for r in rows])
avg_ag = mean([r[7] for r in rows])

attack = {t: mean(team_gf[t])/avg_hg for t in team_gf}
defense = {t: mean(team_ga[t])/avg_ag for t in team_ga}

def poisson_pmf(k, lam):
    if k < 0 or lam <= 0:
        return 0
    return math.exp(-lam) * lam**k / math.factorial(k)

def predict(home, away):
    lam_h = avg_hg * attack.get(home,1) * defense.get(away,1) * 1.15
    lam_a = avg_ag * attack.get(away,1) * defense.get(home,1) * 0.85
    p_h = p_d = p_a = 0.0
    for h in range(0, 8):
        for a in range(0, 8):
            prob = poisson_pmf(h, lam_h) * poisson_pmf(a, lam_a)
            if h > a: p_h += prob
            elif h == a: p_d += prob
            else: p_a += prob
    return p_h, p_d, p_a

correct = 0
market_correct = 0
total = 0
for r in rows:
    home, away, oh, od, oa, outcome, _, _ = r
    if oh <= 0 or od <= 0 or oa <= 0: continue
    ph, pd, pa = predict(home, away)
    impl_h = 1/oh / (1/oh + 1/od + 1/oa)
    impl_d = 1/od / (1/oh + 1/od + 1/oa)
    impl_a = 1/oa / (1/oh + 1/od + 1/oa)
    
    poisson_pick = 'HOME' if ph > max(pd, pa) else ('DRAW' if pd > pa else 'AWAY')
    market_pick = 'HOME' if impl_h > max(impl_d, impl_a) else ('DRAW' if impl_d > impl_a else 'AWAY')
    
    if poisson_pick == outcome: correct += 1
    if market_pick == outcome: market_correct += 1
    total += 1

print(f"Poisson: {correct}/{total} = {correct/total*100:.1f}%")
print(f"Market:  {market_correct}/{total} = {market_correct/total*100:.1f}%")
verdict = "beats" if correct > market_correct else "loses to"
pp = abs(correct-market_correct)/total*100
print(f"VERDICT: Poisson {verdict} market by {pp:.1f}pp")

result = {
    "poisson_accuracy": round(correct/total, 4),
    "market_accuracy": round(market_correct/total, 4),
    "verdict": f"Poisson {verdict} market by {pp:.1f}pp",
    "poisson_correct": correct,
    "market_correct": market_correct,
    "total": total
}

with open('/home/faith/Documents/Projects/vfl-data/analysis/poisson-model.json', 'w') as f:
    json.dump(result, f, indent=2)

print("\nSaved to poisson-model.json")
conn.close()
