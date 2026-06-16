#!/usr/bin/env python3
"""
finite_state_filter.py — Finite State Space Trap Filter
========================================================
Prevents betting on fixture pairs where historical data shows the
outcome is mathematically unlikely (a "trap").

Uses the proven finite state space discovery: only 34 unique scorelines
across 240 fixture pairs, each with 100+ matches of convergence data.

Usage:
    from finite_state_filter import FiniteStateFilter
    fsf = FiniteStateFilter()
    result = fsf.check_pair("Leeds", "Fulham", "O1.5")
    # → {'verdict': 'FAIL', 'rate': 0.462, ...}

Author: VFL Engineering Team
"""

import json
import os

FINITE_STATE_PATH = '/home/ubuntu/faith-workspace/vfl-complete-data/analysis/finite_state_space.json'
RESULTS_DB = '/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db'

DEFAULT_THRESHOLDS = {
    'O1.5': 0.65,
    'O2.5': 0.40,
    'GG': 0.45,
    'U3.5': 0.65,
}


class FiniteStateFilter:
    def __init__(self, data_path=None):
        self.data_path = data_path or FINITE_STATE_PATH
        self.data = None
        self.load()

    def load(self):
        if os.path.exists(self.data_path):
            with open(self.data_path) as f:
                self.data = json.load(f)
        else:
            self._compute_from_db()

    def _compute_from_db(self):
        """Fallback: compute from vfl_results.db"""
        import sqlite3
        conn = sqlite3.connect(RESULTS_DB)
        # Compute pair stats from results table
        self.data = self._pair_stats_from_conn(conn)

    def _pair_stats_from_conn(self, conn):
        """Read all completed results and aggregate into pair_stats format."""
        cursor = conn.execute("""
            SELECT home_team, away_team, home_goals, away_goals, total_goals
            FROM results
            WHERE status = 3
              AND home_goals IS NOT NULL
              AND away_goals IS NOT NULL
        """)
        pair_data = {}
        for row in cursor.fetchall():
            home, away, hg, ag, tg = row
            key = self._pair_key(home, away)
            if key not in pair_data:
                pair_data[key] = {
                    'home': home,
                    'away': away,
                    'matches': 0,
                    'total_goals_sum': 0,
                    'o15_count': 0,
                    'o25_count': 0,
                    'gg_count': 0,
                    'scorelines': {},
                }
            pd = pair_data[key]
            pd['matches'] += 1
            pd['total_goals_sum'] += tg
            if tg > 1.5:
                pd['o15_count'] += 1
            if tg > 2.5:
                pd['o25_count'] += 1
            if tg <= 3.5: # Corrected for U3.5
                pd['u35_count'] = pd.get('u35_count', 0) + 1
            if hg > 0 and ag > 0:
                pd['gg_count'] += 1
            scoreline = f"{hg}:{ag}"
            pd['scorelines'][scoreline] = pd['scorelines'].get(scoreline, 0) + 1
        conn.close()

        pair_stats = {}
        for key, pd in pair_data.items():
            n = pd['matches']
            most_common_score = max(pd['scorelines'], key=pd['scorelines'].get) if pd['scorelines'] else '0:0'
            pair_stats[key] = {
                'home': pd['home'],
                'away': pd['away'],
                'matches': n,
                'o15_rate': round(pd['o15_count'] / n * 100, 1) if n > 0 else 0,
                'o25_rate': round(pd['o25_count'] / n * 100, 1) if n > 0 else 0,
                'u35_rate': round(pd.get('u35_count', 0) / n * 100, 1) if n > 0 else 0,
                'gg_rate': round(pd['gg_count'] / n * 100, 1) if n > 0 else 0,
                'unique_scorelines': len(pd['scorelines']),
                'most_common_score': most_common_score,
                'scorelines': pd['scorelines'],
            }

        return {
            'analyzed_at': None,
            'total_matches': sum(p['matches'] for p in pair_stats.values()),
            'total_pairs': len(pair_stats),
            'total_unique_scorelines': len(set(
                s for p in pair_stats.values()
                for s in p['scorelines']
            )),
            'pair_stats': pair_stats,
        }

    def _pair_key(self, home, away):
        return f"{home} vs {away}"

    def _get_recent_sequence(self, home, away, market='O1.5', count=2):
        """Get the last `count` matches outcomes for this specific fixture pair."""
        import sqlite3
        if not os.path.exists(RESULTS_DB):
            return []
        try:
            conn = sqlite3.connect(RESULTS_DB)
            cursor = conn.execute("""
                SELECT home_goals, away_goals, total_goals
                FROM results
                WHERE status = 3
                  AND home_team = ? AND away_team = ?
                  AND home_goals IS NOT NULL
                  AND away_goals IS NOT NULL
                ORDER BY season_name DESC, match_day DESC
                LIMIT ?
            """, (home, away, count))
            rows = cursor.fetchall()
            conn.close()
            
            # Since they are ordered DESC, reverse them to get chronological order
            rows.reverse()
            
            check_fns = {
                'O1.5': lambda hg, ag, tg: 1 if tg >= 2 else 0,
                'O2.5': lambda hg, ag, tg: 1 if tg >= 3 else 0,
                'GG': lambda hg, ag, tg: 1 if hg >= 1 and ag >= 1 else 0,
                'U3.5': lambda hg, ag, tg: 1 if tg <= 3 else 0
            }
            check_fn = check_fns.get(market, lambda hg, ag, tg: 1 if tg >= 2 else 0)
            
            return [check_fn(r[0], r[1], r[2]) for r in rows]
        except Exception as e:
            return []

    def check_pair(self, home, away, market='O1.5'):
        """Check if a pair is a known trap for the given market.

        Returns dict with:
            verdict: 'PASS' or 'FAIL'
            rate: historical rate for this market
            threshold: minimum rate required
            reason: human-readable explanation
            most_common: most frequent scoreline (if FAIL)
            matches: number of historical matches
        """
        key = self._pair_key(home, away)
        stats = self.data.get('pair_stats', {}).get(key)
        if not stats:
            return {
                'verdict': 'PASS',
                'reason': 'No historical data for this pair',
                'rate': None,
                'threshold': DEFAULT_THRESHOLDS.get(market, 0.65),
                'matches': 0,
            }

        threshold = DEFAULT_THRESHOLDS.get(market, 0.65)
        if market == 'O1.5':
            rate_key = 'o15_rate'
        elif market == 'O2.5':
            rate_key = 'o25_rate'
        elif market == 'GG':
            rate_key = 'gg_rate'
        elif market == 'U3.5':
            rate_key = 'u35_rate'
        else:
            rate_key = 'o15_rate'

        rate = stats.get(rate_key, 0) / 100.0
        n_matches = stats.get('matches', 0)

        # 1. Baseline Finite State Space Trap Check
        if rate < threshold:
            return {
                'verdict': 'FAIL',
                'rate': rate,
                'threshold': threshold,
                'reason': f'{market} trap: only {rate*100:.1f}% for {home} vs {away} (need {threshold*100:.0f}%)',
                'most_common': stats.get('most_common_score', '?'),
                'matches': n_matches,
            }

        # 2. Dynamic Fellynius Sequence Transition Check
        felly = stats.get('fellynius', {}).get(market, {})
        if felly:
            seq = self._get_recent_sequence(home, away, market, 2)
            if len(seq) == 2:
                seq_key = f"{seq[0]},{seq[1]}"
                t2_stats = felly.get('t2', {}).get(seq_key)
                if t2_stats:
                    prob_1 = t2_stats.get('1', 0.0)
                    # If the transition probability to the target state is too low, fail it as a sequence trap.
                    felly_threshold = 0.50 if market in ['O2.5', 'GG'] else 0.60
                    if prob_1 < felly_threshold:
                        return {
                            'verdict': 'FAIL',
                            'rate': rate,
                            'threshold': threshold,
                            'reason': f'Fellynius {market} sequence trap: sequence {seq_key} has only {prob_1*100:.1f}% transition to {market} (need {felly_threshold*100:.0f}%)',
                            'most_common': stats.get('most_common_score', '?'),
                            'matches': n_matches,
                        }

        return {
            'verdict': 'PASS',
            'rate': rate,
            'threshold': threshold,
            'reason': f'{market} rate {rate*100:.1f}% meets {threshold*100:.0f}% threshold ({n_matches} matches)',
            'matches': n_matches,
        }

    def get_golden_pairs(self, min_o15=80.0):
        """Get all pairs with O1.5 rate >= min_o15, sorted descending."""
        result = []
        for key, s in self.data.get('pair_stats', {}).items():
            if s.get('o15_rate', 0) >= min_o15:
                result.append((key, s))
        return sorted(result, key=lambda x: x[1]['o15_rate'], reverse=True)

    def get_trap_pairs(self, max_o15=60.0):
        """Get all pairs with O1.5 rate <= max_o15, sorted ascending."""
        result = []
        for key, s in self.data.get('pair_stats', {}).items():
            if s.get('o15_rate', 100) <= max_o15:
                result.append((key, s))
        return sorted(result, key=lambda x: x[1]['o15_rate'])

    def get_pair_stats(self, home, away):
        """Get raw stats dict for a specific pair."""
        key = self._pair_key(home, away)
        return self.data.get('pair_stats', {}).get(key)


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def main():
    """CLI entry point for testing the filter."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Finite State Space Trap Filter for VFL Betting'
    )
    parser.add_argument('--check', nargs=3, metavar=('HOME', 'AWAY', 'MARKET'),
                        help='Check a specific pair: HOME AWAY MARKET')
    parser.add_argument('--golden', type=float, nargs='?', const=80.0, default=None,
                        help='List golden pairs (O1.5 >= threshold, default 80%)')
    parser.add_argument('--traps', type=float, nargs='?', const=60.0, default=None,
                        help='List trap pairs (O1.5 <= threshold, default 60%)')
    parser.add_argument('--stats', nargs=2, metavar=('HOME', 'AWAY'),
                        help='Show detailed stats for a pair')
    parser.add_argument('--json', action='store_true',
                        help='Output raw JSON')

    args = parser.parse_args()
    fsf = FiniteStateFilter()

    if args.check:
        home, away, market = args.check
        result = fsf.check_pair(home, away, market)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            icon = '✅ PASS' if result['verdict'] == 'PASS' else '🚫 FAIL'
            print(f"{icon}: {result['reason']}")
            if result.get('most_common'):
                print(f"   Most common: {result['most_common']}")
            if result.get('matches'):
                print(f"   Matches: {result['matches']}")

    elif args.golden is not None:
        pairs = fsf.get_golden_pairs(args.golden)
        if args.json:
            print(json.dumps(pairs, indent=2))
        else:
            print(f"\n🏆 **Golden Pairs** (O1.5 >= {args.golden:.0f}%): {len(pairs)} found\n")
            for key, s in pairs:
                print(f"  {key}: O1.5={s['o15_rate']}%, O2.5={s['o25_rate']}%, GG={s['gg_rate']}% ({s['matches']} matches)")

    elif args.traps is not None:
        pairs = fsf.get_trap_pairs(args.traps)
        if args.json:
            print(json.dumps(pairs, indent=2))
        else:
            print(f"\n🚫 **Trap Pairs** (O1.5 <= {args.traps:.0f}%): {len(pairs)} found\n")
            for key, s in pairs:
                print(f"  {key}: O1.5={s['o15_rate']}%, O2.5={s['o25_rate']}%, GG={s['gg_rate']}% ({s['matches']} matches, most common: {s.get('most_common_score','?')})")

    elif args.stats:
        home, away = args.stats
        stats = fsf.get_pair_stats(home, away)
        if args.json:
            print(json.dumps(stats, indent=2))
        elif stats:
            print(f"\n📊 **{home} vs {away}** ({stats['matches']} matches)\n")
            print(f"   O1.5: {stats['o15_rate']}%")
            print(f"   O2.5: {stats['o25_rate']}%")
            print(f"   GG:   {stats['gg_rate']}%")
            print(f"   Most common: {stats['most_common_score']}")
            print(f"   Unique scorelines: {stats['unique_scorelines']}")
        else:
            print(f"No data for {home} vs {away}")

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
