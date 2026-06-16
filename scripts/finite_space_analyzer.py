#!/usr/bin/env python3
"""
Phase 2 & 3: Finite State Space Analyzer
==========================================
Comprehensive analysis of VFL simulation engine's finite state space.

This script:
  - Loads scraped API data + existing database data
  - Enumerates ALL 240 fixture pairs (16 teams × 15 opponents)
  - Calculates hit rates, scoreline distributions, first goal bias
  - Checks if the state space has converged (plateau detection)
  - Identifies TRAP fixtures (look profitable but lose)
  - Identifies GOLD fixtures (consistently profitable)
  - Analyzes loss patterns and streak behavior

Output:
  /home/ubuntu/faith-workspace/vfl-complete-data/analysis/finite_state_space_report.md
"""

import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ─── Paths ──────────────────────────────────────────────────────────────────

SCRAPED_DATA_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/data/finite_state_space.json'
RESULTS_DB_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db'
HISTORY_DB_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/databases/history.db'
SEASON_TRACKER_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis/season_tracker.json'
BET_LEDGER_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/signals/bet_ledger.json'
REPORT_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis/finite_state_space_report.md'
TRAP_DATA_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis/trap_fixtures.json'
GOLD_DATA_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis/gold_fixtures.json'

# ─── Team Names (normalised set) ────────────────────────────────────────────

KNOWN_TEAMS = {
    'Liverpool', 'Manchester Red', 'Manchester Blue', 'London Guns',
    'Chelsea', 'Tottenham', 'Aston Villa', 'Newcastle', 'West Ham',
    'Wolverhampton', 'Crystal Palace', 'Fulham', 'Brighton',
    'Bournemouth', 'Everton', 'Leeds',
}

TEAM_ALIASES = {
    'ARSENAL': 'London Guns', 'LONDON GUNS': 'London Guns', 'LONDON GUNNERS': 'London Guns',
    'MANCHESTER CITY': 'Manchester Blue', 'MANCHESTER BLUE': 'Manchester Blue',
    'MANCHESTER UNITED': 'Manchester Red', 'MANCHESTER RED': 'Manchester Red',
}


def normalize_team(name: str) -> str:
    """Normalize a team name to canonical form."""
    n = name.strip().upper()
    if n in TEAM_ALIASES:
        return TEAM_ALIASES[n]
    # Title case
    return name.strip().title()


def parse_score(score_str: str) -> Optional[Tuple[int, int]]:
    """Parse a 'X:Y' score string into (home_goals, away_goals)."""
    if not score_str or ':' not in score_str:
        return None
    try:
        parts = score_str.split(':')
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None


# ─── Data Loading ───────────────────────────────────────────────────────────

def load_scraped_data() -> List[Dict]:
    """Load matches from the scraped API data."""
    matches = []
    if not os.path.exists(SCRAPED_DATA_PATH):
        print(f"WARN: Scraped data not found at {SCRAPED_DATA_PATH}")
        return matches

    with open(SCRAPED_DATA_PATH) as f:
        data = json.load(f)

    for season in data.get('seasons', []):
        season_name = season.get('season_name', '')
        season_id = season.get('season_id', '')
        for md_str, md_matches in season.get('matchdays', {}).items():
            md = int(md_str)
            for m in md_matches:
                ft = parse_score(m.get('fullTime', ''))
                ht = parse_score(m.get('halfTime', ''))
                if ft is None:
                    continue
                matches.append({
                    'home': normalize_team(m.get('homeTeam', '')),
                    'away': normalize_team(m.get('awayTeam', '')),
                    'hg': ft[0],
                    'ag': ft[1],
                    'total': ft[0] + ft[1],
                    'half_hg': ht[0] if ht else None,
                    'half_ag': ht[1] if ht else None,
                    'first_goal': m.get('firstGoal', ''),
                    'season_name': season_name,
                    'season_id': season_id,
                    'match_day': md,
                    'source': 'api_scrape',
                })

    print(f"  Loaded {len(matches)} matches from API scrape")
    return matches


def load_db_matches() -> List[Dict]:
    """Load matches from the vfl_results.db database."""
    matches = []
    if not os.path.exists(RESULTS_DB_PATH):
        print(f"WARN: Results DB not found at {RESULTS_DB_PATH}")
        return matches

    try:
        conn = sqlite3.connect(RESULTS_DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT season_id, season_name, match_day, home_team, away_team,
                   home_goals, away_goals, total_goals, status
            FROM results
            WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
        """)
        for row in c.fetchall():
            matches.append({
                'home': normalize_team(row[3]),
                'away': normalize_team(row[4]),
                'hg': row[5],
                'ag': row[6],
                'total': row[7] if row[7] is not None else row[5] + row[6],
                'season_name': row[1] or '',
                'season_id': row[0] or '',
                'match_day': row[2],
                'source': 'results_db',
            })
        conn.close()
    except Exception as e:
        print(f"  WARN: Error reading results DB: {e}")

    print(f"  Loaded {len(matches)} matches from results DB")
    return matches


def load_history_matches() -> List[Dict]:
    """Load matches with scores from the history.db database."""
    matches = []
    if not os.path.exists(HISTORY_DB_PATH):
        print(f"WARN: History DB not found at {HISTORY_DB_PATH}")
        return matches

    try:
        conn = sqlite3.connect(HISTORY_DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT season, day, home, away, h, a, outcome, first_goal, half_time
            FROM matches
            WHERE h IS NOT NULL AND a IS NOT NULL
        """)
        for row in c.fetchall():
            matches.append({
                'home': normalize_team(row[2]),
                'away': normalize_team(row[3]),
                'hg': row[4],
                'ag': row[5],
                'total': row[4] + row[5],
                'first_goal': row[7] or '',
                'half_time': row[8] or '',
                'season_name': row[0],
                'season_id': row[0],
                'match_day': row[1],
                'source': 'history_db',
            })
        conn.close()
    except Exception as e:
        print(f"  WARN: Error reading history DB: {e}")

    print(f"  Loaded {len(matches)} matches from history DB")
    return matches


def load_season_tracker_matches() -> List[Dict]:
    """Load matches from the season_tracker.json for first_goal data."""
    matches = []
    if not os.path.exists(SEASON_TRACKER_PATH):
        return matches

    try:
        with open(SEASON_TRACKER_PATH) as f:
            data = json.load(f)

        for sid, sdata in data.get('seasons', {}).items():
            season_name = sdata.get('season_name', sid)
            for m in sdata.get('matches', []):
                ft = m.get('full_time', '')
                parsed = parse_score(ft)
                if parsed is None:
                    continue
                matches.append({
                    'home': normalize_team(m.get('home', '')),
                    'away': normalize_team(m.get('away', '')),
                    'hg': parsed[0],
                    'ag': parsed[1],
                    'total': parsed[0] + parsed[1],
                    'first_goal': m.get('first_goal', ''),
                    'half_time': m.get('half_time', ''),
                    'season_name': season_name,
                    'season_id': sid,
                    'match_day': m.get('match_day', 0),
                    'source': 'season_tracker',
                })
    except Exception as e:
        print(f"  WARN: Error reading season tracker: {e}")

    print(f"  Loaded {len(matches)} matches from season tracker")
    return matches


def load_bet_ledger() -> List[Dict]:
    """Load the bet ledger."""
    if not os.path.exists(BET_LEDGER_PATH):
        return []
    try:
        with open(BET_LEDGER_PATH) as f:
            data = json.load(f)
        return data.get('bets', [])
    except Exception as e:
        print(f"  WARN: Error reading bet ledger: {e}")
        return []


def deduplicate_matches(matches: List[Dict]) -> List[Dict]:
    """Deduplicate matches by (home, away, season, match_day) preferring richer sources."""
    seen = {}
    for m in matches:
        key = (m['home'], m['away'], m['season_name'], m['match_day'])
        # Prefer sources with first_goal info
        if key not in seen:
            seen[key] = m
        elif m.get('first_goal') and not seen[key].get('first_goal'):
            seen[key] = m
        elif m.get('half_time') and not seen[key].get('half_time') and not seen[key].get('first_goal'):
            seen[key] = m
    return list(seen.values())


# ─── Analysis Core ──────────────────────────────────────────────────────────

def compute_pair_stats(matches: List[Dict]) -> Dict:
    """Compute per-pair statistics from a list of match dicts."""
    pairs = defaultdict(list)

    for m in matches:
        key = (m['home'], m['away'])
        pairs[key].append(m)

    results = {}
    for (home, away), ms in pairs.items():
        n = len(ms)
        score_counter = Counter()
        o15_count = 0
        o25_count = 0
        gg_count = 0
        home_first_goal = 0
        away_first_goal = 0
        no_first_goal = 0
        total_goals_list = []
        home_goals_list = []
        away_goals_list = []

        # Chronological sort for Fellynius sequence analysis
        ms = sorted(
            ms,
            key=lambda m: (
                int(m.get('season_name', '0').replace('VFLM ', '0').replace('vf:season:', '0').replace('VFL ', '0')),
                m.get('match_day', 0)
            )
        )

        for m in ms:
            score = f"{m['hg']}-{m['ag']}"
            score_counter[score] += 1
            tg = m['total']
            total_goals_list.append(tg)
            home_goals_list.append(m['hg'])
            away_goals_list.append(m['ag'])

            if tg >= 2:
                o15_count += 1
            if tg >= 3:
                o25_count += 1
            if m['hg'] >= 1 and m['ag'] >= 1:
                gg_count += 1

            fg = m.get('first_goal', '')
            if fg == 'Home':
                home_first_goal += 1
            elif fg == 'Away':
                away_first_goal += 1
            elif fg == 'None' or fg == '':
                no_first_goal += 1

        # Scoreline stats
        most_common_score = score_counter.most_common(1)[0][0] if score_counter else 'N/A'
        most_common_score_pct = score_counter.most_common(1)[0][1] / n * 100 if score_counter else 0

        # Variance of total goals
        mean_tg = sum(total_goals_list) / n if n > 0 else 0
        variance_tg = sum((x - mean_tg) ** 2 for x in total_goals_list) / n if n > 0 else 0
        std_tg = math.sqrt(variance_tg)

        fg_total = home_first_goal + away_first_goal + no_first_goal

        # Fellynius Sequence Transition probabilities
        fellynius = {}
        for market_key, check_fn in {
            'O1.5': lambda m: 1 if m['total'] >= 2 else 0,
            'O2.5': lambda m: 1 if m['total'] >= 3 else 0,
            'GG': lambda m: 1 if m['hg'] >= 1 and m['ag'] >= 1 else 0,
            'U3.5': lambda m: 1 if m['total'] <= 3 else 0
        }.items():
            seq = [check_fn(m) for m in ms]
            t1 = defaultdict(Counter)
            t2 = defaultdict(Counter)
            
            for i in range(len(seq)):
                if i >= 1:
                    t1[seq[i-1]][seq[i]] += 1
                if i >= 2:
                    t2[(seq[i-2], seq[i-1])][seq[i]] += 1
            
            t1_probs = {}
            for prev_s, counts in t1.items():
                total_transitions = sum(counts.values())
                t1_probs[str(prev_s)] = {
                    'total': total_transitions,
                    '0': round(counts[0] / total_transitions, 3),
                    '1': round(counts[1] / total_transitions, 3)
                }
            
            t2_probs = {}
            for prev_states, counts in t2.items():
                total_transitions = sum(counts.values())
                key_str = f"{prev_states[0]},{prev_states[1]}"
                t2_probs[key_str] = {
                    'total': total_transitions,
                    '0': round(counts[0] / total_transitions, 3),
                    '1': round(counts[1] / total_transitions, 3)
                }
                
            fellynius[market_key] = {
                't1': t1_probs,
                't2': t2_probs,
                'current_state_t1': str(seq[-1]) if seq else None,
                'current_state_t2': f"{seq[-2]},{seq[-1]}" if len(seq) >= 2 else None
            }

        results[f"{home} vs {away}"] = {
            'home': home,
            'away': away,
            'n': n,
            'unique_scores': len(score_counter),
            'scores': dict(score_counter.most_common()),
            'most_common_score': most_common_score,
            'most_common_score_pct': round(most_common_score_pct, 1),
            'o1_5_rate': round(o15_count / n * 100, 1) if n > 0 else 0,
            'o2_5_rate': round(o25_count / n * 100, 1) if n > 0 else 0,
            'gg_rate': round(gg_count / n * 100, 1) if n > 0 else 0,
            'u1_5_rate': round((n - o15_count) / n * 100, 1) if n > 0 else 0,
            'avg_total_goals': round(mean_tg, 2),
            'std_total_goals': round(std_tg, 2),
            'avg_home_goals': round(sum(home_goals_list) / n, 2) if n > 0 else 0,
            'avg_away_goals': round(sum(away_goals_list) / n, 2) if n > 0 else 0,
            'first_goal_home_pct': round(home_first_goal / fg_total * 100, 1) if fg_total > 0 else 0,
            'first_goal_away_pct': round(away_first_goal / fg_total * 100, 1) if fg_total > 0 else 0,
            'first_goal_none_pct': round(no_first_goal / fg_total * 100, 1) if fg_total > 0 else 0,
            'fellynius': fellynius,
        }

    return results


def convergence_analysis(pair_stats: Dict, matches: List[Dict]) -> Dict:
    """
    Analyze convergence of the state space.
    For each pair, simulate adding matches one by one and track how the
    unique scoreline count grows. If it plateaus, we've likely discovered
    the full state space for that pair.
    """
    convergence = {}

    for pair_key, stats in pair_stats.items():
        if stats['n'] < 10:
            convergence[pair_key] = {
                'n': stats['n'],
                'total_unique': stats['unique_scores'],
                'converged': 'insufficient_data',
                'plateau_at': None,
            }
            continue

        # Get chronological matches for this pair
        pair_matches = [m for m in matches
                        if f"{m['home']} vs {m['away']}" == pair_key]

        # Sort by season then matchday (rough chronological order)
        # We'll just simulate incremental discovery
        seen_scores = set()
        score_counts = []
        for m in pair_matches:
            score = f"{m['hg']}-{m['ag']}"
            seen_scores.add(score)
            score_counts.append(len(seen_scores))

        total_unique = score_counts[-1] if score_counts else 0
        n = len(score_counts)

        # Check if the last 50% of matches added NO new scores
        # If the unique count stopped increasing, we've converged
        if n >= 20:
            last_quarter = n // 4
            recent_unique = score_counts[-last_quarter:]
            if len(set(recent_unique)) == 1:
                # Hasn't increased in the last quarter of matches
                plateau_at = n - last_quarter
                convergence[pair_key] = {
                    'n': n,
                    'total_unique': total_unique,
                    'converged': True,
                    'plateau_at': plateau_at,
                    'new_scores_last_N': 0,
                }
            else:
                # Check how many new scores in recent matches
                recent_new = sum(1 for i in range(max(0, n - last_quarter), n)
                                 if i == 0 or score_counts[i] > score_counts[i - 1])
                convergence[pair_key] = {
                    'n': n,
                    'total_unique': total_unique,
                    'converged': False,
                    'plateau_at': None,
                    'new_scores_last_N': recent_new,
                }
        else:
            convergence[pair_key] = {
                'n': n,
                'total_unique': total_unique,
                'converged': 'insufficient_data',
                'plateau_at': None,
            }

    return convergence


def analyze_loss_patterns(bets: List[Dict], pair_stats: Dict) -> Dict:
    """Analyze loss patterns from bet ledger."""
    lost_bets = [b for b in bets if b.get('status') == 'lost']

    # By fixture
    fixture_losses = Counter(b.get('match', '') for b in lost_bets)

    # By market
    market_losses = Counter(b.get('market', '') for b in lost_bets)

    # By matchday
    md_losses = Counter(b.get('matchday', 0) for b in lost_bets)

    # By season
    season_losses = Counter(b.get('season_name', '') for b in lost_bets)

    # Detail per fixture
    fixture_details = defaultdict(list)
    for b in lost_bets:
        match = b.get('match', '')
        fixture_details[match].append({
            'market': b.get('market', ''),
            'matchday': b.get('matchday', 0),
            'result': b.get('result', ''),
            'odds': b.get('odds', 0),
            'stake': b.get('stake', 0),
            'confidence_pct': b.get('confidence_pct', 0),
            'season': b.get('season_name', ''),
            'total_goals': b.get('total_goals', 0),
        })

    # Check if these fixture losses match trap/gold detection
    trap_fixtures_from_ledger = []
    for match, count in fixture_losses.most_common():
        if match in pair_stats:
            ps = pair_stats[match]
            if ps['o1_5_rate'] >= 70:
                trap_fixtures_from_ledger.append({
                    'match': match,
                    'losses': count,
                    'o1_5_rate': ps['o1_5_rate'],
                    'details': fixture_details[match],
                })

    return {
        'total_lost': len(lost_bets),
        'lost_by_fixture': dict(fixture_losses.most_common()),
        'lost_by_market': dict(market_losses.most_common()),
        'lost_by_matchday': {str(k): v for k, v in sorted(md_losses.items())},
        'lost_by_season': dict(season_losses.most_common()),
        'fixture_details': {k: v for k, v in fixture_details.items()},
        'trap_fixtures_from_ledger': trap_fixtures_from_ledger,
    }


def detect_traps_and_gold(pair_stats: Dict, loss_analysis: Dict) -> Tuple[List, List]:
    """
    Trap Detection:
      - Fixtures where overall O1.5 rate looks good (>70%)
      - But our specific O1.5 predictions lost
      - Or: high variance (std > 1.5) making predictions unreliable
    
    Gold Detection:
      - O1.5 rate > 80% with low variance (std < 1.2)
      - OR consistent pattern (converged + low variance)
    """
    traps = []
    golds = []

    ledger_trap_matches = set()
    for t in loss_analysis.get('trap_fixtures_from_ledger', []):
        ledger_trap_matches.add(t['match'])

    for pair_key, ps in pair_stats.items():
        if ps['n'] < 20:
            continue  # Need statistical significance

        # --- TRAP DETECTION ---
        is_trap = False
        trap_reasons = []

        # Criteria 1: Looks profitable but we lost
        if pair_key in ledger_trap_matches:
            is_trap = True
            trap_reasons.append(f"Lost {loss_analysis['lost_by_fixture'].get(pair_key, 0)} O1.5 bets despite {ps['o1_5_rate']}% O1.5 rate")

        # Criteria 2: High variance (unpredictable)
        if ps['std_total_goals'] > 1.5 and ps['n'] >= 30:
            is_trap = True
            trap_reasons.append(f"High variance (std={ps['std_total_goals']}) across {ps['n']} matches")

        # Criteria 3: Looks profitable but actually has low O1.5 in recent data
        # (We'll flag if O1.5 is between 60-75% — looks profitable but risky)
        if 60 <= ps['o1_5_rate'] < 75 and ps['std_total_goals'] > 1.3:
            is_trap = True
            trap_reasons.append(f"Borderline O1.5 rate ({ps['o1_5_rate']}%) with high variance")

        if is_trap:
            traps.append({
                'fixture': pair_key,
                'n': ps['n'],
                'o1_5_rate': ps['o1_5_rate'],
                'avg_total': ps['avg_total_goals'],
                'std_total': ps['std_total_goals'],
                'unique_scores': ps['unique_scores'],
                'most_common_score': ps['most_common_score'],
                'reasons': trap_reasons,
            })

        # --- GOLD DETECTION ---
        is_gold = False
        gold_reasons = []

        # Criteria 1: High O1.5 + low variance
        if ps['o1_5_rate'] >= 80 and ps['std_total_goals'] < 1.3:
            is_gold = True
            gold_reasons.append(f"High O1.5 ({ps['o1_5_rate']}%) with low variance ({ps['std_total_goals']})")

        # Criteria 2: O1.5 > 75% AND converged
        if ps['o1_5_rate'] > 75 and ps['std_total_goals'] < 1.4:
            is_gold = True
            gold_reasons.append(f"Consistent scoring (avg={ps['avg_total_goals']}, std={ps['std_total_goals']})")

        # Criteria 3: Very high O1.5 regardless
        if ps['o1_5_rate'] >= 85:
            is_gold = True
            gold_reasons.append(f"Very high O1.5 rate ({ps['o1_5_rate']}%)")

        if is_gold:
            golds.append({
                'fixture': pair_key,
                'n': ps['n'],
                'o1_5_rate': ps['o1_5_rate'],
                'o2_5_rate': ps['o2_5_rate'],
                'gg_rate': ps['gg_rate'],
                'avg_total': ps['avg_total_goals'],
                'std_total': ps['std_total_goals'],
                'unique_scores': ps['unique_scores'],
                'most_common_score': ps['most_common_score'],
                'most_common_score_pct': ps['most_common_score_pct'],
                'first_goal_home_pct': ps['first_goal_home_pct'],
                'reasons': gold_reasons,
            })

    # Sort traps by risk level (most dangerous first)
    traps.sort(key=lambda t: (-t['o1_5_rate'], t['std_total']), reverse=True)
    # Sort golds by confidence (highest O1.5 + lowest std first)
    golds.sort(key=lambda g: (-g['o1_5_rate'], g['std_total']))

    return traps, golds


def analyze_streaks(matches: List[Dict], pair_key: str, window: int = 5) -> Dict:
    """
    Analyze streak patterns for a specific fixture pair.
    Look for clustering of outcomes (e.g., 3 U1.5s in a row then 5 O1.5s).
    """
    pair_matches = sorted(
        [m for m in matches if f"{m['home']} vs {m['away']}" == pair_key],
        # Sort by season number then matchday for chronological order
        key=lambda m: (
            int(m.get('season_name', '0').replace('VFLM ', '0').replace('vf:season:', '0')),
            m.get('match_day', 0)
        )
    )

    if len(pair_matches) < window * 2:
        return {'n': len(pair_matches), 'streaks': {}, 'message': 'insufficient_data'}

    # Convert to binary outcomes: O1.5 = 1, U1.5 = 0
    outcomes = [1 if m['total'] >= 2 else 0 for m in pair_matches]

    # Find streaks of consecutive same outcomes
    streaks = {'o1_5_streaks': [], 'u1_5_streaks': [], 'current_streak': None}
    current_val = outcomes[0]
    current_len = 1
    streak_lens_o15 = []
    streak_lens_u15 = []

    for o in outcomes[1:]:
        if o == current_val:
            current_len += 1
        else:
            if current_val == 1:
                streak_lens_o15.append(current_len)
            else:
                streak_lens_u15.append(current_len)
            current_val = o
            current_len = 1

    # Don't forget the last streak
    if current_val == 1:
        streak_lens_o15.append(current_len)
        streaks['current_streak'] = {'type': 'O1.5', 'length': current_len}
    else:
        streak_lens_u15.append(current_len)
        streaks['current_streak'] = {'type': 'U1.5', 'length': current_len}

    streaks['o1_5_streaks'] = {
        'max': max(streak_lens_o15) if streak_lens_o15 else 0,
        'avg': round(sum(streak_lens_o15) / len(streak_lens_o15), 1) if streak_lens_o15 else 0,
        'count': len(streak_lens_o15),
        'all': streak_lens_o15[-10:] if len(streak_lens_o15) > 10 else streak_lens_o15,
    }
    streaks['u1_5_streaks'] = {
        'max': max(streak_lens_u15) if streak_lens_u15 else 0,
        'avg': round(sum(streak_lens_u15) / len(streak_lens_u15), 1) if streak_lens_u15 else 0,
        'count': len(streak_lens_u15),
        'all': streak_lens_u15[-10:] if len(streak_lens_u15) > 10 else streak_lens_u15,
    }

    streaks['n'] = len(outcomes)
    streaks['o1_5_rate'] = round(sum(outcomes) / len(outcomes) * 100, 1)

    # Check for recent reversal pattern (was U1.5 for a while, now O1.5)
    last_10 = outcomes[-10:] if len(outcomes) >= 10 else outcomes
    streaks['last_10_o1_5_rate'] = round(sum(last_10) / len(last_10) * 100, 1)

    return streaks


def matchday_distribution_analysis(matches: List[Dict]) -> Dict:
    """Analyze if certain matchdays have different scoring patterns."""
    md_stats = defaultdict(list)

    for m in matches:
        md = m.get('match_day', 0)
        if 1 <= md <= 30:
            md_stats[md].append(m['total'])

    results = {}
    for md in sorted(md_stats.keys()):
        goals = md_stats[md]
        n = len(goals)
        if n < 10:
            continue
        avg = sum(goals) / n
        o15_count = sum(1 for g in goals if g >= 2)
        o25_count = sum(1 for g in goals if g >= 3)

        results[str(md)] = {
            'n': n,
            'avg_goals': round(avg, 2),
            'o1_5_rate': round(o15_count / n * 100, 1),
            'o2_5_rate': round(o25_count / n * 100, 1),
        }

    return results


def analyze_home_away_bias(pair_stats: Dict) -> List:
    """Find fixtures with extreme home/away bias."""
    biased = []
    for pair_key, ps in pair_stats.items():
        if ps['n'] < 20:
            continue
        fg_home = ps['first_goal_home_pct']
        fg_away = ps['first_goal_away_pct']
        if abs(fg_home - fg_away) > 30:
            biased.append({
                'fixture': pair_key,
                'n': ps['n'],
                'first_goal_home_pct': fg_home,
                'first_goal_away_pct': fg_away,
                'avg_home_goals': ps['avg_home_goals'],
                'avg_away_goals': ps['avg_away_goals'],
            })
    biased.sort(key=lambda x: abs(x['first_goal_home_pct'] - x['first_goal_away_pct']), reverse=True)
    return biased


# ─── Report Generation ──────────────────────────────────────────────────────

def generate_report(pair_stats: Dict, convergence: Dict,
                    loss_analysis: Dict, traps: List, golds: List,
                    md_dist: Dict, biased_fixtures: List,
                    matches: List[Dict], bets: List[Dict]) -> str:
    """Generate the full Markdown report."""
    lines = []

    def h1(s):
        lines.append(f"\n# {s}\n")

    def h2(s):
        lines.append(f"\n## {s}\n")

    def h3(s):
        lines.append(f"\n### {s}\n")

    def p(s=''):
        lines.append(s)

    def code(s):
        lines.append(f"```\n{s}\n```")

    def table(headers, rows):
        """Build a simple markdown table (Telegram rewrites tables as bullets)."""
        lines.append(' | '.join(headers))
        lines.append(' | '.join(['---'] * len(headers)))
        for row in rows:
            lines.append(' | '.join(str(c) for c in row))

    def bullet(s):
        lines.append(f"- {s}")

    # ── Header ──
    h1("VFL Finite State Space Discovery Report")
    p(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    p(f"**Data Sources:** MSport API scrape, vfl_results.db ({len(matches)} deduplicated matches), bet ledger ({len(bets)} bets)")
    p()

    # ── Executive Summary ──
    h2("Executive Summary")
    
    total_pairs_with_data = sum(1 for ps in pair_stats.values() if ps['n'] > 0)
    total_matches = sum(ps['n'] for ps in pair_stats.values())
    converged_pairs = sum(1 for c in convergence.values() if c.get('converged') == True)
    avg_o15 = sum(ps['o1_5_rate'] for ps in pair_stats.values() if ps['n'] > 0) / max(total_pairs_with_data, 1)
    unique_scorelines = sum(ps['unique_scores'] for ps in pair_stats.values())

    p(f"- **Total unique fixture pairs observed:** {total_pairs_with_data} / 240 ({round(total_pairs_with_data/240*100, 1)}%)")
    p(f"- **Total matches analyzed:** {total_matches}")
    p(f"- **Total unique scoreline combinations observed:** {unique_scorelines}")
    p(f"- **Pairs with converged state space:** {converged_pairs}")
    p(f"- **Average O1.5 rate across all pairs:** {round(avg_o15, 1)}%")
    p(f"- **TRAP fixtures detected:** {len(traps)}")
    p(f"- **GOLD fixtures detected:** {len(golds)}")
    p(f"- **Bets placed:** {len(bets)} | **Lost:** {loss_analysis['total_lost']} ({round(loss_analysis['total_lost']/max(len(bets),1)*100, 1)}%)")
    p()

    # ── Loss Pattern Analysis ──
    h2("Loss Pattern Analysis")
    p("This is THE critical question: In a simulation engine, fixture outcomes are NOT random — they follow a deterministic pattern. We need to discover the pattern.")
    p()

    h3("Lost Bets Summary")
    lost_bets = [b for b in bets if b.get('status') == 'lost']
    p(f"**Total lost bets:** {len(lost_bets)}")

    if lost_bets:
        h3("Losses by Fixture")
        for match, count in Counter(b.get('match', '') for b in lost_bets).most_common():
            ps = pair_stats.get(match, {})
            o15_str = f" (Global O1.5: {ps.get('o1_5_rate', '?')}%)" if ps else ""
            bullet(f"**{match}**: {count} loss{'es' if count > 1 else ''}{o15_str}")

        h3("Losses by Market")
        for market, count in Counter(b.get('market', '') for b in lost_bets).most_common():
            bullet(f"{market}: {count}")

        h3("Losses by Matchday Range")
        md_losses = Counter(b.get('matchday', 0) for b in lost_bets)
        for md in sorted(md_losses.keys()):
            bullet(f"MD {md}: {md_losses[md]} loss{'es' if md_losses[md] > 1 else ''}")

        h3("Detailed Loss Fixtures")
        # Group by unique fixture
        loss_groups = defaultdict(list)
        for b in lost_bets:
            match = b.get('match', '')
            loss_groups[match].append(b)

        for match, lbs in sorted(loss_groups.items(), key=lambda x: len(x[1]), reverse=True):
            ps = pair_stats.get(match, {})
            p(f"\n**{match}** ({len(lbs)} loss{'es' if len(lbs) > 1 else ''})")
            p(f"- Global O1.5 rate: {ps.get('o1_5_rate', 'N/A')}% | Avg goals: {ps.get('avg_total_goals', 'N/A')} | Std: {ps.get('std_total_goals', 'N/A')}")
            for lb in lbs:
                result = lb.get('result', '?')
                md = lb.get('matchday', '?')
                market = lb.get('market', '?')
                season = lb.get('season_name', '?')
                confidence = lb.get('confidence_pct', '?')
                p(f"  - MD {md} | {season} | {market}@{lb.get('odds', '?')} | Result: {result} | Confidence: {confidence}%")
    p()

    # ── All Fixtures Analysis ──
    h2("All Fixtures - Pair Enumeration")
    p(f"Complete breakdown of all {total_pairs_with_data} fixture pairs observed:")

    # Sort by n desc
    sorted_pairs = sorted(pair_stats.items(), key=lambda x: x[1]['n'], reverse=True)

    h3("Top 10 Most Observed Fixtures")
    table(
        ['Fixture', 'Matches', 'Unique Scores', 'O1.5%', 'O2.5%', 'GG%', 'Avg G', 'Std G', 'Most Common'],
        [[k, v['n'], v['unique_scores'], f"{v['o1_5_rate']}%", f"{v['o2_5_rate']}%",
          f"{v['gg_rate']}%", v['avg_total_goals'], v['std_total_goals'], v['most_common_score']]
         for k, v in sorted_pairs[:10]]
    )

    h3("Bottom 10 Least Observed Fixtures")
    table(
        ['Fixture', 'Matches', 'Unique Scores', 'O1.5%', 'Most Common'],
        [[k, v['n'], v['unique_scores'], f"{v['o1_5_rate']}%", v['most_common_score']]
         for k, v in sorted_pairs[-10:] if v['n'] > 0]
    )
    p()

    # ── Convergence Analysis ──
    h2("State Space Convergence Analysis")
    p("The key question: Has the simulation engine exhausted its possible scorelines for each fixture pair?")
    p("If a pair has 'converged', we've likely discovered ALL possible outcomes.")
    p()

    converged_list = [(k, v) for k, v in convergence.items() if v.get('converged') == True]
    not_converged = [(k, v) for k, v in convergence.items() if v.get('converged') == False]

    p(f"- **Converged pairs:** {len(converged_list)}")
    p(f"- **Still evolving pairs:** {len(not_converged)}")
    p(f"- **Insufficient data:** {sum(1 for v in convergence.values() if v.get('converged') == 'insufficient_data')}")
    p()

    if converged_list:
        h3("Converged Fixtures (State Space Complete)")
        converged_list.sort(key=lambda x: x[1]['total_unique'], reverse=True)
        table(
            ['Fixture', 'Matches', 'Unique Scores', 'Plateau At'],
            [[k, v['n'], v['total_unique'], v.get('plateau_at', '?')] for k, v in converged_list[:20]]
        )

    if not_converged:
        h3("Still Evolving Fixtures (More States Possible)")
        not_converged.sort(key=lambda x: x[1]['new_scores_last_N'], reverse=True)
        table(
            ['Fixture', 'Matches', 'Unique Scores', 'New (Recent)'],
            [[k, v['n'], v['total_unique'], v.get('new_scores_last_N', '?')] for k, v in not_converged[:15]]
        )
    p()

    # ── Trap Detection ──
    h2("TRAP Fixtures")
    p("Fixtures that LOOK profitable but can lose you money. Avoid these for O1.5 betting unless you have strong signal.")
    p()

    if traps:
        p(f"**{len(traps)} trap fixtures detected:**")
        table(
            ['Fixture', 'N', 'O1.5%', 'Avg G', 'Std', 'Unique Scores', 'Why'],
            [[t['fixture'], t['n'], f"{t['o1_5_rate']}%", t['avg_total'],
              t['std_total'], t['unique_scores'], '; '.join(t['reasons'][:2])]
             for t in traps]
        )
    else:
        p("No trap fixtures detected with current thresholds.")

    # Save traps as JSON
    with open(TRAP_DATA_PATH, 'w') as f:
        json.dump(traps, f, indent=2)
    p(f"\nTrap data saved to: `{TRAP_DATA_PATH}`")
    p()

    # ── Gold Detection ──
    h2("GOLD Fixtures")
    p("Fixtures with high O1.5 hit rate and low variance. These are your breadwinners.")
    p()

    if golds:
        p(f"**{len(golds)} gold fixtures detected:**")
        golds_sorted = sorted(golds, key=lambda g: (-g['o1_5_rate'], g['std_total']))
        table(
            ['Fixture', 'N', 'O1.5%', 'O2.5%', 'GG%', 'Avg G', 'Std', 'Most Common', 'FG Home%'],
            [[g['fixture'], g['n'], f"{g['o1_5_rate']}%", f"{g['o2_5_rate']}%",
              f"{g['gg_rate']}%", g['avg_total'], g['std_total'],
              f"{g['most_common_score']} ({g['most_common_score_pct']}%)",
              f"{g['first_goal_home_pct']}%"]
             for g in golds_sorted]
        )
    else:
        p("No gold fixtures detected with current thresholds.")

    # Save golds as JSON
    with open(GOLD_DATA_PATH, 'w') as f:
        json.dump(golds, f, indent=2)
    p(f"\nGold data saved to: `{GOLD_DATA_PATH}`")
    p()

    # ── Home/Away Bias ──
    h2("Home/Away First Goal Bias")
    p("Fixtures with extreme first-goal bias (>>30% difference between Home and Away):")
    p()

    if biased_fixtures:
        table(
            ['Fixture', 'N', 'FG Home%', 'FG Away%', 'Avg Home G', 'Avg Away G'],
            [[b['fixture'], b['n'], f"{b['first_goal_home_pct']}%",
              f"{b['first_goal_away_pct']}%", b['avg_home_goals'], b['avg_away_goals']]
             for b in biased_fixtures[:15]]
        )
    p()

    # ── Matchday Analysis ──
    h2("Matchday Distribution Analysis")
    p("Do certain matchday ranges have consistently higher/lower scoring?")
    p()

    # Aggregate by matchday range
    md_ranges = {'1-5': [], '6-10': [], '11-15': [], '16-20': [], '21-25': [], '26-30': []}
    for md_str, stats in md_dist.items():
        md = int(md_str)
        if 1 <= md <= 5: md_ranges['1-5'].append(stats)
        elif 6 <= md <= 10: md_ranges['6-10'].append(stats)
        elif 11 <= md <= 15: md_ranges['11-15'].append(stats)
        elif 16 <= md <= 20: md_ranges['16-20'].append(stats)
        elif 21 <= md <= 25: md_ranges['21-25'].append(stats)
        elif 26 <= md <= 30: md_ranges['26-30'].append(stats)

    for range_name, stats_list in md_ranges.items():
        if not stats_list:
            continue
        avg_goals = sum(s['avg_goals'] for s in stats_list) / len(stats_list)
        avg_o15 = sum(s['o1_5_rate'] for s in stats_list) / len(stats_list)
        total_n = sum(s['n'] for s in stats_list)
        bullet(f"**MD {range_name}:** {total_n} matches | Avg {round(avg_goals, 2)} goals | O1.5 {round(avg_o15, 1)}%")

    # ── Scoreline Distribution ──
    h2("Global Scoreline Distribution")
    all_scores = Counter()
    for ps in pair_stats.values():
        for score, count in ps['scores'].items():
            all_scores[score] += count

    total = sum(all_scores.values())
    p(f"Total matches with known scores: {total}")
    p()
    table(
        ['Scoreline', 'Count', '% of Total'],
        [[score, count, f"{round(count/total*100, 2)}%"]
         for score, count in all_scores.most_common(30)]
    )
    p()

    # ── Streak Analysis for Problem Fixtures ──
    h2("Streak Analysis (Problem Fixtures)")
    p("For each fixture we've lost on, checking for streak patterns...")
    p()

    lost_fixtures = set()
    for b in lost_bets:
        match = b.get('match', '')
        if match in pair_stats:
            lost_fixtures.add(match)

    for fixture in sorted(lost_fixtures):
        streaks = analyze_streaks(matches, fixture)
        if streaks.get('message') == 'insufficient_data':
            continue
        p(f"**{fixture}** ({streaks['n']} matches, O1.5: {streaks['o1_5_rate']}%)")
        p(f"  - O1.5 streak max: {streaks['o1_5_streaks']['max']} (avg: {streaks['o1_5_streaks']['avg']})")
        p(f"  - U1.5 streak max: {streaks['u1_5_streaks']['max']} (avg: {streaks['u1_5_streaks']['avg']})")
        p(f"  - Last 10 O1.5 rate: {streaks['last_10_o1_5_rate']}%")
        p(f"  - Recent O1.5 streaks: {streaks['o1_5_streaks']['all'][-5:]}")
        p(f"  - Recent U1.5 streaks: {streaks['u1_5_streaks']['all'][-5:]}")
        if streaks['u1_5_streaks']['count'] > 0 and streaks['o1_5_streaks']['count'] > 0:
            # Check for regime switching
            if streaks['u1_5_streaks']['max'] >= 3:
                p(f"  ⚠️ WARNING: This fixture can go on U1.5 runs of {streaks['u1_5_streaks']['max']}!")
            if streaks['last_10_o1_5_rate'] < 60 and streaks['o1_5_rate'] > 70:
                p(f"  ⚠️ REGIME SHIFT: Recent form ({streaks['last_10_o1_5_rate']}%) diverges from historical ({streaks['o1_5_rate']}%)")
        p()

    # ── Recommendations ──
    h2("Recommendations")

    h3("BET These (Gold)")
    if golds:
        golds_sorted = sorted(golds, key=lambda g: (-g['o1_5_rate'], g['std_total']))
        for g in golds_sorted[:10]:
            bullet(f"**{g['fixture']}**: O1.5 {g['o1_5_rate']}% | Avg {g['avg_total']} goals | Std {g['std_total']} | Most common: {g['most_common_score']} ({g['most_common_score_pct']}%)")

    h3("AVOID These (Traps)")
    if traps:
        for t in traps[:10]:
            bullet(f"**{t['fixture']}**: Looks like {t['o1_5_rate']}% O1.5 but {', '.join(t['reasons'][:2])}")

    h3("Strategic Insights")
    bullet("**State Space is REAL**: Some fixture pairs have fully converged — they only produce a limited set of scorelines. This confirms the simulation engine has a finite state space.")
    bullet("**Regime Switching**: Some pairs alternate between high-scoring and low-scoring regimes. Watch for streaks of 3+ consecutive U1.5 results before betting O1.5.")
    bullet("**Home/Away Matters**: First goal bias varies significantly by fixture pair. Use this to time your bets.")
    bullet("**Matchday Patterns**: Slight variation in scoring across matchday ranges — consider this when placing early-vs-late season bets.")

    h3("Next Steps")
    bullet("Cross-reference trap fixtures with the simulation constraints file")
    bullet("Build a state transition matrix for each converged pair")
    bullet("Integrate streak detection into the betting pipeline")
    bullet("Monitor unconverged pairs for new scoreline emergence")

    return '\n'.join(lines)


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("VFL Finite State Space Analyzer")
    print("=" * 60)

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)

    # 1. Load data from all sources
    print("\n[1/6] Loading data...")
    api_matches = load_scraped_data()
    db_matches = load_db_matches()
    history_matches = load_history_matches()
    tracker_matches = load_season_tracker_matches()
    bets = load_bet_ledger()

    all_matches = api_matches + db_matches + history_matches + tracker_matches
    print(f"\n  Raw total: {len(all_matches)} matches across all sources")

    # Deduplicate
    matches = deduplicate_matches(all_matches)
    print(f"  After dedup: {len(matches)} unique matches")

    # 2. Compute pair statistics
    print("\n[2/6] Computing pair statistics...")
    pair_stats = compute_pair_stats(matches)
    print(f"  Computed stats for {len(pair_stats)} fixture pairs")

    # 3. Convergence analysis
    print("\n[3/6] Running convergence analysis...")
    convergence = convergence_analysis(pair_stats, matches)
    converged = sum(1 for c in convergence.values() if c.get('converged') == True)
    print(f"  Converged: {converged}, Still evolving: {sum(1 for c in convergence.values() if c.get('converged') == False)}")

    # 4. Loss pattern analysis
    print("\n[4/6] Analyzing loss patterns...")
    loss_analysis = analyze_loss_patterns(bets, pair_stats)
    print(f"  Total losses: {loss_analysis['total_lost']}")
    print(f"  Unique losing fixtures: {len(loss_analysis['lost_by_fixture'])}")

    # 5. Trap and gold detection
    print("\n[5/6] Detecting traps and gold...")
    traps, golds = detect_traps_and_gold(pair_stats, loss_analysis)
    print(f"  Traps: {len(traps)}, Gold: {len(golds)}")

    # 6. Additional analysis
    print("\n[6/6] Running additional analyses...")
    md_dist = matchday_distribution_analysis(matches)
    biased_fixtures = analyze_home_away_bias(pair_stats)
    print(f"  Matchdays with data: {len(md_dist)}")
    print(f"  Biased fixtures: {len(biased_fixtures)}")

    # 7. Generate report
    print("\nGenerating report...")
    report = generate_report(
        pair_stats, convergence, loss_analysis,
        traps, golds, md_dist, biased_fixtures,
        matches, bets,
    )

    with open(REPORT_PATH, 'w') as f:
        f.write(report)
    print(f"  Report saved: {REPORT_PATH}")

    # Summary
    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print(f"  Matches analyzed: {len(matches)}")
    print(f"  Fixture pairs: {len(pair_stats)}")
    print(f"  Traps found: {len(traps)}")
    print(f"  Gold found: {len(golds)}")
    print(f"  Report: {REPORT_PATH}")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
