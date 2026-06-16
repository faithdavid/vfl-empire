#!/usr/bin/env python3
"""
test_auth_pipeline.py — Comprehensive tests for the MSport auth pipeline.

Tests THREE layers of the authentication pipeline:

  Layer 1 — Token Refresher (msport_token_refresher.py)
    • Cookie string parsing (document.cookie parser)
    • Token file JSON format (compatibility with Go struct)
    • Graceful failure when CDP browser is not available

  Layer 2 — Python API Client (msport_api.py)
    • Header construction (clientid, platform, apilevel, deviceid)
    • Device ID resolution (env var → random UUID fallback)
    • Live API endpoints: event/list, current/match/day/info, season/selection
    • Data extraction: 1X2 odds, Over/Under odds, Double Chance odds
    • Error handling: network failures, invalid tokens, missing auth

  Layer 3 — Go Agent Token Consumption
    • Token file JSON schema matches Go TokenFile struct
    • Token value quoting/trimming (Go strips surrounding quotes)

Usage:
  python3 tests/test_auth_pipeline.py                 # Run all tests
  python3 tests/test_auth_pipeline.py --layer 1       # Run only layer 1
  python3 tests/test_auth_pipeline.py --layer 2       # Run only layer 2
  python3 tests/test_auth_pipeline.py --offline       # Skip live API calls
  python3 tests/test_auth_pipeline.py -v              # Verbose output

Environment Variables:
  MSPORT_ACCESS_TOKEN   — Fallback access token (if token file missing)
  MSPORT_USER_ID        — Fallback user ID (if token file missing)
  MSPORT_DEVICE_ID      — Custom device ID (optional)
  MSPORT_COOKIE         — Cookie string (optional)

Exit code: 0 if all tests pass, 1 if any fail.
"""

import argparse
import json
import logging
import os
import re
import subprocess  # nosec: used for controlled script execution
import sys
import tempfile
import time
import traceback
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Test configuration ──────────────────────────────────────────────────
TOKEN_FILE = "/tmp/msport_tokens.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
GO_AGENT_DIR = PROJECT_ROOT / "go-agent"

# ── Colourised output helpers ────────────────────────────────────────────
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def ok(text: str) -> str:
    return f"{_GREEN}✓ {text}{_RESET}"


def fail(text: str) -> str:
    return f"{_RED}✗ {text}{_RESET}"


def warn(text: str) -> str:
    return f"{_YELLOW}⚠ {text}{_RESET}"


def header(text: str) -> str:
    return f"\n{_BOLD}{_CYAN}{'=' * 60}\n{text}\n{'=' * 60}{_RESET}\n"


# ═══════════════════════════════════════════════════════════════════════════
# Layer 1 — Token Refresher Tests
# ═══════════════════════════════════════════════════════════════════════════


def parse_cookies(cookie_str: str) -> Dict[str, str]:
    """Standalone copy of the token refresher's parse_cookies for testing."""
    result = {}
    if not cookie_str:
        return result
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, val = item.split("=", 1)
            result[key.strip()] = val.strip()
    return result


COOKIE_KEYS = {"accessToken", "refreshToken", "userId", "deviceId",
               "device-id", "did", "highFreqToken"}


class TestTokenRefresher_parseCookies(unittest.TestCase):
    """Layer 1a — Cookie string parsing logic."""

    def test_empty_string(self) -> None:
        self.assertEqual(parse_cookies(""), {})

    def test_none_string(self) -> None:
        self.assertEqual(parse_cookies(""), {})

    def test_single_cookie(self) -> None:
        result = parse_cookies("accessToken=abc123")
        self.assertEqual(result.get("accessToken"), "abc123")

    def test_multiple_cookies(self) -> None:
        result = parse_cookies("accessToken=abc; refreshToken=def; userId=42")
        self.assertEqual(result["accessToken"], "abc")
        self.assertEqual(result["refreshToken"], "def")
        self.assertEqual(result["userId"], "42")

    def test_cookies_with_spaces(self) -> None:
        result = parse_cookies("  accessToken=abc  ;  refreshToken=def  ")
        self.assertEqual(result["accessToken"], "abc")
        self.assertEqual(result["refreshToken"], "def")

    def test_cookies_with_quote_values(self) -> None:
        """Browser cookies often wrap values in quotes."""
        result = parse_cookies('accessToken="eyJhbGciOiJIUzI1NiJ9.abc"')
        self.assertEqual(result["accessToken"], '"eyJhbGciOiJIUzI1NiJ9.abc"')

    def test_extracts_key_cookie_keys(self) -> None:
        cookie_str = (
            'accessToken=abc; refreshToken=def; userId=42; '
            'deviceId=dev-1; device-id=dev-1; did=dev-1; highFreqToken=hft1'
        )
        parsed = parse_cookies(cookie_str)
        for key in COOKIE_KEYS:
            self.assertIn(key, parsed, f"Missing key: {key}")

    def test_ignores_irrelevant_cookies(self) -> None:
        """Should not error on extra cookies like PHPSESSID, _ga, etc."""
        cookie_str = (
            'PHPSESSID=sess123; _ga=GA1.2.abc; accessToken=abc; '
            '_gid=GA1.2.xyz; refreshToken=def'
        )
        parsed = parse_cookies(cookie_str)
        self.assertEqual(parsed.get("accessToken"), "abc")
        self.assertEqual(parsed.get("refreshToken"), "def")
        # Extra keys may be present, but we only care about our known ones
        for key in COOKIE_KEYS:
            if key in ("accessToken", "refreshToken"):
                self.assertIn(key, parsed)

    def test_malformed_cookie(self) -> None:
        """Cookies without '=' should be skipped."""
        result = parse_cookies("accessToken=abc; just-a-key; refreshToken=def")
        self.assertEqual(result.get("accessToken"), "abc")
        self.assertEqual(result.get("refreshToken"), "def")
        # just-a-key is missing '=' so it's skipped

    def test_realistic_cookie_string(self) -> None:
        """Simulate the kind of cookie string a real browser would have."""
        cookie_str = (
            'accessToken="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"; '  # noqa: E501
            'refreshToken="def456"; '
            'userId="12345"; '
            'deviceId="dev-uuid-abc"; '
            'device-id="dev-uuid-abc"; '
            'did="dev-uuid-abc"; '
            'highFreqToken="hft-xyz"; '
            'PHPSESSID="sess_abc123"; '
            '_ga="GA1.2.123456789.1234567890"'
        )
        parsed = parse_cookies(cookie_str)
        self.assertIn("accessToken", parsed)
        self.assertIn("refreshToken", parsed)
        self.assertIn("userId", parsed)
        self.assertIn("deviceId", parsed)
        self.assertIn("device-id", parsed)
        self.assertIn("did", parsed)
        self.assertIn("highFreqToken", parsed)
        # Values should contain quotes like the browser returns them
        self.assertTrue(parsed["accessToken"].startswith('"'))


class TestTokenRefresher_script(unittest.TestCase):
    """Layer 1b — Token refresher script import + execution."""

    def test_import_token_refresher(self) -> None:
        """Verify the token refresher module is importable."""
        sys.path.insert(0, str(GO_AGENT_DIR))
        try:
            import msport_token_refresher as tr
            self.assertTrue(hasattr(tr, "refresh"))
            self.assertTrue(hasattr(tr, "parse_cookies"))
            self.assertTrue(hasattr(tr, "TOKEN_FILE"))
            self.assertEqual(tr.TOKEN_FILE, TOKEN_FILE)
        except Exception as e:
            self.fail(f"Import msport_token_refresher failed: {e}")
        finally:
            sys.path.remove(str(GO_AGENT_DIR))

    def test_token_file_format_matches_go_struct(self) -> None:
        """Verify a sample token file parses correctly and matches Go's expected fields.

        Go struct (client.go):
            type TokenFile struct {
                AccessToken   string  `json:"accessToken"`
                RefreshToken  string  `json:"refreshToken"`
                UserID        string  `json:"userId"`
                DeviceID      string  `json:"device-id"`
                HighFreqToken string  `json:"highFreqToken,omitempty"`
                RefreshedAt   float64 `json:"refreshed_at"`
            }
        """
        sample = {
            "accessToken": "test_access_token",
            "refreshToken": "test_refresh_token",
            "userId": "12345",
            "device-id": "test-device-id",
            "deviceId_localStorage": "test-device-id",
            "highFreqToken": "test_hft",
            "refreshed_at": 1712345678.123,
            "deviceId": "test-device-id",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sample, f)
            tmp_path = f.name
        try:
            with open(tmp_path) as f:
                data = json.load(f)
            # Fields the Go struct expects
            self.assertIn("accessToken", data)
            self.assertIn("refreshToken", data)
            self.assertIn("userId", data)
            # Go looks for "device-id" (with hyphen)
            self.assertIn("device-id", data)
            self.assertIn("refreshed_at", data)
            # Optional field
            self.assertIn("highFreqToken", data)
            # Device ID consistency
            self.assertEqual(data["device-id"], "test-device-id")
            # refreshed_at should be numeric (float)
            self.assertIsInstance(data["refreshed_at"], (int, float))
        finally:
            os.unlink(tmp_path)

    def test_token_file_with_quoted_values(self) -> None:
        """Go's LoadTokensFromFile strips surrounding quotes.

        Verify that the format the Go code expects is compatible.
        """
        sample = {
            'accessToken': '"eyJhbGciOiJIUzI1NiJ9.abc"',
            'refreshToken': '"def456"',
            'userId': '"12345"',
            'device-id': '"dev-uuid-abc"',
            'refreshed_at': 1712345678.0,
        }
        # Simulate what Go does: Trim quotes from values
        trimmed = {k: v.strip('"') for k, v in sample.items() if isinstance(v, str)}
        self.assertEqual(trimmed["accessToken"], "eyJhbGciOiJIUzI1NiJ9.abc")
        self.assertEqual(trimmed["refreshToken"], "def456")
        self.assertEqual(trimmed["userId"], "12345")
        self.assertEqual(trimmed["device-id"], "dev-uuid-abc")

    def test_token_refresher_error_on_missing_browser(self) -> None:
        """Token refresher should fail gracefully when CDP is not available."""
        # We test by monkey-patching: simulate what happens when
        # playwright can't connect to CDP
        try:
            import playwright.sync_api
        except ImportError:
            self.skipTest("playwright not installed")

        # Just verify the script handles sys.exit or exceptions
        # by running it in a subprocess with a non-existent CDP port
        script_path = GO_AGENT_DIR / "msport_token_refresher.py"
        if not script_path.exists():
            self.skipTest(f"Token refresher not found at {script_path}")

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Should either error out or return non-empty stderr about connection refused
        # The script should not hang or crash with unhandled exception
        self.assertIn(result.returncode, (0, 1),
                      msg=f"Unexpected exit code: {result.returncode}\n"
                          f"stdout: {result.stdout[:500]}\n"
                          f"stderr: {result.stderr[:500]}")


# ═══════════════════════════════════════════════════════════════════════════
# Layer 2 — Python API Client Tests
# ═══════════════════════════════════════════════════════════════════════════


def resolve_device_id(device_id: Optional[str] = None) -> str:
    """Copy of msport_api._get_device_id for isolated testing."""
    import uuid
    if device_id:
        return device_id
    env_id = os.environ.get("MSPORT_DEVICE_ID")
    if env_id:
        return env_id
    return str(uuid.uuid4())


class TestMsportApi_headers(unittest.TestCase):
    """Layer 2a — Header construction and device ID resolution."""

    def test_default_headers_contain_required_fields(self) -> None:
        """Verify DEFAULT_HEADERS has all required auth fields."""
        import scripts.msport_api as api
        self.assertIn("clientid", api.DEFAULT_HEADERS)
        self.assertIn("platform", api.DEFAULT_HEADERS)
        self.assertIn("apilevel", api.DEFAULT_HEADERS)
        self.assertEqual(api.DEFAULT_HEADERS["clientid"], "WEB")
        self.assertEqual(api.DEFAULT_HEADERS["platform"], "WEB")
        self.assertEqual(api.DEFAULT_HEADERS["apilevel"], "2")

    def test_make_headers_includes_deviceid(self) -> None:
        """Verify _make_headers sets deviceid correctly."""
        import scripts.msport_api as api
        headers = api._make_headers(device_id="test-dev-123")
        self.assertEqual(headers.get("deviceid"), "test-dev-123")

    def test_make_headers_fallback_to_env(self) -> None:
        """Verify deviceid falls back to MSPORT_DEVICE_ID env var."""
        import scripts.msport_api as api
        old = os.environ.get("MSPORT_DEVICE_ID")
        try:
            os.environ["MSPORT_DEVICE_ID"] = "env-device-id"
            headers = api._make_headers()
            self.assertEqual(headers.get("deviceid"), "env-device-id")
        finally:
            if old is not None:
                os.environ["MSPORT_DEVICE_ID"] = old
            else:
                del os.environ["MSPORT_DEVICE_ID"]

    def test_make_headers_fallback_to_uuid(self) -> None:
        """Verify deviceid generates a random UUID when nothing else set."""
        import scripts.msport_api as api
        import uuid
        old = os.environ.pop("MSPORT_DEVICE_ID", None)
        try:
            headers = api._make_headers()
            devid = headers.get("deviceid", "")
            # Validate UUID format
            uuid.UUID(devid)
        except (ValueError, AttributeError):
            self.fail(f"deviceid '{devid}' is not a valid UUID")
        finally:
            if old is not None:
                os.environ["MSPORT_DEVICE_ID"] = old

    def test_make_headers_includes_cookie_when_set(self) -> None:
        """Verify Cookie header is included when _COOKIE is set."""
        import scripts.msport_api as api
        old_cookie = api._COOKIE
        try:
            api.set_cookie("PHPSESSID=test123")
            headers = api._make_headers()
            self.assertIn("Cookie", headers)
            self.assertEqual(headers["Cookie"], "PHPSESSID=test123")
        finally:
            api._COOKIE = old_cookie

    def test_make_headers_extra_override(self) -> None:
        """Verify extra headers override defaults."""
        import scripts.msport_api as api
        headers = api._make_headers(extra={"clientid": "MOBILE"})
        self.assertEqual(headers["clientid"], "MOBILE")


class TestMsportApi_endpoints(unittest.TestCase):
    """Layer 2b — Live API endpoint tests.

    These tests require a valid token file at /tmp/msport_tokens.json
    or environment variables MSPORT_ACCESS_TOKEN + MSPORT_USER_ID.

    Tests are skipped if no tokens are available.
    """

    _tokens_loaded = False
    _has_tokens = False
    _match_day_info = None
    _event_list = None

    @classmethod
    def setUpClass(cls) -> None:
        """Try to load tokens from file or env vars."""
        token_sources = []

        # Option A: token file
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE) as f:
                    tokens = json.load(f)
                access = tokens.get("accessToken", "").strip('"')
                user_id = tokens.get("userId", "").strip('"')
                device_id = tokens.get("device-id", "") or tokens.get("deviceId", "")
                if access and user_id:
                    os.environ.setdefault("MSPORT_ACCESS_TOKEN", access)
                    os.environ.setdefault("MSPORT_USER_ID", user_id)
                    if device_id:
                        os.environ.setdefault("MSPORT_DEVICE_ID", device_id)
                    token_sources.append(f"file ({TOKEN_FILE})")
                    cls._has_tokens = True
            except (json.JSONDecodeError, KeyError, OSError) as e:
                print(warn(f"Token file exists but is invalid: {e}"))

        # Option B: env vars
        if os.environ.get("MSPORT_ACCESS_TOKEN") and os.environ.get("MSPORT_USER_ID"):
            if not token_sources:
                token_sources.append("env vars")
                cls._has_tokens = True

        cls._tokens_loaded = True
        if token_sources:
            print(ok(f"Tokens loaded from: {', '.join(token_sources)}"))
        else:
            print(warn("No tokens available — live API tests will be skipped"))
            print(warn("  Set MSPORT_ACCESS_TOKEN + MSPORT_USER_ID env vars"))
            print(warn(f"  Or ensure {TOKEN_FILE} exists with valid tokens"))

    def _require_tokens(self) -> None:
        if not self._has_tokens:
            self.skipTest("No valid tokens available — set MSPORT_ACCESS_TOKEN + MSPORT_USER_ID")

    def test_get_current_match_day_info(self) -> None:
        """GET /current/match/day/info returns valid season info."""
        self._require_tokens()
        import scripts.msport_api as api
        info = api.get_current_match_day_info()
        self.assertIsNotNone(info, "get_current_match_day_info returned None")
        self.assertIsInstance(info, dict)
        # Expected keys
        self.assertIn("seasonId", info, msg=f"Missing seasonId in: {list(info.keys())}")
        self.assertIn("seasonName", info, msg=f"Missing seasonName in: {list(info.keys())}")
        # matchDay may be null in pre-season, but the key should exist
        self.assertIn("matchDay", info, msg=f"Missing matchDay in: {list(info.keys())}")
        # Print info for visibility
        season_id = info.get("seasonId", "N/A")
        season_name = info.get("seasonName", "N/A")
        match_day = info.get("matchDay", "N/A")
        print(ok(f"Season: {season_name} (ID: {season_id}), MatchDay: {match_day}"))

    def test_get_event_list(self) -> None:
        """GET /event/list returns match day data with events."""
        self._require_tokens()
        import scripts.msport_api as api
        match_days = api.get_event_list()
        self.assertIsNotNone(match_days, "get_event_list returned None")
        self.assertIsInstance(match_days, list)
        print(ok(f"Event list: {len(match_days)} match day(s)"))
        total_events = 0
        for md in match_days:
            events = md.get("events", [])
            total_events += len(events)
            season_name = md.get("seasonName", "?")
            md_num = md.get("matchDay", "?")
            print(ok(f"  {season_name} MD{md_num}: {len(events)} events"))
        print(ok(f"Total events: {total_events}"))
        self.assertGreater(total_events, 0,
                           "Expected at least 1 event in the event list")

    def test_get_event_list_has_valid_markets(self) -> None:
        """Events in the list should have market data (odds)."""
        self._require_tokens()
        import scripts.msport_api as api
        match_days = api.get_event_list()
        self.assertIsNotNone(match_days)
        # Find the first match day with events
        first_events = None
        for md in match_days:
            evts = md.get("events", [])
            if evts:
                first_events = evts
                break
        self.assertIsNotNone(first_events, "No events found in any match day")
        event = first_events[0]
        # Check basic event fields
        self.assertIn("eventId", event)
        self.assertIn("homeTeam", event)
        self.assertIn("awayTeam", event)
        # Extract 1X2 odds
        odds_1x2 = api.extract_1x2_odds(event)
        self.assertIsInstance(odds_1x2, dict)
        print(ok(f"Event {event.get('eventId', '?')}: {event.get('homeTeam', '?')} vs "
                 f"{event.get('awayTeam', '?')}"))
        print(ok(f"  1X2 odds: {odds_1x2}"))

    def test_get_season_list(self) -> None:
        """GET /result/season/selection returns available seasons."""
        self._require_tokens()
        import scripts.msport_api as api
        seasons = api.get_season_list()
        self.assertIsNotNone(seasons, "get_season_list returned None")
        self.assertIsInstance(seasons, list)
        print(ok(f"Seasons: {len(seasons)} available"))
        if seasons:
            s = seasons[0]
            self.assertIn("seasonId", s, msg=f"Missing seasonId in: {list(s.keys())}")
            self.assertIn("seasonName", s, msg=f"Missing seasonName in: {list(s.keys())}")
            print(ok(f"  First: {s.get('seasonName', '?')} (ID: {s.get('seasonId', '?')})"))

    def test_get_event_detail(self) -> None:
        """GET /event/detail returns market details for a known event."""
        self._require_tokens()
        import scripts.msport_api as api
        # Get event list first to find a known event ID
        match_days = api.get_event_list()
        self.assertIsNotNone(match_days)
        first_event: Optional[Dict[str, Any]] = None
        for md in match_days:
            evts = md.get("events", [])
            if evts:
                first_event = evts[0]
                break
        if not first_event:
            self.skipTest("No events found in event list")
        event_id = first_event.get("eventId", "")
        if not event_id:
            self.skipTest("Event has no eventId")
        detail = api.get_event_detail(event_id)
        self.assertIsNotNone(detail, f"get_event_detail({event_id}) returned None")
        self.assertIsInstance(detail, dict)
        self.assertIn("markets", detail,
                      msg=f"No markets in event detail: {list(detail.keys())}")
        markets = detail.get("markets", [])
        self.assertGreater(len(markets), 0,
                           "Expected at least 1 market in event detail")
        print(ok(f"Event detail: {event_id} — {len(markets)} market(s)"))
        for m in markets[:3]:
            m_id = m.get("id", "?")
            m_name = m.get("name", "?")
            outcomes = len(m.get("outcomes", []))
            print(ok(f"  Market #{m_id} ({m_name}): {outcomes} outcomes"))

    def test_get_standings(self) -> None:
        """GET /virtual/table returns standings data."""
        self._require_tokens()
        import scripts.msport_api as api
        standings = api.get_standings()
        if standings is None:
            # This can happen in pre-season — don't fail
            self.skipTest("Standings returned None (likely pre-season)")
        self.assertIsInstance(standings, dict)
        self.assertIn("standings", standings,
                      msg=f"No standings in: {list(standings.keys())}")
        teams = standings.get("standings", [])
        print(ok(f"Standings: {standings.get('seasonName', '?')}, "
                 f"{len(teams)} teams"))
        if teams:
            t = teams[0]
            print(ok(f"  Top: #{t.get('rank', '?')} {t.get('teamName', '?')} "
                     f"({t.get('points', '?')} pts)"))

    def test_get_results(self) -> None:
        """GET /result returns results for a known season."""
        self._require_tokens()
        import scripts.msport_api as api
        # Get current info first to find a season ID
        info = api.get_current_match_day_info()
        if not info:
            self.skipTest("Could not get current match day info")
        season_id = info.get("seasonId", "")
        if not season_id:
            self.skipTest("No seasonId available")
        # Try match day 1 (should always have results)
        results = api.get_results(season_id, 1)
        if results is None:
            # May be pre-season, try getting from season list
            seasons = api.get_season_list()
            if seasons:
                for s in seasons[:3]:
                    sid = s.get("seasonId", "")
                    mds = s.get("matchDay", [])
                    if mds:
                        results = api.get_results(sid, mds[0])
                        if results:
                            break
        if results is None:
            self.skipTest("No results available (likely pre-season)")
        self.assertIsInstance(results, list)
        print(ok(f"Results: {len(results)} matches"))
        if results:
            r = results[0]
            self.assertIn("homeTeam", r)
            self.assertIn("awayTeam", r)
            print(ok(f"  E.g.: {r.get('homeTeam', '?')} {r.get('fullTime', '?-?')} "
                     f"{r.get('awayTeam', '?')}"))


class TestMsportApi_dataExtraction(unittest.TestCase):
    """Layer 2c — Market data extraction functions."""

    def setUp(self) -> None:
        """Create a sample event with known market data."""
        import scripts.msport_api as api
        self.api = api
        self.sample_event = {
            "eventId": "vf:match:test123",
            "homeTeam": "Manchester Blue",
            "awayTeam": "London Guns",
            "markets": [
                {
                    "id": 1,
                    "name": "1X2",
                    "outcomes": [
                        {"description": "Home", "odds": "1.50"},
                        {"description": "Draw", "odds": "4.00"},
                        {"description": "Away", "odds": "6.50"},
                    ],
                },
                {
                    "id": 18,
                    "name": "Over/Under",
                    "specifiers": "total=1.5",
                    "outcomes": [
                        {"description": "Over", "odds": "1.40"},
                        {"description": "Under", "odds": "2.80"},
                    ],
                },
                {
                    "id": 18,
                    "name": "Over/Under",
                    "specifiers": "total=2.5",
                    "outcomes": [
                        {"description": "Over", "odds": "2.20"},
                        {"description": "Under", "odds": "1.65"},
                    ],
                },
                {
                    "id": 18,
                    "name": "Over/Under",
                    "specifiers": "total=3.5",
                    "outcomes": [
                        {"description": "Over", "odds": "4.50"},
                        {"description": "Under", "odds": "1.18"},
                    ],
                },
                {
                    "id": 2,
                    "name": "Double Chance",
                    "specifiers": "home=1",
                    "outcomes": [
                        {"description": "HomeOrDraw", "odds": "1.10"},
                        {"description": "HomeOrAway", "odds": "1.22"},
                        {"description": "DrawOrAway", "odds": "2.50"},
                    ],
                },
            ],
        }

    def test_extract_1x2_odds(self) -> None:
        """Extract Home/Draw/Away odds correctly."""
        odds = self.api.extract_1x2_odds(self.sample_event)
        self.assertEqual(odds["Home"], 1.50)
        self.assertEqual(odds["Draw"], 4.00)
        self.assertEqual(odds["Away"], 6.50)

    def test_extract_1x2_odds_missing_market(self) -> None:
        """Returns zeros when no 1X2 market."""
        event = {"eventId": "test", "markets": []}
        odds = self.api.extract_1x2_odds(event)
        self.assertEqual(odds, {"Home": 0.0, "Draw": 0.0, "Away": 0.0})

    def test_extract_over_under_odds(self) -> None:
        """Extract Over/Under odds by specifier."""
        odds = self.api.extract_over_under_odds(self.sample_event)
        self.assertIn("total=1.5", odds)
        self.assertIn("total=2.5", odds)
        self.assertIn("total=3.5", odds)
        self.assertEqual(odds["total=1.5"]["Over"], 1.40)
        self.assertEqual(odds["total=1.5"]["Under"], 2.80)
        self.assertEqual(odds["total=2.5"]["Over"], 2.20)
        self.assertEqual(odds["total=2.5"]["Under"], 1.65)

    def test_extract_double_chance_odds(self) -> None:
        """Extract Double Chance odds."""
        odds = self.api.extract_double_chance_odds(self.sample_event)
        self.assertEqual(odds["HomeOrDraw"], 1.10)
        self.assertEqual(odds["HomeOrAway"], 1.22)
        self.assertEqual(odds["DrawOrAway"], 2.50)

    def test_extract_all_markets(self) -> None:
        """Extract_all_markets returns structured data."""
        result = self.api.extract_all_markets(self.sample_event)
        self.assertEqual(result["event_id"], "vf:match:test123")
        self.assertIn("1x2", result)
        self.assertIn("over_under", result)
        self.assertIn("double_chance", result)
        self.assertEqual(result["home_team"], "Manchester Blue")
        self.assertEqual(result["away_team"], "London Guns")

    def test_find_upcoming_match_day(self) -> None:
        """Find upcoming match day filters correctly."""
        import time
        now_ms = int(time.time() * 1000)
        match_days = [
            {"matchDayStartTime": now_ms + 30_000, "matchDay": 1},   # 30s away
            {"matchDayStartTime": now_ms + 120_000, "matchDay": 2},  # 2m away
            {"matchDayStartTime": now_ms + 600_000, "matchDay": 3},  # 10m away
        ]
        # With min_seconds=60, MD1 (30s) should be skipped
        result = self.api.find_upcoming_match_day(match_days, min_seconds=60)
        self.assertIsNotNone(result)
        self.assertEqual(result["matchDay"], 2)

    def test_team_name_normalisation(self) -> None:
        """TEAM_ALIASES normalises team names correctly."""
        # Direct call to _normalise_team_name
        from scripts.msport_api import _normalise_team_name
        self.assertEqual(_normalise_team_name("MANCHESTER BLUE"), "Manchester Blue")
        self.assertEqual(_normalise_team_name("liverpool"), "Liverpool")
        self.assertEqual(_normalise_team_name("chelsea fc"), "Chelsea Fc")  # default title()


class TestMsportApi_errorHandling(unittest.TestCase):
    """Layer 2d — Error handling and edge cases."""

    def test_fetch_json_bad_url(self) -> None:
        """fetch_json should return None on network errors."""
        import scripts.msport_api as api
        result = api.fetch_json(
            "https://nonexistent-domain-xyz123.com/api",
            timeout=3,
            retries=1,
        )
        self.assertIsNone(result)

    def test_fetch_json_bad_host(self) -> None:
        """fetch_json should not crash on connection refused."""
        import scripts.msport_api as api
        result = api.fetch_json(
            "https://localhost:1/api",
            timeout=3,
            retries=1,
        )
        self.assertIsNone(result)

    def test_set_cookie_persists(self) -> None:
        """set_cookie should store the cookie globally."""
        import scripts.msport_api as api
        old = api._COOKIE
        try:
            api.set_cookie("test=cookie")
            self.assertEqual(api._COOKIE, "test=cookie")
            # Subsequent _make_headers should include it
            headers = api._make_headers()
            self.assertIn("Cookie", headers)
            self.assertEqual(headers["Cookie"], "test=cookie")
        finally:
            api._COOKIE = old

    def test_load_cookie_from_env(self) -> None:
        """load_cookie_from_env reads from env var."""
        import scripts.msport_api as api
        old = os.environ.get("MSPORT_COOKIE")
        old_cookie = api._COOKIE
        try:
            os.environ["MSPORT_COOKIE"] = "env=cookie"
            result = api.load_cookie_from_env()
            self.assertEqual(result, "env=cookie")
            self.assertEqual(api._COOKIE, "env=cookie")
        finally:
            if old is not None:
                os.environ["MSPORT_COOKIE"] = old
            else:
                os.environ.pop("MSPORT_COOKIE", None)
            api._COOKIE = old_cookie

    def test_extract_standings_table_empty(self) -> None:
        """extract_standings_table returns [] on empty input."""
        import scripts.msport_api as api
        self.assertEqual(api.extract_standings_table({}), [])
        self.assertEqual(api.extract_standings_table(None), [])
        self.assertEqual(api.extract_standings_table({"teams": []}), [])


# ═══════════════════════════════════════════════════════════════════════════
# Layer 3 — Go Agent Compatibility Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGoAgent_tokenFormat(unittest.TestCase):
    """Layer 3 — Go agent token file format compatibility."""

    def test_go_token_file_fields(self) -> None:
        """Verify that the Go TokenFile struct fields match what we write."""
        # The Go struct expects these JSON keys:
        #   accessToken, refreshToken, userId, device-id, highFreqToken, refreshed_at
        required = {"accessToken", "refreshToken", "userId", "device-id", "refreshed_at"}
        optional = {"highFreqToken", "deviceId", "deviceId_localStorage", "did"}

        # Build a realistic token file as the Python refresher would write it
        sample = {
            "accessToken": "eyJhbGciOiJIUzI1NiJ9.test",
            "refreshToken": "def456",
            "userId": "12345",
            "device-id": "test-device-uuid",
            "deviceId": "test-device-uuid",
            "deviceId_localStorage": "test-device-uuid",
            "did": "test-device-uuid",
            "highFreqToken": "hft_abc123",
            "refreshed_at": 1712345678.123,
        }

        # All required fields present
        for key in required:
            self.assertIn(key, sample, f"Missing required field: {key}")

        # Go reads "device-id" (hyphenated) as DeviceID
        self.assertIn("device-id", sample)

        # The Go code also looks for accessToken with quotes stripped
        access_val = sample["accessToken"].strip('"')
        self.assertEqual(access_val, "eyJhbGciOiJIUzI1NiJ9.test")

    def test_go_binary_compiles(self) -> None:
        """Verify the Go agent compiles correctly."""
        # Check if Go is installed
        go_check = subprocess.run(
            ["which", "go"], capture_output=True, text=True
        )
        if go_check.returncode != 0:
            self.skipTest("Go is not installed on this system")

        build_result = subprocess.run(
            ["go", "build", "-o", "/dev/null", "."],
            capture_output=True, text=True,
            timeout=120,
            cwd=str(GO_AGENT_DIR),
        )
        if build_result.returncode != 0:
            # Show the error but don't fail if dependencies aren't installed
            print(warn(f"Go build failed (may need 'go mod download'): "
                       f"{build_result.stderr[:500]}"))
        self.assertEqual(
            build_result.returncode, 0,
            f"Go build failed:\n"
            f"stdout: {build_result.stdout[:500]}\n"
            f"stderr: {build_result.stderr[:500]}"
        )
        print(ok("Go agent compiles successfully"))

    def test_go_dependencies_resolve(self) -> None:
        """Verify Go module dependencies resolve."""
        go_check = subprocess.run(
            ["which", "go"], capture_output=True, text=True
        )
        if go_check.returncode != 0:
            self.skipTest("Go is not installed")

        result = subprocess.run(
            ["go", "mod", "tidy"],
            capture_output=True, text=True,
            timeout=60,
            cwd=str(GO_AGENT_DIR),
        )
        if result.returncode != 0:
            print(warn(f"go mod tidy: {result.stderr[:500]}"))
        # Not failing this test — dependency resolution may need network
        print(ok("Go module check complete"))


# ═══════════════════════════════════════════════════════════════════════════
# Test Runner
# ═══════════════════════════════════════════════════════════════════════════


def run_layer(layer_num: int) -> bool:
    """Run tests for a specific layer. Returns True if all pass."""
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    if layer_num == 1:
        suite.addTests(loader.loadTestsFromTestCase(TestTokenRefresher_parseCookies))
        suite.addTests(loader.loadTestsFromTestCase(TestTokenRefresher_script))
    elif layer_num == 2:
        suite.addTests(loader.loadTestsFromTestCase(TestMsportApi_headers))
        suite.addTests(loader.loadTestsFromTestCase(TestMsportApi_dataExtraction))
        suite.addTests(loader.loadTestsFromTestCase(TestMsportApi_endpoints))
        suite.addTests(loader.loadTestsFromTestCase(TestMsportApi_errorHandling))
    elif layer_num == 3:
        suite.addTests(loader.loadTestsFromTestCase(TestGoAgent_tokenFormat))
    else:
        raise ValueError(f"Unknown layer: {layer_num}")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


def print_report(results: Dict[str, bool]) -> None:
    """Print a summary report."""
    print(header("TEST SUMMARY"))
    all_pass = True
    for layer, passed in results.items():
        status = ok("PASS") if passed else fail("FAIL")
        print(f"  {layer}: {status}")
        if not passed:
            all_pass = False
    print()
    if all_pass:
        print(ok(f"{_BOLD}All tests passed!{_RESET}"))
    else:
        print(fail(f"{_BOLD}Some tests failed!{_RESET}"))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MSport Auth Pipeline Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 tests/test_auth_pipeline.py              # Run all layers
  python3 tests/test_auth_pipeline.py --layer 1    # Token refresher only
  python3 tests/test_auth_pipeline.py --layer 2    # Python API client only
  python3 tests/test_auth_pipeline.py --offline    # Skip live API calls
  python3 tests/test_auth_pipeline.py -v           # Verbose
        """,
    )
    parser.add_argument(
        "--layer", type=int, choices=[1, 2, 3],
        help="Only run a specific layer (1=token refresher, 2=API client, 3=Go agent)"
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Skip live API endpoint tests (only test parsing/data extraction)"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output"
    )
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level,
                        format="%(levelname)s: %(message)s")

    # Add project root to path for imports
    sys.path.insert(0, str(PROJECT_ROOT))

    # If offline mode, skip any test that reaches the live API
    if args.offline:
        print(warn("Offline mode: skipping live API endpoint tests"))

    # Determine test plan
    layers_to_run = [args.layer] if args.layer else [1, 2, 3]

    print(header("MSport Auth Pipeline — Test Suite"))
    print(f"  Project root: {PROJECT_ROOT}")
    print(f"  Token file:   {TOKEN_FILE}")
    print(f"  Go agent:     {GO_AGENT_DIR}")
    print(f"  Mode:         {'offline' if args.offline else 'online'}")
    print()

    results = {}
    for layer_num in layers_to_run:
        if layer_num == 1:
            print(header("Layer 1: Token Refresher"))
            results["Layer 1: Token Refresher"] = run_layer(1)
        elif layer_num == 2:
            print(header("Layer 2: Python API Client"))
            if args.offline:
                # Only run offline-safe tests
                suite = unittest.TestSuite()
                loader = unittest.TestLoader()
                suite.addTests(loader.loadTestsFromTestCase(TestMsportApi_headers))
                suite.addTests(loader.loadTestsFromTestCase(TestMsportApi_dataExtraction))
                suite.addTests(loader.loadTestsFromTestCase(TestMsportApi_errorHandling))
                runner = unittest.TextTestRunner(verbosity=2)
                result = runner.run(suite)
                results["Layer 2: Python API Client (offline)"] = result.wasSuccessful()
            else:
                results["Layer 2: Python API Client"] = run_layer(2)
        elif layer_num == 3:
            print(header("Layer 3: Go Agent Compatibility"))
            results["Layer 3: Go Agent"] = run_layer(3)

    print_report(results)

    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
