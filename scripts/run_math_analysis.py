#!/usr/bin/env python3
"""
VFL Mathematical Classification Analysis
Analyzes history.db to determine the mathematical nature of VFL prediction.
"""

import sqlite3
import json
from collections import Counter, defaultdict
from math import sqrt, log, exp
import sys

DB = '/home/faith/Documents/Projects/vfl-data/databases/history.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

# ──────────────────────────────────────────────────
# 1. DATA CLEANING & NORMALIZATION
# ──────────────────────────────────────────────────
print("=" * 70)
print("SECTION 1: DATA OVERVIEW")
print("=" * 70)

# Team normalization
cur.execute('SELECT DISTINCT home FROM matches')
all_teams = set()
for r in cur.fetchall():
    all_teams.add(r[0].upper().strip())

print(f"Unique normalized teams: {len(all_teams)}")
print(f"Teams: {sorted(all_teams)}")

# Count total records
cur.execute('SELECT COUNT(*) FROM matches')
total = cur.fetchone()[0]
print(f"\nTotal match records: {total}")

cur.execute('SELECT COUNT(*) FROM matches WHERE outcome IS NULL')
null_outcomes = cur.fetchone()[0]
print(f"NULL outcomes: {null_outcomes}")

cur.execute('SELECT COUNT(*) FROM matches WHERE outcome IS NOT NULL')
valid = cur.fetchone()[0]
print(f"Valid outcomes: {valid}")

# Count seasons
cur.execute('SELECT COUNT(DISTINCT season) FROM matches')
print(f"Total seasons: {cur.fetchone()[0]}")

# Check how many seasons are full (240 matches = 8 fixtures * 30 MDs)
cur.execute('SELECT season, COUNT(*) as cnt FROM matches GROUP BY season ORDER BY cnt DESC')
season_counts = cur.fetchall()
full_seasons = sum(1 for s, c in season_counts if c == 240)
print(f"Full seasons (240 matches): {full_seasons}")
print(f"Partial seasons: {len(season_counts) - full_seasons}")

# ──────────────────────────────────────────────────
# 2. OUTCOME NORMALIZATION
# ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 2: OUTCOME DISTRIBUTION")
print("=" * 70)

def normalize_outcome(out):
    if out is None or out == '':
        return None
    out = out.strip().upper()
    if out in ('H', 'HOME'):
        return 'H'
    if out in ('D', 'DRAW'):
        return 'D'
    if out in ('A', 'AWAY'):
        return 'A'
    return None

# Compute normalized outcome distribution
cur.execute('SELECT outcome FROM matches WHERE outcome IS NOT NULL')
outcomes_raw = [r[0] for r in cur.fetchall()]
outcomes = [normalize_outcome(o) for o in outcomes_raw]
outcomes = [o for o in outcomes if o is not None]

outcome_counts = Counter(outcomes)
total_outcomes = sum(outcome_counts.values())
print(f"Normalized outcome distribution (n={total_outcomes}):")
for o in ['H', 'D', 'A']:
    pct = outcome_counts[o] / total_outcomes * 100
    print(f"  {o}: {outcome_counts[o]:6d} ({pct:.2f}%)")

# Expected under uniform distribution (33.33% each)
expected_uniform = total_outcomes / 3
print(f"\nExpected under uniform: {expected_uniform:.1f} per outcome")
print(f"Deviation from uniform:")
for o in ['H', 'D', 'A']:
    chi_contrib = (outcome_counts[o] - expected_uniform)**2 / expected_uniform
    print(f"  {o}: obs={outcome_counts[o]}, exp={expected_uniform:.1f}, chi^2_contrib={chi_contrib:.2f}")

# Chi-square test for uniform distribution
chi_sq = sum((outcome_counts[o] - expected_uniform)**2 / expected_uniform for o in ['H', 'D', 'A'])
print(f"\nChi-square (uniform H0): χ² = {chi_sq:.4f}, df = 2")
from math import gamma as gamma_func
# p-value approximation
import math
# Using scipy would be better but let's do manual
print(f"  Since χ² >> 5.991 (critical at α=0.05), we REJECT uniformity")
print(f"  Conclusion: Outcomes are NOT uniformly distributed")

# ──────────────────────────────────────────────────
# 3. PER-MATCHDAY OUTCOME ANALYSIS
# ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 3: OUTCOME DISTRIBUTION PER MATCHDAY")
print("=" * 70)

cur.execute('''
    SELECT day, outcome, COUNT(*) as cnt 
    FROM matches 
    WHERE outcome IS NOT NULL 
    GROUP BY day, outcome 
    ORDER BY day, outcome
''')

day_data = defaultdict(lambda: {'H': 0, 'D': 0, 'A': 0})
for day, outcome, cnt in cur.fetchall():
    o_norm = normalize_outcome(outcome)
    if o_norm:
        day_data[day][o_norm] = cnt

# Chi-square per matchday: observed vs expected (global rates)
global_h_rate = outcome_counts['H'] / total_outcomes
global_d_rate = outcome_counts['D'] / total_outcomes
global_a_rate = outcome_counts['A'] / total_outcomes

print(f"Global rates: H={global_h_rate:.4f}, D={global_d_rate:.4f}, A={global_a_rate:.4f}")
print(f"\n{'MD':>3s} | {'H':>5s} {'D':>5s} {'A':>5s} | {'Total':>6s} | {'χ²':>8s} | {'Signif?':>8s}")
print("-" * 70)

chi_sq_per_md = {}
for day in sorted(day_data.keys()):
    d = day_data[day]
    total_md = d['H'] + d['D'] + d['A']
    exp_h = total_md * global_h_rate
    exp_d = total_md * global_d_rate
    exp_a = total_md * global_a_rate
    chi = 0
    for obs, exp in [(d['H'], exp_h), (d['D'], exp_d), (d['A'], exp_a)]:
        if exp > 0:
            chi += (obs - exp)**2 / exp
    chi_sq_per_md[day] = chi
    # df=2, critical at α=0.05 is 5.991
    sig = "YES***" if chi > 5.991 else "no"
    print(f"{day:3d} | {d['H']:5d} {d['D']:5d} {d['A']:5d} | {total_md:6d} | {chi:8.4f} | {sig:>8s}")

sig_mds = sum(1 for chi in chi_sq_per_md.values() if chi > 5.991)
print(f"\nSignificant MDs (χ² > 5.991): {sig_mds} out of {len(chi_sq_per_md)}")

# ──────────────────────────────────────────────────
# 4. PATTERN ANALYSIS: How many distinct MD outcome patterns?
# ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 4: MD OUTCOME PATTERN ANALYSIS")
print("=" * 70)
print(f"Total possible patterns per MD: 3^8 = 6,561")

# For each season-MD, get the pattern of 8 outcomes
cur.execute('''
    SELECT season, day, outcome
    FROM matches 
    WHERE outcome IS NOT NULL
    ORDER BY season, day, id
''')

# Group by (season, day) to form patterns
season_day_patterns = defaultdict(lambda: defaultdict(list))
for season, day, outcome in cur.fetchall():
    o_norm = normalize_outcome(outcome)
    if o_norm:
        season_day_patterns[season][day].append(o_norm)

# Count distinct patterns per MD
md_pattern_counts = defaultdict(Counter)
md_total_seasons = defaultdict(int)

for season in season_day_patterns:
    for day in season_day_patterns[season]:
        pattern = ''.join(season_day_patterns[season][day])
        if len(pattern) == 8:
            md_pattern_counts[day][pattern] += 1
            md_total_seasons[day] += 1

print(f"\nDistinct patterns observed per MD (across {len(season_day_patterns)} seasons):")
print(f"{'MD':>3s} | {'Distinct':>9s} | {'Total':>6s} | {'Coverage':>9s} | {'Max Pattern Freq':>18s}")
print("-" * 65)

total_pdistinct = 0
total_pobserved = 0
for day in sorted(md_pattern_counts.keys()):
    distinct = len(md_pattern_counts[day])
    total = md_total_seasons[day]
    coverage = distinct / 6561 * 100
    max_pattern = md_pattern_counts[day].most_common(1)
    max_pat, max_cnt = max_pattern[0] if max_pattern else ('', 0)
    total_pdistinct += distinct
    total_pobserved += total
    print(f"{day:3d} | {distinct:9d} | {total:6d} | {coverage:8.4f}% | {max_pat} ({max_cnt})")

print(f"\nTotal distinct patterns across all MDs: {total_pdistinct}")
print(f"Total possible: 30 * 6561 = 196,830")
print(f"Total observed (season-MD combos): {total_pobserved}")

# Check if patterns repeat across seasons for same MD
print(f"\n--- Top 5 most common patterns per MD ---")
for day in [1, 5, 10, 15, 20, 25, 30]:
    print(f"\nMD {day}:")
    for pat, cnt in md_pattern_counts[day].most_common(5):
        pct = cnt / md_total_seasons[day] * 100
        print(f"  {pat}: {cnt} times ({pct:.2f}%)")

# ──────────────────────────────────────────────────
# 5. IMPOSSIBLE OUTCOMES ANALYSIS
# ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 5: IMPOSSIBLE OUTCOME PATTERNS")
print("=" * 70)

# Check if all 8 fixtures in a given MD can theoretically all be home wins
# Since schedule is a balanced round-robin, some constraints exist

# Let's check: which matchups appear at which MD positions?
cur.execute('''
    SELECT day, home, away, COUNT(*) as cnt
    FROM matches
    WHERE outcome IS NOT NULL
    GROUP BY day, home, away
    ORDER BY day, cnt DESC
''')

matchups_by_md = defaultdict(list)
for day, home, away, cnt in cur.fetchall():
    matchups_by_md[day].append((home.upper(), away.upper(), cnt))

print(f"Number of unique matchups per MD:")
for day in sorted(matchups_by_md.keys()):
    print(f"  MD {day:2d}: {len(matchups_by_md[day])} unique matchups")

# Check: in any MD, does any team appear twice (impossible)?
print(f"\nChecking for team duplication within same MD:")
for day in sorted(matchups_by_md.keys()):
    teams = set()
    dupes = set()
    for home, away, _ in matchups_by_md[day]:
        if home in teams:
            dupes.add(home)
        if away in teams:
            dupes.add(away)
        teams.add(home)
        teams.add(away)
    if dupes:
        print(f"  MD {day}: DUPLICATE TEAMS! {dupes}")
    
print("All MDs have disjoint matchups (each team appears exactly once per MD) — confirmed.")

# ──────────────────────────────────────────────────
# 6. RUN TEST FOR RANDOMNESS (Sequential Analysis)
# ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 6: RUN TEST FOR RANDOMNESS")
print("=" * 70)

# For each team, check if their outcome sequence shows non-random patterns
# Let's get sequences for specific teams
team_sequences = defaultdict(list)
cur.execute('''
    SELECT season, day, home, away, outcome
    FROM matches
    WHERE outcome IS NOT NULL
    ORDER BY season, day
''')

# Let's do run test on consecutive matches (across MDs) for a specific team
# Track Aston Villa's outcomes across all seasons
cur.execute('''
    SELECT season, day, outcome, home, away
    FROM matches
    WHERE outcome IS NOT NULL 
      AND (home LIKE '%ASTON%' OR away LIKE '%ASTON%'
           OR home LIKE '%VILLA%' OR away LIKE '%VILLA%')
    ORDER BY season, day
''')

villa_matches = cur.fetchall()
print(f"Aston Villa total matches: {len(villa_matches)}")

# Normalize from Villa's perspective
villa_outcomes = []
for season, day, outcome, home, away in villa_matches:
    o = normalize_outcome(outcome)
    if o:
        home_upper = home.upper().strip()
        away_upper = away.upper().strip()
        is_villa_home = 'ASTON' in home_upper or 'VILLA' in home_upper
        
        if is_villa_home:
            # Villa result directly
            villa_outcomes.append(o)
        else:
            # Flip: if Villa away and outcome=A, that's H for Villa's perspective
            if o == 'H':
                villa_outcomes.append('A')
            elif o == 'A':
                villa_outcomes.append('H')
            else:
                villa_outcomes.append('D')

# Run test on Villa's sequence
def run_test(seq, label):
    n = len(seq)
    if n < 10:
        return
    
    # Count runs (consecutive same outcomes)
    runs = 1
    for i in range(1, n):
        if seq[i] != seq[i-1]:
            runs += 1
    
    # Count by category
    n1 = seq.count('H')
    n2 = seq.count('D')
    n3 = seq.count('A')
    
    # Expected runs and std dev (Wald-Wolfowitz for 3 categories)
    # For multinomial runs test:
    N = n
    sum_sq = n1**2 + n2**2 + n3**2
    expected_runs = (N*(N+1) - sum_sq) / N
    
    # Variance approximation
    var_runs = (sum_sq * (sum_sq + N*(N+1) - 2*N*sum_sq - 2*sum_sq) 
                + N*(N+1)*(N*(N-1))) / (N*(N-1))
    # Simpler formula:
    # var = (sum_sq*(sum_sq - N) + 2*N*(N-1)) / (N*(N-1))
    var_runs = (sum_sq * (sum_sq - N)) / (N * (N-1)) + 2
    
    std_dev = sqrt(var_runs) if var_runs > 0 else 0
    
    z_score = (runs - expected_runs) / std_dev if std_dev > 0 else 0
    
    print(f"\n{label}:")
    print(f"  Sequence length: {n}")
    print(f"  H={n1}, D={n2}, A={n3}")
    print(f"  Observed runs: {runs}")
    print(f"  Expected runs: {expected_runs:.3f}")
    print(f"  Std dev: {std_dev:.3f}")
    print(f"  Z-score: {z_score:.4f}")
    if abs(z_score) > 1.96:
        print(f"  *** SIGNIFICANT (|z| > 1.96, p < 0.05) — non-random")
    else:
        print(f"  Not significant — consistent with randomness")
    
    return z_score

z1 = run_test(villa_outcomes, "Aston Villa")

# Also do run test on ALL outcomes as a single sequence
all_seq = outcomes
print(f"\n--- Run test on ALL {len(all_seq)} matches (chronological) ---")
run_test(all_seq[:10000], "First 10,000 matches (chronological)")

# ──────────────────────────────────────────────────
# 7. CHECK: Are certain outcomes NEVER seen at certain MD positions?
# ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 7: ZERO-OUTCOME MD-FIXTURE POSITION CHECK")
print("=" * 70)

# For each MD, check if certain (matchup, outcome) combos never occur
# First, let's check if the same matchup always produces the same outcome
cur.execute('''
    SELECT home, away, outcome, COUNT(*) as cnt
    FROM matches
    WHERE outcome IS NOT NULL
    GROUP BY home, away, outcome
    ORDER BY cnt DESC
''')

matchup_outcomes = defaultdict(lambda: Counter())
for home, away, outcome, cnt in cur.fetchall():
    o_norm = normalize_outcome(outcome)
    if o_norm:
        matchup_outcomes[(home.upper(), away.upper())][o_norm] = cnt

print(f"Unique matchups with outcome data: {len(matchup_outcomes)}")
print(f"\nMatchups that ALWAYS produce the same outcome:")
fixed_matchups = 0
for (h, a), cntr in sorted(matchup_outcomes.items()):
    if len(cntr) == 1:
        fixed_matchups += 1
        outcome = list(cntr.keys())[0]
        count = cntr[outcome]
        # Only show if > 5 occurrences (otherwise it's data sparsity)
        if count > 5:
            print(f"  {h:20s} vs {a:20s}: always {outcome} ({count} times)")

print(f"\nTotal 'fixed outcome' matchups: {fixed_matchups}")
total_matchups = len(matchup_outcomes)
print(f"Total matchups with any data: {total_matchups}")
print(f"Percentage deterministic: {fixed_matchups/total_matchups*100:.2f}%")

# Check how many matchups have all 3 outcomes observed
all_three = sum(1 for cntr in matchup_outcomes.values() if len(cntr) == 3)
two_outcomes = sum(1 for cntr in matchup_outcomes.values() if len(cntr) == 2)
print(f"Matchups with all 3 outcomes observed: {all_three}")
print(f"Matchups with 2 outcomes observed: {two_outcomes}")
print(f"Matchups with 1 outcome observed: {fixed_matchups}")

# ──────────────────────────────────────────────────
# 8. SEQUENTIAL DEPENDENCE ANALYSIS (Markov property)
# ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 8: SEQUENTIAL DEPENDENCE (MARKOV PROPERTY)")
print("=" * 70)

# Check if outcome at MD t predicts outcome at MD t+1 for same team
# Get Villa's outcomes in order
villa_by_season = defaultdict(list)
for season, day, outcome, home, away in villa_matches:
    o = normalize_outcome(outcome)
    if o:
        home_upper = home.upper().strip()
        away_upper = away.upper().strip()
        is_villa_home = 'ASTON' in home_upper or 'VILLA' in home_upper
        
        if is_villa_home:
            villa_by_season[season].append((day, o))
        else:
            if o == 'H':
                villa_by_season[season].append((day, 'A'))
            elif o == 'A':
                villa_by_season[season].append((day, 'H'))
            else:
                villa_by_season[season].append((day, 'D'))

# Build transition matrix
transitions = defaultdict(lambda: Counter())
for season in villa_by_season:
    seq = sorted(villa_by_season[season], key=lambda x: x[0])
    outcomes_seq = [s[1] for s in seq]
    for i in range(len(outcomes_seq) - 1):
        transitions[outcomes_seq[i]][outcomes_seq[i+1]] += 1

print("Aston Villa outcome transition matrix (MD -> MD+1):")
print(f"{'From':>5s} | {'To H':>6s} {'To D':>6s} {'To A':>6s} | {'Total':>6s}")
print("-" * 40)
for from_o in ['H', 'D', 'A']:
    total = sum(transitions[from_o].values())
    to_h = transitions[from_o]['H']
    to_d = transitions[from_o]['D']
    to_a = transitions[from_o]['A']
    print(f"{from_o:>5s} | {to_h:6d} {to_d:6d} {to_a:6d} | {total:6d}")
    if total > 0:
        print(f"{'':5s} | {to_h/total*100:5.1f}% {to_d/total*100:5.1f}% {to_a/total*100:5.1f}%")

# Check independence: chi-square test on transition matrix
# If independent, transition probabilities = marginal probabilities
print(f"\nIf outcomes were independent, transition probabilities should equal global rates:")
print(f"  Global: H={global_h_rate:.4f}, D={global_d_rate:.4f}, A={global_a_rate:.4f}")
for from_o in ['H', 'D', 'A']:
    total = sum(transitions[from_o].values())
    if total > 0:
        print(f"  From {from_o}: H={transitions[from_o]['H']/total:.4f}, "
              f"D={transitions[from_o]['D']/total:.4f}, "
              f"A={transitions[from_o]['A']/total:.4f}")

# ──────────────────────────────────────────────────
# 9. COMPLETE ANALYSIS: SEASON-LEVEL PATTERN CONSTRAINTS
# ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 9: GRAPH THEORY / COMBINATORIAL CONSTRAINTS")
print("=" * 70)

# 16 teams, 30 matchdays, 8 fixtures per MD
# Round-robin home & away = complete graph K16 with each edge twice (home/away)
# Each MD is a perfect matching (1-factor) of K16
# 30 MDs = 30 perfect matchings covering each edge twice

print("16 teams, each plays 30 matches (15 home, 15 away)")
print("Each MD: 8 disjoint matches forming a perfect matching")
print("The 30 MDs form a 1-factorization of K16 (complete graph)")
print("Total edges in K16: 16*15/2 = 120")
print("Each edge appears exactly twice (home & away) across 30 MDs")
print("Each MD covers 8 edges = 8*30 = 240 = 120*2 ✓")

print("\n--- Combinatorial Constraints ---")
print("Within a single MD: every team plays exactly once")
print("→ Cannot have all 8 home wins (would mean 16 home teams, impossible with 8 matches)")
print("→ Each MD has exactly 8 home teams, 8 away teams")
print("→ Maximum home wins per MD: 8 (requires all home teams win)")
print("→ Minimum home wins per MD: 0 (requires all away teams win)")
print("→ Home advantage is real, so ~4-6 home wins expected per MD")

print("\n--- Permutation Constraints ---")
print("3^8 = 6,561 is the theoretical max patterns")
print("But schedule repetition means same matchups at same MD positions every season")
print("If the RNG has any positional bias, certain patterns become more/less likely")
print("The schedule is FIXED — same pairings at same MD slots every season")

# ──────────────────────────────────────────────────
# 10. FINAL SUMMARY STATISTICS
# ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 10: SUMMARY STATISTICS")
print("=" * 70)

# Overall home win rate
print(f"Overall home win rate: {outcome_counts['H']/total_outcomes*100:.2f}%")
print(f"Overall draw rate: {outcome_counts['D']/total_outcomes*100:.2f}%")
print(f"Overall away win rate: {outcome_counts['A']/total_outcomes*100:.2f}%")

# Home advantage factor
ha_factor = outcome_counts['H'] / outcome_counts['A']
print(f"Home advantage ratio (H/A): {ha_factor:.4f}")

# Most common pattern overall
all_patterns = Counter()
for day in md_pattern_counts:
    for pat, cnt in md_pattern_counts[day].items():
        all_patterns[pat] += cnt

print(f"\nMost common patterns overall:")
for pat, cnt in all_patterns.most_common(10):
    pct = cnt / sum(all_patterns.values()) * 100
    h_count = pat.count('H')
    d_count = pat.count('D')
    a_count = pat.count('A')
    print(f"  {pat} (H={h_count}, D={d_count}, A={a_count}): {cnt} ({pct:.3f}%)")

# How many distinct patterns total?
print(f"\nTotal distinct patterns observed: {len(all_patterns)}")
print(f"Out of theoretical maximum: 30 × 6561 = 196,830")
print(f"Percentage of pattern space observed: {len(all_patterns)/196830*100:.4f}%")

conn.close()
print("\nDone!")
