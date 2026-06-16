#!/usr/bin/env python3
"""
VFL Fixture Intelligence Engine — Test Suite
=============================================
Comprehensive tests verifying the FixtureIntelligenceEngine against
known fixtures with expected outcomes.

Usage:
    python test_fixture_intelligence.py                  # Run all tests
    python test_fixture_intelligence.py -v               # Verbose mode
    python test_fixture_intelligence.py --list           # List test cases
    python test_fixture_intelligence.py --quick          # Quick smoke test only

Exit code: 0 = all passed, 1 = any failure
"""

import sys
import os
import json
import traceback

# Ensure we can import from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixture_intelligence import FixtureIntelligenceEngine, TEAM_PROFILES, TEAMS


# ──────────────────────────────────────────────────────────────────────
# TEST CASES
# ──────────────────────────────────────────────────────────────────────

TEST_FIXTURES = [
    # (home, away, expect_goals_range, expect_market_type, description)
    # Low-scoring defensive matchups
    {
        "home": "Everton",
        "away": "Leeds",
        "goals_min": 1.2,
        "goals_max": 2.8,
        "expect_over_15": False,  # H2H-driven: 50.9% O1.5 → Under 3.5 candidate
        "expect_market_validation": True,
        "strength_min": 65,
        "description": "Classic low-scoring defensive duel - both most defensive teams",
    },
    {
        "home": "Fulham",
        "away": "Leeds",
        "goals_min": 1.2,
        "goals_max": 2.8,
        "expect_over_15": False,  # H2H-driven: 54.7% O1.5 → Under 2.5 candidate
        "expect_market_validation": True,
        "strength_min": 60,
        "description": "Defensive matchup - Fulham vs Leeds",
    },
    # High-scoring powerhouse matchups
    {
        "home": "Manchester Blue",
        "away": "Wolverhampton",
        "goals_min": 2.5,
        "goals_max": 4.5,
        "expect_over_15": True,
        "expect_market_validation": True,
        "strength_min": 85,
        "description": "Highest scoring matchup - Man Blue vs Wolves (3.49g H2H avg)",
    },
    {
        "home": "London Guns",
        "away": "Wolverhampton",
        "goals_min": 2.5,
        "goals_max": 4.0,
        "expect_over_15": True,
        "expect_market_validation": True,
        "strength_min": 80,
        "description": "High scoring - London Guns vs Wolves",
    },
    {
        "home": "Chelsea",
        "away": "Manchester Blue",
        "goals_min": 2.5,
        "goals_max": 4.5,
        "expect_over_15": True,
        "expect_market_validation": True,
        "strength_min": 85,
        "description": "Powerhouse battle - Chelsea vs Man Blue",
    },
    # Balanced matchups
    {
        "home": "Aston Villa",
        "away": "Newcastle",
        "goals_min": 1.8,
        "goals_max": 3.5,
        "expect_over_15": True,
        "expect_market_validation": True,
        "strength_min": 70,
        "description": "Balanced mid-table matchup",
    },
    {
        "home": "Brighton",
        "away": "Crystal Palace",
        "goals_min": 1.8,
        "goals_max": 3.5,
        "expect_over_15": True,
        "expect_market_validation": True,
        "strength_min": 65,
        "description": "Balanced matchup - Brighton vs Palace",
    },
    # Attacking teams
    {
        "home": "Liverpool",
        "away": "Tottenham",
        "goals_min": 2.0,
        "goals_max": 4.0,
        "expect_over_15": True,
        "expect_market_validation": True,
        "strength_min": 70,
        "description": "Attacking clash - Liverpool vs Tottenham",
    },
    {
        "home": "Manchester Red",
        "away": "West Ham",
        "goals_min": 2.0,
        "goals_max": 3.8,
        "expect_over_15": True,
        "expect_market_validation": True,
        "strength_min": 70,
        "description": "Attacking matchup - Man Red vs West Ham",
    },
    # Mixed tiers
    {
        "home": "Everton",
        "away": "Manchester Blue",
        "goals_min": 2.0,
        "goals_max": 3.5,
        "expect_over_15": True,
        "expect_market_validation": True,
        "strength_min": 70,
        "description": "Defensive vs Powerhouse - Everton vs Man Blue",
    },
]

# Edge cases
EDGE_CASES = [
    {
        "home": "Leeds",
        "away": "Leeds",
        "should_error": True,
        "description": "Same team - should error",
    },
]

# ──────────────────────────────────────────────────────────────────────
# TEST RUNNER
# ──────────────────────────────────────────────────────────────────────


class TestResult:
    """Result of a single test."""

    def __init__(self, name: str, passed: bool, details: str = ""):
        self.name = name
        self.passed = passed
        self.details = details


class TestSuite:
    """Runs tests and collects results."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: list[TestResult] = []
        self.engine = FixtureIntelligenceEngine()

    def run_all(self):
        """Run all test cases."""
        self._test_team_validation()
        self._test_team_profiles()
        self._test_l1_computation()
        self._test_l2_h2h()
        self._test_l3_form()
        self._test_full_analysis()
        self._test_edge_cases()
        self._test_batch_analysis()
        self._test_h2h_summary()

    def _record(self, name: str, passed: bool, details: str = ""):
        """Record a test result."""
        self.results.append(TestResult(name, passed, details))

    def _assert(
        self, condition: bool, name: str, msg: str = ""
    ) -> bool:
        """Assert a condition and record result."""
        passed = bool(condition)
        details = "" if passed else (msg or "Assertion failed")
        self._record(name, passed, details)
        if not passed:
            print(f"  ✗ FAIL: {name}")
            if details:
                print(f"    {details}")
        elif self.verbose:
            print(f"  ✓ PASS: {name}")
        return passed

    def _assert_approx(
        self, actual: float, expected: float, tolerance: float, name: str
    ):
        """Assert approximately equal floating point values."""
        diff = abs(actual - expected)
        passed = diff <= tolerance
        details = (
            f"Expected ~{expected} (±{tolerance}), got {actual} (diff={diff:.4f})"
            if not passed
            else ""
        )
        self._record(name, passed, details)
        if not passed:
            print(f"  ✗ FAIL: {name}")
            print(f"    {details}")
        elif self.verbose:
            print(f"  ✓ PASS: {name} (got {actual})")

    def _assert_in_range(
        self, actual: float, lo: float, hi: float, name: str
    ):
        """Assert value is in range [lo, hi]."""
        passed = lo <= actual <= hi
        details = (
            f"Expected {actual} to be in [{lo}, {hi}]"
            if not passed
            else ""
        )
        self._record(name, passed, details)
        if not passed:
            print(f"  ✗ FAIL: {name}")
            print(f"    {details}")
        elif self.verbose:
            print(f"  ✓ PASS: {name} (got {actual})")

    # ── Individual tests ─────────────────────────────────────────

    def _test_team_validation(self):
        """Test team validation and normalization."""
        self._assert(
            FixtureIntelligenceEngine.validate_team("Everton") == "Everton",
            "validate_team exact match",
        )
        self._assert(
            FixtureIntelligenceEngine.validate_team("  everton  ".title())
            == "Everton",
            "validate_team case normalization",
        )

        # All teams are valid
        for team in sorted(TEAMS):
            try:
                result = FixtureIntelligenceEngine.validate_team(team)
                self._assert(result == team, f"validate_team '{team}'", f"Got '{result}'")
            except ValueError as e:
                self._record(f"validate_team '{team}'", False, str(e))

        # Invalid team
        try:
            FixtureIntelligenceEngine.validate_team("FC Barcelona")
            self._record("validate_team invalid", False, "Should have raised ValueError")
        except ValueError:
            self._record("validate_team invalid", True)

    def _test_team_profiles(self):
        """Test that all teams have profiles."""
        for team in TEAMS:
            profile = TEAM_PROFILES.get(team)
            self._assert(
                profile is not None,
                f"team_profile exists: {team}",
            )
            if profile:
                self._assert(
                    1.0 <= profile["avg_goals"] <= 4.0,
                    f"{team} avg_goals reasonable",
                    f"Got {profile['avg_goals']}",
                )
                self._assert(
                    profile["tier"] in ("defensive", "balanced", "attacking", "powerhouse"),
                    f"{team} tier valid",
                    f"Got '{profile['tier']}'",
                )
                self._assert(
                    0 <= profile["o1_5_pct"] <= 100,
                    f"{team} o1_5_pct",
                )

    def _test_l1_computation(self):
        """Test Layer 1 (all-time profiles) computation."""
        l1 = self.engine._compute_l1("Everton", "Leeds")
        self._assert(
            l1["expected_goals"] > 0,
            "L1 Everton vs Leeds positive",
            f"Got {l1['expected_goals']}",
        )
        self._assert(
            l1["tier_adjustment"] < 0,
            "L1 defensive+defensive = negative adjustment",
            f"Got {l1['tier_adjustment']}",
        )
        self._assert(
            l1["home_profile"]["tier"] == "defensive",
            "L1 home profile tier",
        )
        self._assert(
            l1["away_profile"]["tier"] == "defensive",
            "L1 away profile tier",
        )

        # Powerhouse matchup should have positive adjustment
        l1_power = self.engine._compute_l1("Manchester Blue", "London Guns")
        self._assert(
            l1_power["tier_adjustment"] > 0,
            "L1 powerhouse+powerhouse = positive adjustment",
            f"Got {l1_power['tier_adjustment']}",
        )

        # Man Blue vs Wolves should be very high
        l1_high = self.engine._compute_l1("Manchester Blue", "Wolverhampton")
        self._assert(
            l1_high["expected_goals"] > 2.5,
            "L1 Man Blue vs Wolves > 2.5",
            f"Got {l1_high['expected_goals']}",
        )

    def _test_l2_h2h(self):
        """Test Layer 2 (H2H history)."""
        # Everton vs Leeds - well known low-scoring matchup
        l2 = self.engine._compute_l2("Everton", "Leeds")
        if l2["n_matches"] > 0:
            self._assert(
                l2["n_matches"] >= 100,
                "L2 Everton vs Leeds has many matches",
                f"Got {l2['n_matches']}",
            )
            self._assert(
                l2["expected_goals"] is not None,
                "L2 expected_goals not None",
            )
            if l2["expected_goals"]:
                self._assert(
                    1.0 <= l2["expected_goals"] <= 2.5,
                    "L2 Everton vs Leeds avg goals in range",
                    f"Got {l2['expected_goals']}",
                )
            self._assert(
                l2["o1_5_rate"] is not None,
                "L2 o1_5_rate not None",
            )
            self._assert(
                l2["zero_zero_rate"] is not None,
                "L2 zero_zero_rate not None",
            )

        # Man Blue vs Wolves - high scoring
        l2_high = self.engine._compute_l2("Manchester Blue", "Wolverhampton")
        if l2_high["n_matches"] > 0:
            self._assert(
                l2_high["expected_goals"] is not None
                and l2_high["expected_goals"] > 2.5,
                "L2 Man Blue vs Wolves high scoring",
                f"Got {l2_high.get('expected_goals')}",
            )

    def _test_l3_form(self):
        """Test Layer 3 (recent form)."""
        l3 = self.engine._compute_l3("Everton", "Leeds")
        self._assert(
            l3["expected_goals"] is not None,
            "L3 expected_goals not None",
        )
        self._assert(
            l3["n_home"] + l3["n_away"] > 0,
            "L3 has some matches",
        )
        if l3["expected_goals"]:
            self._assert(
                l3["expected_goals"] > 0,
                "L3 positive expected goals",
                f"Got {l3['expected_goals']}",
            )

        # Test with larger window
        l3_large = self.engine._compute_l3("Everton", "Leeds", window=10)
        self._assert(
            l3_large["n_home"] + l3_large["n_away"] > 0,
            "L3 with window=10 has matches",
        )

    def _test_full_analysis(self):
        """Test full analysis for all defined fixtures."""
        for tc in TEST_FIXTURES:
            name = f"analyze '{tc['home']}' vs '{tc['away']}'"
            try:
                result = self.engine.analyze_fixture(
                    tc["home"], tc["away"],
                    include_market_validation=True,
                )

                # Check error field
                if "error" in result:
                    self._record(name, False, f"Error: {result['error']}")
                    continue

                # Check expected goals range
                eg = result["expected_goals"]
                self._assert_in_range(
                    eg, tc["goals_min"], tc["goals_max"],
                    f"{name} expected_goals in [{tc['goals_min']}, {tc['goals_max']}]",
                )

                # Check expected market type
                if tc["expect_over_15"]:
                    expected_market = "Over 1.5"
                else:
                    expected_market = "Under"
                market_ok = result["recommended_market"].startswith(expected_market[:4])
                self._assert(
                    market_ok,
                    f"{name} recommended_market starts with {expected_market[:4]}",
                    f"Got '{result['recommended_market']}'",
                )

                # Check strength
                self._assert(
                    result["strength"] in ("STRONG", "MODERATE", "WEAK"),
                    f"{name} strength valid",
                    f"Got '{result['strength']}'",
                )

                # Check confidence is reasonable
                self._assert(
                    40 <= result["confidence"] <= 99,
                    f"{name} confidence in [40, 99]",
                    f"Got {result['confidence']}",
                )

                # Check breakdown structure
                bd = result["breakdown"]
                for key in ("L1_all_time_profiles", "L2_h2h_history", "L3_recent_form"):
                    self._assert(
                        key in bd,
                        f"{name} breakdown has {key}",
                    )

                # Check signals - should have at least 3
                self._assert(
                    len(result["signals"]) >= 3,
                    f"{name} has >=3 signals",
                    f"Got {len(result['signals'])}",
                )

                # Check market validation
                if tc["expect_market_validation"]:
                    mv = result.get("market_validation")
                    self._assert(
                        mv is not None,
                        f"{name} has market_validation",
                    )
                    if mv:
                        self._assert(
                            isinstance(mv.get("market_data_found"), bool),
                            f"{name} market_data_found is bool",
                        )

                if self.verbose:
                    print(
                        f"  ✓ {name}: {eg}g → {result['recommended_market']} "
                        f"({result['confidence']}%, {result['strength']})"
                    )

            except Exception as e:
                self._record(name, False, f"Exception: {type(e).__name__}: {e}")
                if self.verbose:
                    traceback.print_exc()

    def _test_edge_cases(self):
        """Test edge cases."""
        for tc in EDGE_CASES:
            name = f"edge '{tc['home']}' vs '{tc['away']}'"
            try:
                result = self.engine.analyze_fixture(tc["home"], tc["away"])
                if tc.get("should_error"):
                    self._record(name, False, "Should have raised error but didn't")
                else:
                    self._record(name, True)
            except (ValueError, Exception) as e:
                if tc.get("should_error"):
                    self._record(name, True)
                else:
                    self._record(name, False, f"Unexpected error: {e}")

    def _test_batch_analysis(self):
        """Test batch analysis mode."""
        fixtures = [
            ("Everton", "Leeds"),
            ("Manchester Blue", "Wolverhampton"),
        ]
        results = self.engine.analyze_fixtures(fixtures)
        self._assert(
            len(results) == 2,
            "batch returned 2 results",
            f"Got {len(results)}",
        )
        for r in results:
            if "error" not in r:
                self._assert(
                    "expected_goals" in r,
                    f"batch result has expected_goals for {r['fixture']}",
                )

    def _test_h2h_summary(self):
        """Test static H2H summary method."""
        engine = self.engine
        try:
            summary = FixtureIntelligenceEngine.get_h2h_summary(
                engine.results_db_path, "Everton", "Leeds"
            )
            self._assert(
                summary["n_matches"] > 0,
                "H2H summary has matches",
                f"Got {summary['n_matches']}",
            )
            if summary["n_matches"] > 0:
                self._assert(
                    "avg_total_goals" in summary,
                    "H2H summary has avg_total_goals",
                )
                self._assert(
                    "o1_5_pct" in summary,
                    "H2H summary has o1_5_pct",
                )
        except Exception as e:
            self._record("H2H summary", False, str(e))

    def report(self) -> int:
        """Print a summary report. Returns number of failures."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        print(f"\n{'=' * 60}")
        print(f"  TEST SUMMARY")
        print(f"{'=' * 60}")
        print(f"  Total:  {total}")
        print(f"  Passed: {passed}")
        print(f"  Failed: {failed}")
        if failed > 0:
            print(f"\n  FAILURES:")
            for r in self.results:
                if not r.passed:
                    print(f"    ✗ {r.name}")
                    if r.details:
                        print(f"      {r.details}")
        print(f"{'=' * 60}")

        return failed


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="VFL Fixture Intelligence Engine - Test Suite",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--list", action="store_true", help="List test fixtures")
    parser.add_argument("--quick", action="store_true", help="Quick smoke test only")
    parser.add_argument(
        "--fixture", nargs=2, metavar=("HOME", "AWAY"),
        help="Run a single fixture analysis",
    )

    args = parser.parse_args()

    if args.list:
        print(f"\nVFL Fixture Intelligence Engine — Test Fixtures\n")
        print(f"{'Home':20s} {'Away':20s} {'Goals Range':15s} {'O1.5?':8s} {'Description'}")
        print("-" * 90)
        for tc in TEST_FIXTURES:
            exp = "O1.5" if tc["expect_over_15"] else "UNDER"
            gr = f"[{tc['goals_min']}, {tc['goals_max']}]"
            print(f"{tc['home']:20s} {tc['away']:20s} {gr:15s} {exp:8s} {tc['description']}")
        print()
        return 0

    if args.fixture:
        engine = FixtureIntelligenceEngine()
        try:
            home, away = args.fixture
            result = engine.analyze_fixture(home, away)
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        finally:
            engine.close()
        return 0

    suite = TestSuite(verbose=args.verbose or args.quick)

    if args.quick:
        # Quick smoke test: just the key fixtures
        print("\n  Quick smoke test...")
        for tc in TEST_FIXTURES[:3]:
            try:
                result = suite.engine.analyze_fixture(tc["home"], tc["away"])
                eg = result["expected_goals"]
                market = result["recommended_market"]
                conf = result["confidence"]
                strength = result["strength"]
                print(
                    f"  ✓ {tc['home']:15s} vs {tc['away']:15s}: "
                    f"{eg:.2f}g → {market:12s} ({conf}%, {strength})"
                )
            except Exception as e:
                print(f"  ✗ {tc['home']} vs {tc['away']}: {e}")
        print("\n  Smoke test complete.")
        return 0

    print(f"\n{'=' * 60}")
    print(f"  VFL FIXTURE INTELLIGENCE ENGINE — TEST SUITE")
    print(f"{'=' * 60}")
    print(f"  Teams: {len(TEAMS)}")
    print(f"  Test cases: {len(TEST_FIXTURES)}")
    print(f"  Database: {suite.engine.results_db_path}")
    print(f"{'=' * 60}\n")

    suite.run_all()

    failures = suite.report()
    return failures


if __name__ == "__main__":
    sys.exit(main())
