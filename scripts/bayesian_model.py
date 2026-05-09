import sqlite3, numpy as np, json
from collections import defaultdict

conn = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')

# First, let's explore the schema
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print(f"Tables: {tables}")

# Check matches table
cursor = conn.execute("PRAGMA table_info(matches)")
cols = {r[1]: r[2] for r in cursor.fetchall()}
print(f"matches columns: {list(cols.keys())}")

# Count rows
n = conn.execute("SELECT COUNT(*) FROM matches WHERE outcome IS NOT NULL").fetchone()[0]
print(f"Matches with outcomes: {n}")

# Sample a few rows
print("\nSample rows:")
for row in conn.execute("SELECT * FROM matches WHERE outcome IS NOT NULL LIMIT 3").fetchall():
    print(row)

TIERS = {
    'MANCHESTER BLUE':1,'LIVERPOOL':1,'MANCHESTER RED':1,'CHELSEA':1,
    'LONDON GUNS':2,'TOTTENHAM':2,'ASTON VILLA':2,'WEST HAM':3,
    'EVERTON':3,'WOLVERHAMPTON':3,'BRIGHTON':3,'NEWCASTLE':4,
    'LEEDS':4,'CRYSTAL PALACE':4,'FULHAM':4,'BOURNEMOUTH':4
}

# Load match outcomes by team
team_results = defaultdict(lambda: {'h_games': 0, 'h_wins': 0, 'a_games': 0, 'a_wins': 0})
rows = conn.execute("SELECT home, away, outcome FROM matches WHERE outcome IS NOT NULL").fetchall()

for home, away, outcome in rows:
    team_results[home]['h_games'] += 1
    team_results[away]['a_games'] += 1
    if outcome == 'HOME':
        team_results[home]['h_wins'] += 1
    elif outcome == 'AWAY':
        team_results[away]['a_wins'] += 1

# SIMPLE BAYESIAN: Empirical Bayes estimate
# Prior: tier-level mean win rate (from all teams in that tier)
# Posterior: (prior * tier_games + team_win_rate * team_games) / (tier_games + team_games)

# Tier priors (from the Fellenius analysis — pre-computed tier averages)
tier_home = defaultdict(list)
tier_away = defaultdict(list)
for team, r in team_results.items():
    t = TIERS.get(team, 3)
    if r['h_games'] > 10:
        tier_home[t].append(r['h_wins'] / r['h_games'])
    if r['a_games'] > 10:
        tier_away[t].append(r['a_wins'] / r['a_games'])

tier_home_prior = {t: np.mean(vals) for t, vals in tier_home.items()}
tier_away_prior = {t: np.mean(vals) for t, vals in tier_away.items()}

print("\n=== BAYESIAN TIER PRIORS ===")
print(f"Tier: Home Win % | Away Win %")
for t in range(1,5):
    print(f"  T{t}: {tier_home_prior.get(t,0)*100:5.1f}% | {tier_away_prior.get(t,0)*100:5.1f}%")

# Empirical Bayes: shrink each team's estimate toward their tier mean
# Shrinkage factor α = k / (k + n) where k = prior strength (how many games the prior is worth)
print(f"\n=== EMPIRICAL BAYES TEAM RATINGS (shrunk toward tier mean) ===")
print(f"{'Team':22s} {'Raw H%':6s} {'Bayes H%':6s} {'Shrink':6s} {'Raw A%':6s} {'Bayes A%':6s} {'Shrink':6s} {'Tier':5s}")

bayes_ratings = []
shrinkage_data = []
for team in sorted(team_results.keys()):
    r = team_results[team]
    t = TIERS.get(team, 3)
    k = 50  # prior weight (50 games of tier-level data)
    
    raw_h = r['h_wins']/r['h_games']*100 if r['h_games'] > 0 else 0
    raw_a = r['a_wins']/r['a_games']*100 if r['a_games'] > 0 else 0
    
    bayes_h = (tier_home_prior.get(t,0.4)*100 * k + raw_h * r['h_games']) / (k + r['h_games']) if r['h_games'] > 0 else tier_home_prior.get(t,0.4)*100
    bayes_a = (tier_away_prior.get(t,0.3)*100 * k + raw_a * r['a_games']) / (k + r['a_games']) if r['a_games'] > 0 else tier_away_prior.get(t,0.3)*100
    
    shrink_h = abs(bayes_h - raw_h) if r['h_games'] > 10 else 0
    shrink_a = abs(bayes_a - raw_a) if r['a_games'] > 10 else 0
    
    bayes_ratings.append({'team': team, 'bayes_h': round(bayes_h,1), 'bayes_a': round(bayes_a,1), 'tier': t})
    shrinkage_data.append({'team': team, 'shrink_h': round(shrink_h,1), 'shrink_a': round(shrink_a,1), 'tier': t, 'games': r['h_games'] + r['a_games']})
    
    if r['h_games'] > 10:
        print(f"{team:22s} {raw_h:5.1f}% {bayes_h:5.1f}% {shrink_h:5.1f}% {raw_a:5.1f}% {bayes_a:5.1f}% {shrink_a:5.1f}% T{t}")

# Now predict using Bayesian ratings: P(home wins) = bayes_h_home / (bayes_h_home + (1 - bayes_a_away))
# Test against actual outcomes
print(f"\n=== BAYESIAN PREDICTION ACCURACY ===")
correct = 0
total = 0

for home, away, outcome in rows:
    # Get current Bayesian ratings for these teams
    home_rating = next((r for r in bayes_ratings if r['team'] == home), None)
    away_rating = next((r for r in bayes_ratings if r['team'] == away), None)
    if not home_rating or not away_rating: continue
    
    p_home = home_rating['bayes_h'] / (home_rating['bayes_h'] + (100 - away_rating['bayes_a']))
    p_away = away_rating['bayes_a'] / (away_rating['bayes_a'] + (100 - home_rating['bayes_h']))
    p_draw = 1 - p_home - p_away
    
    bayes_pick = 'HOME' if p_home > max(p_draw, p_away) else ('DRAW' if p_draw > p_away else 'AWAY')
    if bayes_pick == outcome: correct += 1
    total += 1

baseline = total * 0.5254  # market baseline from earlier analysis
print(f"Bayesian: {correct}/{total} = {correct/total*100:.1f}%")
print(f"Market baseline: {baseline:.0f}/{total} = 52.5%")
print(f"VERDICT: Bayesian {'BEATS' if correct > baseline else 'LOSES TO'} market by {abs(correct-baseline)/total*100:.1f}pp")

# Now: WHICH TEAMS GAIN MOST FROM SHRINKAGE?
print(f"\n=== TEAMS MOST AFFECTED BY SHRINKAGE ===")
print(f"(Teams whose raw rates are pulled furthest toward tier mean)")

# Sort by total shrinkage
shrinkage_data.sort(key=lambda x: x['shrink_h'] + x['shrink_a'], reverse=True)
print(f"\n{'Team':22s} {'HomeΔ':8s} {'AwayΔ':8s} {'Games':6s} {'Tier':5s}")
for s in shrinkage_data[:8]:
    print(f"{s['team']:22s} {s['shrink_h']:5.1f}%   {s['shrink_a']:5.1f}%   {s['games']:4d}   T{s['tier']}")

# Also check: which teams' raw data is most divergent from tier?
print(f"\n=== TEAMS MOST DIVERGENT FROM TIER (most extreme raw rates) ===")
print(f"(These benefit most from Bayesian smoothing)")
# Calculate divergence from tier mean
divergence = []
for team, r in team_results.items():
    t = TIERS.get(team, 3)
    if r['h_games'] > 10 and r['a_games'] > 10:
        raw_h = r['h_wins']/r['h_games']*100
        raw_a = r['a_wins']/r['a_games']*100
        div_h = abs(raw_h - tier_home_prior.get(t, 0.4)*100)
        div_a = abs(raw_a - tier_away_prior.get(t, 0.3)*100)
        divergence.append({'team': team, 'div_h': round(div_h,1), 'div_a': round(div_a,1), 'total_div': div_h+div_a, 'tier': t, 'raw_h': raw_h, 'raw_a': raw_a})
divergence.sort(key=lambda x: x['total_div'], reverse=True)
for d in divergence[:8]:
    print(f"{d['team']:22s} H:{d['raw_h']:5.1f}% A:{d['raw_a']:5.1f}% DivH:{d['div_h']:5.1f} DivA:{d['div_a']:5.1f} T{d['tier']}")

result = {
    'accuracy': round(correct/total*100, 1),
    'baseline': 52.5,
    'correct': correct,
    'total': total,
    'beats_market': correct > baseline,
    'margin_pp': round(abs(correct-baseline)/total*100, 1),
    'ratings': bayes_ratings,
    'tier_priors': {
        f'T{t}': {
            'home_pct': round(tier_home_prior.get(t, 0)*100, 1),
            'away_pct': round(tier_away_prior.get(t, 0)*100, 1)
        } for t in range(1,5)
    },
    'top_shrinkage': [{'team': s['team'], 'shrink_h': s['shrink_h'], 'shrink_a': s['shrink_a'], 'tier': s['tier']} for s in shrinkage_data[:5]],
    'top_divergent': [{'team': d['team'], 'div_h': d['div_h'], 'div_a': d['div_a'], 'raw_h': round(d['raw_h'],1), 'raw_a': round(d['raw_a'],1), 'tier': d['tier']} for d in divergence[:5]]
}

with open('/home/faith/Documents/Projects/vfl-data/analysis/bayesian-model.json', 'w') as f:
    json.dump(result, f, indent=2)

print(f"\n✅ Results saved to bayesian-model.json")
conn.close()
