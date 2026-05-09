#!/usr/bin/env python3
"""
VFL Constraints Module — Clara's permutation analysis as a constraint layer.
Loads historical analysis data and provides constraint checking for predictions.
"""
import json
import os
import sqlite3
from collections import defaultdict

# ─── PATHS ───
ANALYSIS_PATH = os.path.expanduser(
    "~/Documents/Projects/vfl-data/analysis/clara_permutation_analysis.json"
)
DB_PATH = os.path.expanduser(
    "~/Documents/Projects/vfl-data/databases/history.db"
)


class VFLConstraints:
    """Constraint layer using Clara's historical permutation analysis."""

    def __init__(self, analysis_path=ANALYSIS_PATH, db_path=DB_PATH):
        self.analysis_path = analysis_path
        self.db_path = db_path

        # Load analysis data
        with open(analysis_path) as f:
            self.analysis = json.load(f)

        # Build per-MD → fixture lookup: {md: {(home, away): fixture_data}}
        self._fixture_map = self._build_fixture_map()

        # Cache for observed patterns per MD
        self._observed_patterns_cache = {}

        # Cache for raw MD match data from DB (all seasons)
        self._md_match_cache = {}

    def _build_fixture_map(self):
        """Build a nested dict for fast fixture lookup by MD."""
        fm = {}
        fixture_analysis = self.analysis.get("fixture_analysis", {})
        for md_str, fixtures in fixture_analysis.items():
            md = int(md_str)
            md_map = {}
            for entry in fixtures:
                key = (entry["home"].upper(), entry["away"].upper())
                md_map[key] = entry
            fm[md] = md_map
        return fm

    # ─── FIXTURE-LEVEL CONSTRAINTS ───

    def get_fixture_data(self, home_team, away_team, match_day):
        """Return historical outcome distribution for a fixture on a given MD.
        
        Returns dict with: home_wins, away_wins, draws, total_occurrences,
                           home_pct, away_pct, draw_pct, flags
        or None if no historical data.
        """
        key = (home_team.upper(), away_team.upper())
        md_map = self._fixture_map.get(match_day, {})
        return md_map.get(key)

    def is_always_home(self, home_team, away_team, match_day):
        """Check if a fixture has ALWAYS resulted in a HOME win historically."""
        data = self.get_fixture_data(home_team, away_team, match_day)
        if data is None:
            return False
        return "ALWAYS_HOME" in data.get("flags", [])

    def is_always_away(self, home_team, away_team, match_day):
        """Check if a fixture has ALWAYS resulted in an AWAY win historically."""
        data = self.get_fixture_data(home_team, away_team, match_day)
        if data is None:
            return False
        return "ALWAYS_AWAY" in data.get("flags", [])

    def never_drawn(self, home_team, away_team, match_day):
        """Check if a fixture has NEVER ended in a DRAW historically."""
        data = self.get_fixture_data(home_team, away_team, match_day)
        if data is None:
            return False
        return "NEVER_DRAW" in data.get("flags", [])

    # ─── PATTERN-LEVEL CONSTRAINTS ───

    def _load_matches_for_md(self, match_day):
        """Load all historical matches for a given MD from the database."""
        if match_day in self._md_match_cache:
            return self._md_match_cache[match_day]

        if not os.path.exists(self.db_path):
            return []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT season, home, away, outcome
            FROM matches
            WHERE day = ? AND outcome IS NOT NULL
            ORDER BY season, id
            """,
            (match_day,),
        )
        rows = cursor.fetchall()
        conn.close()

        # Group by season
        seasons = defaultdict(list)
        for season, home, away, outcome in rows:
            # Normalize outcome
            outcome_norm = outcome.upper()
            if outcome_norm in ("H", "HOME"):
                outcome_norm = "HOME"
            elif outcome_norm in ("A", "AWAY"):
                outcome_norm = "AWAY"
            elif outcome_norm in ("D", "DRAW"):
                outcome_norm = "DRAW"
            else:
                continue
            seasons[season].append({
                "home": home.upper(),
                "away": away.upper(),
                "outcome": outcome_norm,
            })

        self._md_match_cache[match_day] = dict(seasons)
        return self._md_match_cache[match_day]

    def _build_observed_patterns(self, match_day, current_fixtures):
        """Build a set of observed patterns for an MD, aligned to the current
        fixture ordering.
        
        current_fixtures: list of (home_team, away_team) tuples in the order
                          they appear in the current season's event list.
        """
        cache_key = (match_day, tuple(current_fixtures))
        if cache_key in self._observed_patterns_cache:
            return self._observed_patterns_cache[cache_key]

        seasons_data = self._load_matches_for_md(match_day)
        if not seasons_data:
            self._observed_patterns_cache[cache_key] = set()
            return set()

        # Normalize current fixture names
        norm_fixtures = [(h.upper(), a.upper()) for h, a in current_fixtures]

        patterns = set()

        for season, matches in seasons_data.items():
            if len(matches) < 8:
                continue

            # Build a lookup for this season's matches
            match_lookup = {}
            for m in matches:
                match_lookup[(m["home"], m["away"])] = m["outcome"]

            # Build pattern in current fixture order
            pattern_parts = []
            valid = True
            for fixture_key in norm_fixtures:
                outcome = match_lookup.get(fixture_key)
                if outcome is None:
                    # Try reversed fixture (home/away swap)
                    rev_key = (fixture_key[1], fixture_key[0])
                    outcome = match_lookup.get(rev_key)
                    # If found, invert the outcome
                    if outcome == "HOME":
                        outcome = "AWAY"
                    elif outcome == "AWAY":
                        outcome = "HOME"
                    # DRAW stays DRAW
                if outcome is None:
                    valid = False
                    break
                pattern_parts.append(outcome)

            if valid and len(pattern_parts) == 8:
                patterns.add(",".join(pattern_parts))

        self._observed_patterns_cache[cache_key] = patterns
        return patterns

    def is_pattern_feasible(self, predictions, match_day, current_fixtures):
        """Check if a predicted pattern (list of 8 outcomes) has ever been
        observed historically for this MD.
        
        predictions: list of 8 outcome strings ("HOME", "AWAY", "DRAW")
        current_fixtures: list of (home_team, away_team) tuples in current order
        """
        pattern = ",".join(predictions)
        observed = self._build_observed_patterns(match_day, current_fixtures)
        return pattern in observed

    def adjust_to_feasible_pattern(self, predictions, confidences, match_day,
                                    current_fixtures):
        """If the predicted pattern has never been observed, adjust the
        lowest-confidence prediction to match a feasible pattern.
        
        Returns a list of 8 adjusted outcome strings.
        """
        pattern = list(predictions)
        observed = self._build_observed_patterns(match_day, current_fixtures)

        # If already feasible, return as-is
        if ",".join(pattern) in observed:
            return pattern

        if not observed:
            # No historical data at all — return original
            return pattern

        # Try flipping the lowest-confidence predictions one at a time
        # until we find a feasible pattern
        idx_sorted = sorted(
            range(len(predictions)),
            key=lambda i: confidences[i],
        )

        for idx in idx_sorted:
            original = pattern[idx]
            alternatives = ["HOME", "AWAY", "DRAW"]
            alternatives.remove(original)

            for alt in alternatives:
                test_pattern = list(pattern)
                test_pattern[idx] = alt
                if ",".join(test_pattern) in observed:
                    return test_pattern

        # Try flipping two lowest-confidence predictions
        for i in range(len(idx_sorted)):
            for j in range(i + 1, len(idx_sorted)):
                i_idx = idx_sorted[i]
                j_idx = idx_sorted[j]
                original_i = pattern[i_idx]
                original_j = pattern[j_idx]

                for alt_i in ["HOME", "AWAY", "DRAW"]:
                    if alt_i == original_i:
                        continue
                    for alt_j in ["HOME", "AWAY", "DRAW"]:
                        if alt_j == original_j:
                            continue
                        test_pattern = list(pattern)
                        test_pattern[i_idx] = alt_i
                        test_pattern[j_idx] = alt_j
                        if ",".join(test_pattern) in observed:
                            return test_pattern

        # If still not found, just return the original
        return pattern

    # ─── SUMMARY STATS ───

    def get_summary_stats(self):
        """Return summary stats from the analysis."""
        meta = self.analysis.get("metadata", {})
        extreme = self.analysis.get("extreme_fixture_summary", {})
        ps = self.analysis.get("permutation_space", {})
        avg_patterns = sum(
            v["distinct_patterns_seen"] for v in ps.values()
        ) / len(ps) if ps else 0

        return {
            "total_seasons": meta.get("total_seasons_analyzed", 0),
            "total_matches": meta.get("global_averages", {}).get("total_matches", 0),
            "always_home": extreme.get("always_home", 0),
            "always_away": extreme.get("always_away", 0),
            "never_draw": extreme.get("never_draw", 0),
            "avg_distinct_patterns_per_md": avg_patterns,
            "total_possible_patterns": 6561,
        }


# ─── STANDALONE USAGE ───
if __name__ == "__main__":
    c = VFLConstraints()
    stats = c.get_summary_stats()
    print("VFL Constraints Module — Loaded")
    print(f"Seasons analyzed: {stats['total_seasons']}")
    print(f"Always HOME: {stats['always_home']}")
    print(f"Always AWAY: {stats['always_away']}")
    print(f"Never DRAW: {stats['never_draw']}")
    print(f"Avg patterns per MD: {stats['avg_distinct_patterns_per_md']:.0f} / 6561")
    print()

    # Test with some known extreme fixtures
    test_cases = [
        ("LONDON GUNS", "TOTTENHAM", 1),   # ALWAYS_HOME
        ("MANCHESTER BLUE", "CHELSEA", 1), # ALWAYS_AWAY
        ("WEST HAM", "BOURNEMOUTH", 1),    # ALWAYS_HOME + STRONG_HOME
    ]
    for home, away, md in test_cases:
        ah = c.is_always_home(home, away, md)
        aa = c.is_always_away(home, away, md)
        nd = c.never_drawn(home, away, md)
        data = c.get_fixture_data(home, away, md)
        print(f"{home:20} vs {away:20} (MD {md}): always_home={ah}, always_away={aa}, never_draw={nd}, data={data is not None}")
    print()
    print("VFL Constraints Module — Ready")
