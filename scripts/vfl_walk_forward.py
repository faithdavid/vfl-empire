#!/usr/bin/env python3
"""
VFL Walk-Forward Unsupervised Learning Engine

Predicts each season BLIND using only patterns learned from PRIOR seasons.
Tests whether we improve across seasons by learning from our misses.

Usage: python3 vfl_walk_forward.py
"""
import sqlite3, json
from collections import defaultdict, Counter
from math import exp, log

def norm_team(t):
    if not t: return ''
    return t.strip().title()

def norm_outcome(o):
    o = str(o).upper().strip()
    if o in ('HOME', 'H', '1'): return 'H'
    if o in ('DRAW', 'D', 'X'): return 'D'
    if o in ('AWAY', 'A', '2'): return 'A'
    return '?'

# ========================
# STEP 1: Load ALL data
# ========================
all_matches = []

# Source 1: History DB
conn = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/history.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("""
    SELECT season, day, home, away, oh, od, oa, outcome, h, a
    FROM matches 
    WHERE oh IS NOT NULL AND od IS NOT NULL AND oa IS NOT NULL
      AND outcome IS NOT NULL AND outcome != ''
      AND oh > 0 AND od > 0 AND oa > 0
    ORDER BY season, day
""")
for r in cur.fetchall():
    outcome = norm_outcome(r['outcome'])
    if outcome == '?': continue
    all_matches.append({
        'season': r['season'],
        'md': r['day'],
        'home': norm_team(r['home']),
        'away': norm_team(r['away']),
        'odds_h': float(r['oh']),
        'odds_d': float(r['od']),
        'odds_a': float(r['oa']),
        'outcome': outcome,
    })
conn.close()

# Source 2: Sovereign DB
conn2 = sqlite3.connect('/home/faith/Documents/Projects/vfl-data/databases/sovereign.db')
conn2.row_factory = sqlite3.Row
cur2 = conn2.cursor()
cur2.execute("""
    SELECT season_id, match_day, home_team, away_team, odds_h, odds_d, odds_a, outcome
    FROM master_ledger 
    WHERE odds_h IS NOT NULL AND odds_d IS NOT NULL AND odds_a IS NOT NULL
      AND outcome IS NOT NULL AND outcome != ''
      AND odds_h > 0 AND odds_d > 0 AND odds_a > 0
""")
for r in cur2.fetchall():
    outcome = norm_outcome(r['outcome'])
    if outcome == '?': continue
    key = (r['season_id'], r['match_day'], norm_team(r['home_team']), norm_team(r['away_team']))
    # Deduplicate
    dupe = False
    for m in all_matches:
        if m['season'] == r['season_id'] and m['md'] == r['match_day'] and m['home'] == norm_team(r['home_team']) and m['away'] == norm_team(r['away_team']):
            dupe = True
            break
    if not dupe:
        all_matches.append({
            'season': r['season_id'],
            'md': r['match_day'],
            'home': norm_team(r['home_team']),
            'away': norm_team(r['away_team']),
            'odds_h': float(r['odds_h']),
            'odds_d': float(r['odds_d']),
            'odds_a': float(r['odds_a']),
            'outcome': outcome,
        })
conn2.close()

print(f"Total matches loaded: {len(all_matches)}")

# ========================
# STEP 2: Organize by season (chronologically)
# ========================
# Sort seasons by extracting the numeric portion
def season_sort_key(s):
    parts = s.replace('vf:season:', '').split('_')
    return int(parts[0])

season_matches = defaultdict(list)
for m in all_matches:
    season_matches[m['season']].append(m)

sorted_seasons = sorted(season_matches.keys(), key=season_sort_key)
print(f"Seasons: {len(sorted_seasons)}")
print(f"Range: {sorted_seasons[0]} → {sorted_seasons[-1]}")

for s in sorted_seasons:
    outcomes = Counter(m['outcome'] for m in season_matches[s])
    h = outcomes.get('H', 0)
    d = outcomes.get('D', 0)
    a = outcomes.get('A', 0)
    total = len(season_matches[s])
    print(f"  {s}: {total} matches (H:{h} D:{d} A:{a})")

# ========================
# STEP 3: Build the Walk-Forward Engine
# ========================

class WalkForwardLearner:
    """Learns from past seasons to predict future seasons blind."""
    
    def __init__(self):
        # Pattern store: what outcomes happen given odds ranges
        self.odd_bracket_stats = defaultdict(lambda: {'H': 0, 'D': 0, 'A': 0, 'total': 0})
        # Team-specific stats
        self.team_home_stats = defaultdict(lambda: {'H': 0, 'D': 0, 'A': 0})
        self.team_away_stats = defaultdict(lambda: {'H': 0, 'D': 0, 'A': 0})
        # H2H stats
        self.h2h_stats = defaultdict(lambda: {'H': 0, 'D': 0, 'A': 0})
        # Miss memory: what conditions cause misses
        self.miss_patterns = defaultdict(int)
        self.total_trained = 0
        
    def get_odds_bracket(self, oh, od, oa):
        """Categorize match by odds type."""
        # Determine favorite and their odds
        min_odds = min(oh, od, oa)
        if min_odds == oh: fav_type = 'H_FAV'
        elif min_odds == od: fav_type = 'D_FAV'
        else: fav_type = 'A_FAV'
        
        # Odds bracket
        if min_odds < 1.5: bracket = 'HEAVY'
        elif min_odds < 2.0: bracket = 'FAV'
        elif min_odds < 3.0: bracket = 'SLIGHT'
        elif min_odds < 5.0: bracket = 'PUNT'
        else: bracket = 'LONGSHOT'
        
        # Draw odds
        if od < 3.0: draw_bracket = 'LOW_D' 
        elif od < 3.5: draw_bracket = 'MED_D'
        elif od < 4.0: draw_bracket = 'HIGH_D'
        else: draw_bracket = 'LONG_D'
        
        return f"{fav_type}_{bracket}_{draw_bracket}"
    
    def train_from_match(self, m, was_miss=False):
        """Learn from a single match result."""
        bracket = self.get_odds_bracket(m['odds_h'], m['odds_d'], m['odds_a'])
        self.odd_bracket_stats[bracket][m['outcome']] += 1
        self.odd_bracket_stats[bracket]['total'] += 1
        
        self.team_home_stats[m['home']][m['outcome']] += 1
        self.team_away_stats[m['away']][m['outcome']] += 1
        
        h2h_key = (m['home'], m['away'])
        self.h2h_stats[h2h_key][m['outcome']] += 1
        
        if was_miss:
            self.miss_patterns[bracket] += 1
        
        self.total_trained += 1
    
    def predict(self, home, away, oh, od, oa):
        """
        Predict a match BLIND using only learned patterns.
        Returns (prediction, confidence, method, odds_fav).
        """
        bracket = self.get_odds_bracket(oh, od, oa)
        bracket_data = self.odd_bracket_stats[bracket]
        
        # Which outcome does the odds favorite suggest?
        min_odds_val = min(oh, od, oa)
        if min_odds_val == oh: odds_fav = 'H'
        elif min_odds_val == od: odds_fav = 'D'
        else: odds_fav = 'A'
        
        # METHOD 1: Odds bracket pattern
        if bracket_data['total'] >= 5:
            h_rate = bracket_data['H'] / bracket_data['total']
            d_rate = bracket_data['D'] / bracket_data['total']
            a_rate = bracket_data['A'] / bracket_data['total']
            bracket_pred = max([('H', h_rate), ('D', d_rate), ('A', a_rate)], key=lambda x: x[1])
            bracket_conf = bracket_pred[1] * 100
            
            # Check if odds fav matches bracket pattern
            if bracket_pred[0] == odds_fav:
                confidence = min(bracket_conf, 70)  # Cap at 70%
            else:
                # When bracket pattern disagrees with odds favorite
                # This is where the value is — market mispricing
                confidence = min(bracket_conf, 55)
            
            return bracket_pred[0], round(confidence, 1), 'ODDS_BRACKET', odds_fav
        
        # METHOD 2: Team-specific (fallback)
        home_data = self.team_home_stats.get(home, {'H': 0, 'D': 0, 'A': 0})
        away_away_data = self.team_away_stats.get(away, {'H': 0, 'D': 0, 'A': 0})
        
        home_h = home_data.get('H', 0) / max(sum(home_data.values()), 1)
        away_a = away_away_data.get('A', 0) / max(sum(away_away_data.values()), 1)
        
        # Simple home-away adjustment
        home_score = home_h * 1.2  # Home advantage boost
        away_score = away_a
        draw_score = 0.25  # Default draw probability
        
        if home_score > away_score and home_score > draw_score:
            team_pred = 'H'
            team_conf = home_score * 60
        elif away_score > draw_score:
            team_pred = 'A'
            team_conf = away_score * 55
        else:
            team_pred = 'D'
            team_conf = 40
        
        return team_pred, round(team_conf, 1), 'TEAM_STATS', odds_fav
    
    def get_accuracy(self, season_name):
        """Get current accuracy stats for reporting."""
        return {
            'total_trained': self.total_trained,
            'miss_patterns': dict(self.miss_patterns.most_common(10)),
        }


# ========================
# STEP 4: RUN WALK-FORWARD TEST
# ========================

print(f"\n{'='*70}")
print(f"WALK-FORWARD UNSUPERVISED LEARNING TEST")
print(f"Each season predicted BLIND — only using data from prior seasons")
print(f"{'='*70}")

learner = WalkForwardLearner()
season_results = []

# Process first season — just train, no prediction (no prior data)
first_season = sorted_seasons[0]
for m in season_matches[first_season]:
    learner.train_from_match(m, was_miss=False)

print(f"\n{'SEASON':30s} | {'MATCHES':8s} | {'CORRECT':8s} | {'ACCURACY':8s} | {'METHOD':15s} | {'AGAINST_ODDS'}")
print("-" * 90)

for season in sorted_seasons[1:]:  # Skip first season
    matches = season_matches[season]
    correct = 0
    total = 0
    against_odds_correct = 0
    against_odds_total = 0
    method_counts = Counter()
    
    for m in matches:
        pred, conf, method, odds_fav = learner.predict(
            m['home'], m['away'], m['odds_h'], m['odds_d'], m['odds_a']
        )
        total += 1
        method_counts[method] += 1
        
        if pred == m['outcome']:
            correct += 1
            learner.train_from_match(m, was_miss=False)
        else:
            learner.train_from_match(m, was_miss=True)
        
        # Track against-odds picks
        if pred != odds_fav:
            against_odds_total += 1
            if pred == m['outcome']:
                against_odds_correct += 1
    
    acc = correct / total * 100 if total else 0
    ao_acc = against_odds_correct / against_odds_total * 100 if against_odds_total else 0
    main_method = method_counts.most_common(1)[0][0]
    
    season_results.append({
        'season': season,
        'total': total,
        'correct': correct,
        'accuracy': acc,
        'against_odds': f"{against_odds_correct}/{against_odds_total} ({ao_acc:.0f}%)" if against_odds_total else "N/A",
        'method': main_method,
    })
    
    # Build progressive accuracy bar
    bar_len = int(acc / 4)
    bar = '█' * bar_len + '░' * (25 - bar_len)
    marker = '⬆' if len(season_results) >= 2 and acc > season_results[-2]['accuracy'] else '⬇' if len(season_results) >= 2 and acc < season_results[-2]['accuracy'] else '→'
    
    print(f"{str(season)[-25:]:30s} | {total:4d}/{total:4d} | {correct:4d}/{total:4d} | {acc:5.1f}% {bar} | {main_method:15s} | {season_results[-1]['against_odds']}")

# ========================
# STEP 5: REPORT
# ========================
print(f"\n{'='*70}")
print(f"OVERALL RESULTS")
print(f"{'='*70}")

total_correct = sum(r['correct'] for r in season_results)
total_matches = sum(r['total'] for r in season_results)
overall_acc = total_correct / total_matches * 100

# Accuracy progression
first_acc = season_results[0]['accuracy']
last_acc = season_results[-1]['accuracy']
best_season = max(season_results, key=lambda r: r['accuracy'])
worst_season = min(season_results, key=lambda r: r['accuracy'])

print(f"  Overall accuracy: {total_correct}/{total_matches} = {overall_acc:.1f}%")
print(f"  First season acc: {first_acc:.1f}% → Last season acc: {last_acc:.1f}%")
print(f"  Change: {last_acc - first_acc:+.1f}pp")
print(f"  Best season: {best_season['season']} ({best_season['accuracy']:.1f}%)")
print(f"  Worst season: {worst_season['season']} ({worst_season['accuracy']:.1f}%)")

# Trend analysis
first_5 = sum(r['accuracy'] for r in season_results[:5]) / 5
last_5 = sum(r['accuracy'] for r in season_results[-5:]) / 5
print(f"\n  First 5 seasons avg: {first_5:.1f}%")
print(f"  Last 5 seasons avg: {last_5:.1f}%")
print(f"  Learning improvement: {last_5 - first_5:+.1f}pp")

print(f"\n  Miss patterns learned:")
for pattern, count in sorted(learner.miss_patterns.items(), key=lambda x: -x[1])[:5]:
    print(f"    {pattern}: {count} misses")

# Accuracy by season - show progression
print(f"\n{'SEASON':25s} | {'ACC':6s} | {'TREND'}")
print("-" * 50)
for i, r in enumerate(season_results):
    if i >= 2:
        prev = season_results[i-1]['accuracy']
        trend = f"⬆ +{r['accuracy']-prev:.1f}" if r['accuracy'] > prev else f"⬇ {r['accuracy']-prev:.1f}" if r['accuracy'] < prev else "→"
    else:
        trend = "  -"
    print(f"{str(r['season'])[-20:]:25s} | {r['accuracy']:5.1f}% | {trend}")

# Save full results
with open('/tmp/walk_forward_results.json', 'w') as f:
    json.dump({
        'overall_accuracy': overall_acc,
        'total_matches': total_matches,
        'total_correct': total_correct,
        'season_results': season_results,
        'miss_patterns': dict(learner.miss_patterns.most_common(20)),
    }, f, indent=2)

print(f"\nResults saved to /tmp/walk_forward_results.json")
