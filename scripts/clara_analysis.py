#!/usr/bin/env python3
"""
Clara's Permutation Analysis: Outcome distribution per MD position
"""

import sqlite3
import json
import math
from collections import Counter, defaultdict

DB_PATH = '/home/faith/Documents/Projects/vfl-data/databases/history.db'
OUTPUT_PATH = '/home/faith/Documents/Projects/vfl-data/analysis/clara_permutation_analysis.json'

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# --- Normalize outcomes ---
def norm_outcome(o):
    if o is None:
        return None
    o = o.strip().upper()
    if o in ('H', 'HOME'):
        return 'HOME'
    if o in ('A', 'AWAY'):
        return 'AWAY'
    if o in ('D', 'DRAW'):
        return 'DRAW'
    return None

# --- Get all complete seasons (30 days) ---
c.execute('''
  SELECT season FROM matches 
  WHERE outcome IS NOT NULL
  GROUP BY season 
  HAVING COUNT(DISTINCT day) = 30
  ORDER BY season
''')
all_seasons = [r['season'] for r in c.fetchall()]
print(f"Complete seasons (30 MDs, non-null outcomes): {len(all_seasons)}")

# Only use the first 223 (as specified) or all if fewer
seasons_to_use = all_seasons[:223] if len(all_seasons) >= 223 else all_seasons
print(f"Using {len(seasons_to_use)} seasons for analysis")

# --- Fetch all match data ---
placeholders = ','.join('?' * len(seasons_to_use))
c.execute(f'''
  SELECT season, day, home, away, outcome
  FROM matches
  WHERE season IN ({placeholders}) AND outcome IS NOT NULL
  ORDER BY season, day
''', seasons_to_use)

matches = [dict(r) for r in c.fetchall()]
print(f"Total matches: {len(matches)}")

# Normalize outcomes
for m in matches:
    m['outcome'] = norm_outcome(m['outcome'])
    m['home'] = m['home'].strip().upper()
    m['away'] = m['away'].strip().upper()

# Filter out any null outcomes after normalization
matches = [m for m in matches if m['outcome'] is not None]
print(f"After normalization: {len(matches)} matches")

# Count matches per MD
md_counts = Counter(m['day'] for m in matches)
print(f"Matches per MD: {dict(sorted(md_counts.items()))}")

# =====================================================
# ANALYSIS 1: Per-MD outcome distribution
# =====================================================
print("\n=== ANALYSIS 1: Per-MD Outcome Distribution ===")

md_outcomes = defaultdict(lambda: {'HOME': 0, 'AWAY': 0, 'DRAW': 0})
for m in matches:
    md_outcomes[m['day']][m['outcome']] += 1

total_home = sum(v['HOME'] for v in md_outcomes.values())
total_away = sum(v['AWAY'] for v in md_outcomes.values())
total_draw = sum(v['DRAW'] for v in md_outcomes.values())
total_all = total_home + total_away + total_draw
global_home_pct = total_home / total_all * 100
global_away_pct = total_away / total_all * 100
global_draw_pct = total_draw / total_all * 100

print(f"Global averages: HOME={global_home_pct:.1f}%, AWAY={global_away_pct:.1f}%, DRAW={global_draw_pct:.1f}%")

md_distribution = {}
deviant_mds = []

for day in sorted(md_outcomes.keys()):
    d = md_outcomes[day]
    total = d['HOME'] + d['AWAY'] + d['DRAW']
    hp = d['HOME'] / total * 100
    ap = d['AWAY'] / total * 100
    dp = d['DRAW'] / total * 100
    
    # Calculate absolute deviation from global average
    dev = abs(hp - global_home_pct) + abs(ap - global_away_pct) + abs(dp - global_draw_pct)
    
    md_distribution[day] = {
        'total_matches': total,
        'home_wins': d['HOME'],
        'away_wins': d['AWAY'],
        'draws': d['DRAW'],
        'home_pct': round(hp, 2),
        'away_pct': round(ap, 2),
        'draw_pct': round(dp, 2),
        'deviation_score': round(dev, 2)
    }
    
    # Flag MDs with significant deviation (using threshold of 5% total deviation)
    if dev > 5.0:
        deviant_mds.append({
            'md': day,
            'deviation_score': round(dev, 2),
            'home_pct': round(hp, 2),
            'away_pct': round(ap, 2),
            'draw_pct': round(dp, 2),
            'vs_global': {
                'home_diff': round(hp - global_home_pct, 2),
                'away_diff': round(ap - global_away_pct, 2),
                'draw_diff': round(dp - global_draw_pct, 2)
            }
        })
        print(f"  MD {day:2d}: HOME={hp:5.1f}% AWAY={ap:5.1f}% DRAW={dp:5.1f}%  (dev={dev:.1f}) *** DEVIANT")
    else:
        print(f"  MD {day:2d}: HOME={hp:5.1f}% AWAY={ap:5.1f}% DRAW={dp:5.1f}%  (dev={dev:.1f})")

# =====================================================
# ANALYSIS 2: Permutation space - distinct outcome patterns
# =====================================================
print("\n=== ANALYSIS 2: Permutation Space ===")

# Group matches by (season, day) to get outcome patterns
md_patterns = defaultdict(set)
md_pattern_counts = defaultdict(lambda: defaultdict(int))  # md -> pattern -> count

# Group matches into patterns per (season, day)
# First, ensure we have exactly 8 matches per MD per season
from collections import defaultdict as dd

md_matches = dd(list)
for m in matches:
    md_matches[(m['season'], m['day'])].append(m)

# Check counts
incomplete = [(s, d) for (s, d), ms in md_matches.items() if len(ms) != 8]
if incomplete:
    print(f"WARNING: {len(incomplete)} (season, day) pairs don't have 8 matches each")
    for s, d in incomplete[:10]:
        print(f"  {s} MD {d}: {len(md_matches[(s,d)])} matches")

# Create patterns
for (season, day), ms in md_matches.items():
    if len(ms) != 8:
        continue
    # Sort by home team for consistent ordering
    ms_sorted = sorted(ms, key=lambda x: (x['home'], x['away']))
    pattern = tuple(m['outcome'] for m in ms_sorted)
    md_patterns[day].add(pattern)
    md_pattern_counts[day][pattern] += 1

total_possible_patterns = 3**8  # 6561

permutation_analysis = {}
for day in sorted(md_patterns.keys()):
    seen = len(md_patterns[day])
    pct = seen / total_possible_patterns * 100
    permutation_analysis[day] = {
        'distinct_patterns_seen': seen,
        'total_possible': total_possible_patterns,
        'coverage_pct': round(pct, 3),
        'unique_seasons_with_pattern': sum(md_pattern_counts[day].values())
    }
    print(f"  MD {day:2d}: {seen:4d} / {total_possible_patterns} patterns seen ({pct:.2f}%)")

# Check for never-seen patterns
# Count most common patterns per MD
print("\n  Top 5 most common patterns per MD:")
for day in sorted(md_pattern_counts.keys()):
    sorted_patterns = sorted(md_pattern_counts[day].items(), key=lambda x: -x[1])[:5]
    patterns_str = []
    for pat, cnt in sorted_patterns:
        h = sum(1 for o in pat if o == 'HOME')
        a = sum(1 for o in pat if o == 'AWAY')
        d = sum(1 for o in pat if o == 'DRAW')
        patterns_str.append(f"{''.join(o[0] for o in pat)} (H{h}A{a}D{d}) x{cnt}")
    print(f"    MD {day:2d}: {' | '.join(patterns_str)}")

# =====================================================
# ANALYSIS 3: Never-seen patterns
# =====================================================
print("\n=== ANALYSIS 3: Never-Seen Patterns ===")

# The big question: how many of the 6561 possible patterns have NEVER been seen?
# Since we've seen relatively few patterns, most are never-seen
never_seen_analysis = {}
for day in sorted(md_patterns.keys()):
    seen_count = len(md_patterns[day])
    never_seen = total_possible_patterns - seen_count
    never_seen_analysis[day] = {
        'never_seen_patterns': never_seen,
        'seen_patterns': seen_count,
        'never_seen_pct': round(never_seen / total_possible_patterns * 100, 2)
    }
    print(f"  MD {day:2d}: {never_seen:5d} / {total_possible_patterns} patterns NEVER seen ({never_seen/total_possible_patterns*100:.2f}%)")

# =====================================================
# ANALYSIS 4: Home win clustering
# =====================================================
print("\n=== ANALYSIS 4: Home Win Clustering ===")

md_home_counts = defaultdict(lambda: Counter())  # md -> home_wins_count -> occurrences

for (season, day), ms in md_matches.items():
    if len(ms) != 8:
        continue
    home_wins = sum(1 for m in ms if m['outcome'] == 'HOME')
    md_home_counts[day][home_wins] += 1

home_clustering = {}
for day in sorted(md_home_counts.keys()):
    counter = md_home_counts[day]
    total_seasons = sum(counter.values())
    distribution = {}
    for hw in range(9):  # 0 to 8
        count = counter.get(hw, 0)
        pct = count / total_seasons * 100 if total_seasons > 0 else 0
        distribution[str(hw)] = {'count': count, 'pct': round(pct, 2)}
    
    # Calculate mean, variance, std
    total_hw = sum(hw * counter[hw] for hw in range(9))
    mean_hw = total_hw / total_seasons if total_seasons > 0 else 0
    variance = sum(counter[hw] * (hw - mean_hw)**2 for hw in range(9)) / total_seasons if total_seasons > 0 else 0
    
    home_clustering[day] = {
        'total_seasons': total_seasons,
        'mean_home_wins': round(mean_hw, 3),
        'variance': round(variance, 3),
        'std_dev': round(math.sqrt(variance), 3),
        'distribution': distribution
    }
    
    dist_str = ', '.join(f"{hw}:{counter.get(hw,0)}" for hw in range(9))
    print(f"  MD {day:2d}: mean={mean_hw:.2f} home wins, dist=[{dist_str}]")

# Global home win distribution
global_hw_counter = Counter()
for (season, day), ms in md_matches.items():
    if len(ms) != 8:
        continue
    home_wins = sum(1 for m in ms if m['outcome'] == 'HOME')
    global_hw_counter[home_wins] += 1
total_gs = sum(global_hw_counter.values())
global_mean_hw = sum(hw * global_hw_counter[hw] for hw in range(9)) / total_gs
print(f"\n  Global: mean={global_mean_hw:.2f} home wins per MD")
print(f"  Global distribution: {dict(sorted(global_hw_counter.items()))}")

# =====================================================
# ANALYSIS 5: Miss pattern check - fixture-specific outcomes
# =====================================================
print("\n=== ANALYSIS 5: Fixture-Based Outcome Analysis ===")

# For each fixture pairing at each MD, get the outcome distribution
fixture_outcomes = defaultdict(lambda: defaultdict(lambda: {'HOME': 0, 'AWAY': 0, 'DRAW': 0}))

for m in matches:
    key = (m['day'], m['home'], m['away'])
    fixture_outcomes[m['day']][(m['home'], m['away'])][m['outcome']] += 1

# Find fixtures with extreme bias (always or never HOME)
fixture_analysis = {}
for day in sorted(fixture_outcomes.keys()):
    fixtures = []
    for (home, away), outcomes in fixture_outcomes[day].items():
        total = sum(outcomes.values())
        hp = outcomes['HOME'] / total * 100 if total > 0 else 0
        ap = outcomes['AWAY'] / total * 100 if total > 0 else 0
        dp = outcomes['DRAW'] / total * 100 if total > 0 else 0
        
        fixture_entry = {
            'home': home,
            'away': away,
            'total_occurrences': total,
            'home_wins': outcomes['HOME'],
            'away_wins': outcomes['AWAY'],
            'draws': outcomes['DRAW'],
            'home_pct': round(hp, 1),
            'away_pct': round(ap, 1),
            'draw_pct': round(dp, 1)
        }
        
        # Flag extreme fixtures
        flags = []
        if hp == 100:
            flags.append('ALWAYS_HOME')
        elif hp == 0 and ap > 0 and dp > 0:
            flags.append('NEVER_HOME')
        if ap == 100:
            flags.append('ALWAYS_AWAY')
        if dp == 0 and hp > 0 and ap > 0:
            flags.append('NEVER_DRAW')
        if total >= 5:
            if hp >= 75:
                flags.append('STRONG_HOME')
            if ap >= 75:
                flags.append('STRONG_AWAY')
        
        if flags:
            fixture_entry['flags'] = flags
        
        fixtures.append(fixture_entry)
    
    # Sort by most biased first
    fixtures_sorted = sorted(fixtures, key=lambda x: max(x['home_pct'], x['away_pct'], x['draw_pct']), reverse=True)
    fixture_analysis[day] = fixtures_sorted
    
    # Show extreme examples
    extreme = [f for f in fixtures_sorted if f.get('flags')]
    if extreme:
        for f in extreme[:3]:
            print(f"  MD {day:2d}: {f['home']} vs {f['away']} — H:{f['home_pct']}% A:{f['away_pct']}% D:{f['draw_pct']}% ({f['total_occurrences']}x) [{','.join(f.get('flags',[]))}]")

# Count extreme fixtures across all MDs
total_extreme = sum(1 for day in fixture_analysis for f in fixture_analysis[day] if f.get('flags'))
always_home = sum(1 for day in fixture_analysis for f in fixture_analysis[day] if 'ALWAYS_HOME' in f.get('flags',[]))
always_away = sum(1 for day in fixture_analysis for f in fixture_analysis[day] if 'ALWAYS_AWAY' in f.get('flags',[]))
never_draw = sum(1 for day in fixture_analysis for f in fixture_analysis[day] if 'NEVER_DRAW' in f.get('flags',[]))
strong_home = sum(1 for day in fixture_analysis for f in fixture_analysis[day] if 'STRONG_HOME' in f.get('flags',[]))
strong_away = sum(1 for day in fixture_analysis for f in fixture_analysis[day] if 'STRONG_AWAY' in f.get('flags',[]))

print(f"\n  Total extreme fixtures: {total_extreme}")
print(f"  Always HOME: {always_home}")
print(f"  Always AWAY: {always_away}")
print(f"  Never DRAW: {never_draw}")
print(f"  Strong HOME bias (>=75%): {strong_home}")
print(f"  Strong AWAY bias (>=75%): {strong_away}")

# =====================================================
# COMPILE FINAL OUTPUT
# =====================================================
print("\n=== COMPILING FINAL OUTPUT ===")

# Sort deviant MDs by deviation score
deviant_mds.sort(key=lambda x: -x['deviation_score'])

output = {
    'metadata': {
        'analysis_name': 'Clara Permutation Analysis',
        'analyst': 'Clara',
        'database': str(DB_PATH),
        'total_seasons_analyzed': len(seasons_to_use),
        'total_seasons_available': len(all_seasons),
        'global_averages': {
            'home_pct': round(global_home_pct, 2),
            'away_pct': round(global_away_pct, 2),
            'draw_pct': round(global_draw_pct, 2),
            'total_matches': total_all,
            'home_wins': total_home,
            'away_wins': total_away,
            'draws': total_draw
        },
        'total_possible_patterns_per_md': total_possible_patterns
    },
    'per_md_outcome_distribution': md_distribution,
    'deviant_mds': deviant_mds,
    'permutation_space': permutation_analysis,
    'never_seen_patterns': never_seen_analysis,
    'home_win_clustering': home_clustering,
    'global_home_win_clustering': {
        'distribution': {str(hw): {'count': c, 'pct': round(c/total_gs*100, 2)} 
                         for hw, c in sorted(global_hw_counter.items())},
        'mean_home_wins': round(global_mean_hw, 3),
        'total_seasons': total_gs
    },
    'fixture_analysis': fixture_analysis,
    'extreme_fixture_summary': {
        'total_extreme_fixtures': total_extreme,
        'always_home': always_home,
        'always_away': always_away,
        'never_draw': never_draw,
        'strong_home_bias_pct75': strong_home,
        'strong_away_bias_pct75': strong_away
    },
    'key_findings': {
        'deviant_md_count': len(deviant_mds),
        'md_positions_to_adjust': [d['md'] for d in deviant_mds],
        'average_distinct_patterns_per_md': round(
            sum(len(md_patterns[d]) for d in md_patterns) / len(md_patterns), 2
        ),
        'total_distinct_patterns_all_mds': sum(len(md_patterns[d]) for d in md_patterns),
        'average_coverage_pct': round(
            sum(len(md_patterns[d]) / total_possible_patterns for d in md_patterns) / len(md_patterns) * 100, 4
        )
    }
}

# Write output
with open(OUTPUT_PATH, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nAnalysis saved to {OUTPUT_PATH}")
print(f"File size: {len(json.dumps(output, indent=2, default=str))} bytes")

# Summary
print("\n=== KEY FINDINGS SUMMARY ===")
print(f"Global outcome split: {global_home_pct:.1f}% HOME, {global_away_pct:.1f}% AWAY, {global_draw_pct:.1f}% DRAW")
print(f"Deviant MD positions (deviation > 5%): {len(deviant_mds)}")
for d in deviant_mds:
    print(f"  MD {d['md']:2d}: dev={d['deviation_score']:.1f}, H={d['home_pct']:.1f}% A={d['away_pct']:.1f}% D={d['draw_pct']:.1f}%")

conn.close()
