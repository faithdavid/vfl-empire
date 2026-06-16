#!/usr/bin/env python3
"""
msport_network_capture_30min.py — Robust 30-minute MSport network capture.

Dual-layer capture:
  Layer 1 – Playwright native request/response event listeners (streaming .ndjson)
  Layer 2 – Requestly SDK SessionRecorder (structured periodic dumps + final HAR)

Output per run (timestamped directory):
  index.json              — Run metadata
  events.ndjson           — Streaming Playwright events
  requestly_session.json  — Final Requestly session dump
  network.har             — HAR 1.2 format
  capture.log             — Runtime log

Cron schedule: hourly at :00 (0 * * * *) → captures for 30 min, cooldown 30 min.
"""

import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────
SDK_PATH = "/tmp/node_modules/@requestly/web-sdk/dist/requestly-web-sdk.min.js"
MSPORT_URL = "https://www.msport.com/ng/web/virtual"
CAPTURE_DURATION_SECONDS = 30 * 60  # 30 minutes
HEALTH_CHECK_INTERVAL = 30  # seconds
HEARTBEAT_INTERVAL = 120  # seconds
FLUSH_INTERVAL = 120  # seconds — flush ndjson buffer
REQUESTLY_PULL_INTERVAL = 120  # seconds — pull events from Requestly
MAX_RETRIES_NAVIGATION = 3
MAX_RETRIES_CRASH = 2
OUTPUT_BASE_DIR = Path("/home/ubuntu/faith-workspace/vfl-empire/network-capture")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
MAX_RESPONSE_BODY_BYTES = 100 * 1024  # 100 KB
CLEANUP_MAX_AGE_HOURS = 72
HAR_CREATOR = {
    "name": "MSport Network Capture Script",
    "version": "1.0.0",
}


# ──────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────
logger = logging.getLogger("msport_capture")
logger.setLevel(logging.DEBUG)


def setup_logging(log_path: Path):
    """Configure dual logging: stdout INFO + file DEBUG."""
    logger.handlers.clear()

    # File handler
    fh = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(ch)


# ──────────────────────────────────────────────────────────────────────
# Self-cleanup: remove directories older than 72 hours
# ──────────────────────────────────────────────────────────────────────
def cleanup_old_captures():
    """Remove capture directories older than CLEANUP_MAX_AGE_HOURS."""
    if not OUTPUT_BASE_DIR.exists():
        return
    now = time.time()
    cutoff = now - (CLEANUP_MAX_AGE_HOURS * 3600)
    removed = 0
    for entry in OUTPUT_BASE_DIR.iterdir():
        if entry.is_dir():
            try:
                # Parse timestamp from directory name YYYY-MM-DD_HHMMSS
                dir_time = datetime.strptime(entry.name, "%Y-%m-%d_%H%M%S")
                if dir_time.timestamp() < cutoff:
                    shutil.rmtree(entry)
                    removed += 1
            except (ValueError, OSError):
                # Not a timestamp directory or can't remove — skip
                pass
    if removed:
        logger.info("Cleaned up %d old capture directories (>%dh)", removed, CLEANUP_MAX_AGE_HOURS)


# ──────────────────────────────────────────────────────────────────────
# HAR conversion (inlined from har_converter.py)
# ──────────────────────────────────────────────────────────────────────
def build_har(rq_session, page_url="about:blank"):
    """Convert an RQSession dict into a HAR 1.2 dict."""
    events = rq_session.get("events", {})
    network_events = events.get("network", [])
    attributes = rq_session.get("attributes", {})

    # Determine start time
    start_time = attributes.get("startTime", 0)
    duration = attributes.get("duration", 0)

    if isinstance(start_time, (int, float)) and start_time > 0:
        started_dt = datetime.fromtimestamp(start_time / 1000, tz=timezone.utc)
    else:
        started_dt = datetime.now(timezone.utc)
    started_date_time = started_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(started_dt.microsecond / 1000):03d}Z"

    entries = []
    for ev in network_events:
        method = ev.get("method", "GET")
        url = ev.get("url", "")
        status = ev.get("status", 0)
        status_text = ev.get("statusText", "")
        content_type = ev.get("contentType", "")
        response_time = ev.get("responseTime", 0)
        timestamp = ev.get("timestamp", 0)
        request_data = ev.get("requestData", {})
        response_data = ev.get("response", "")

        # Request headers
        request_headers = []
        if isinstance(request_data, dict):
            headers = request_data.get("headers", {})
            if isinstance(headers, dict):
                for k, v in headers.items():
                    request_headers.append({"name": str(k), "value": str(v)})

        # Response headers
        response_headers = []
        if isinstance(response_data, dict):
            resp_headers = response_data.get("headers", {})
            if isinstance(resp_headers, dict):
                for k, v in resp_headers.items():
                    response_headers.append({"name": str(k), "value": str(v)})

        # Response body text
        response_body_text = ""
        if isinstance(response_data, str):
            response_body_text = response_data
        elif isinstance(response_data, dict):
            response_body_text = json.dumps(response_data.get("body", response_data))

        # Cap response body for HAR as well
        if len(response_body_text) > 50000:
            response_body_text = response_body_text[:50000]

        # Request object
        request_obj = {
            "method": method,
            "url": url,
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": request_headers,
            "queryString": [],
            "postData": {},
            "headersSize": -1,
            "bodySize": -1,
        }

        post_body = None
        if isinstance(request_data, dict):
            post_body = request_data.get("body")
        if post_body is None and isinstance(request_data, str):
            post_body = request_data
        if post_body:
            request_obj["postData"] = {
                "mimeType": "application/octet-stream",
                "text": str(post_body)[:10000],
            }

        # Response object
        response_obj = {
            "status": status,
            "statusText": status_text or "",
            "httpVersion": "HTTP/1.1",
            "cookies": [],
            "headers": response_headers,
            "content": {
                "size": len(response_body_text),
                "mimeType": content_type or "application/octet-stream",
                "text": response_body_text,
            },
            "redirectURL": "",
            "headersSize": -1,
            "bodySize": len(response_body_text),
        }

        # Timing
        wait_time = response_time if (timestamp and response_time) else 0
        timings_obj = {
            "blocked": -1,
            "dns": -1,
            "connect": -1,
            "send": 0,
            "wait": wait_time,
            "receive": 0,
            "ssl": -1,
        }

        entry = {
            "startedDateTime": started_date_time,
            "time": wait_time,
            "request": request_obj,
            "response": response_obj,
            "cache": {},
            "timings": timings_obj,
        }
        entries.append(entry)

    har = {
        "log": {
            "version": "1.2",
            "creator": dict(HAR_CREATOR),
            "browser": {
                "name": attributes.get("environment", {})
                          .get("browser", {}).get("name", "Chrome"),
                "version": attributes.get("environment", {})
                             .get("browser", {}).get("version", ""),
            },
            "pages": [
                {
                    "startedDateTime": started_date_time,
                    "id": "page_1",
                    "title": page_url,
                    "pageTimings": {
                        "onContentLoad": -1,
                        "onLoad": duration,
                    },
                }
            ],
            "entries": entries,
        }
    }
    return har


# ──────────────────────────────────────────────────────────────────────
# Capture Engine
# ──────────────────────────────────────────────────────────────────────
class MsportNetworkCapture:
    """Orchestrates the 30-minute dual-layer network capture."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Logging
        self.log_path = output_dir / "capture.log"
        setup_logging(self.log_path)

        # State
        self.start_time = time.time()
        self.end_time: float | None = None
        self.playwright_event_count = 0
        self.requestly_event_count = 0
        self.last_flush_time = time.time()
        self.last_heartbeat_time = time.time()
        self.last_requestly_pull_time = time.time()
        self.recorder_running = False
        self.graceful_shutdown = False

        # Layer 1: streaming ndjson file
        self.events_file_path = output_dir / "events.ndjson"
        self.events_fh = None

        # Layer 2: accumulated Requestly events
        self.requestly_events = []

        # Playwright objects (set during run)
        self.browser = None
        self.context = None
        self.page = None

        # Signal handlers
        self._original_sigint = None
        self._original_sigterm = None

    # ── Signal handling ──────────────────────────────────────────────

    def _handle_signal(self, signum, frame):
        """Handle SIGINT/SIGTERM gracefully."""
        sig_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        logger.warning("Received %s – initiating graceful shutdown...", sig_name)
        self.graceful_shutdown = True

    def _install_signal_handlers(self):
        self._original_sigint = signal.signal(signal.SIGINT, self._handle_signal)
        self._original_sigterm = signal.signal(signal.SIGTERM, self._handle_signal)

    def _restore_signal_handlers(self):
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm:
            signal.signal(signal.SIGTERM, self._original_sigterm)

    # ── File I/O ─────────────────────────────────────────────────────

    def _open_events_file(self):
        """Open the ndjson events file for streaming writes."""
        self.events_fh = open(self.events_file_path, "w", encoding="utf-8", buffering=1)

    def _write_event_line(self, event: dict):
        """Write a single JSON line to the ndjson file and flush."""
        if self.events_fh is None:
            return
        line = json.dumps(event, default=str) + "\n"
        self.events_fh.write(line)
        self.playwright_event_count += 1
        # Flush periodically
        now = time.time()
        if now - self.last_flush_time >= FLUSH_INTERVAL:
            self.events_fh.flush()
            os.fsync(self.events_fh.fileno())
            self.last_flush_time = now

    def _flush_events_file(self):
        """Force flush the events file."""
        if self.events_fh is not None:
            self.events_fh.flush()
            os.fsync(self.events_fh.fileno())

    def _close_events_file(self):
        if self.events_fh is not None:
            self._flush_events_file()
            self.events_fh.close()
            self.events_fh = None

    # ── Playwright Event Listeners (Layer 1) ────────────────────────

    async def _setup_event_listeners(self):
        """Attach request/response event listeners on the page."""

        # Track pending requests to match them with responses
        pending = {}

        async def on_request(request):
            pending[request.url] = {
                "method": request.method,
                "url": request.url,
                "request_headers": dict(request.headers),
                "timestamp": time.time(),
                "resource_type": request.resource_type,
            }

        async def on_response(response):
            req = response.request
            req_info = pending.pop(req.url, {})
            try:
                body = await response.body()
                body_str = body[:MAX_RESPONSE_BODY_BYTES].decode("utf-8", errors="replace")
            except Exception:
                body_str = ""

            event = {
                "type": "network",
                "source": "playwright",
                "timestamp": req_info.get("timestamp", time.time()),
                "method": req_info.get("method", req.method),
                "url": req.url,
                "status_code": response.status,
                "status_text": response.status_text,
                "content_type": response.headers.get("content-type", ""),
                "request_headers": req_info.get("request_headers", {}),
                "response_headers": dict(response.headers),
                "response_body_preview": body_str[:5000],  # smaller in ndjson
                "response_body_size": len(body),
                "resource_type": req_info.get("resource_type", ""),
                "timing": {
                    "response_time_ms": time.time() * 1000
                    - (req_info.get("timestamp", time.time()) * 1000),
                },
            }
            self._write_event_line(event)

        self.page.on("request", on_request)
        self.page.on("response", on_response)
        logger.debug("Playwright event listeners installed")

    # ── Requestly SDK (Layer 2) ─────────────────────────────────────

    async def _inject_requestly(self) -> bool:
        """Inject and start Requestly SessionRecorder. Returns True on success."""
        if not os.path.exists(SDK_PATH):
            logger.warning("Requestly SDK not found at %s — skipping Layer 2", SDK_PATH)
            return False

        try:
            await self.page.add_script_tag(path=SDK_PATH)
            logger.info("Injected Requestly web-sdk")
        except Exception as e:
            logger.warning("Failed to inject Requestly SDK: %s — skipping Layer 2", e)
            return False

        # Verify SDK loaded
        sdk_ok = await self.page.evaluate(
            "typeof window.Requestly !== 'undefined' && "
            "typeof window.Requestly.SessionRecorder !== 'undefined'"
        )
        if not sdk_ok:
            logger.warning("Requestly SDK loaded but SessionRecorder not found — skipping Layer 2")
            return False
        logger.info("Requestly.SessionRecorder is available")

        return True

    async def _start_recorder(self):
        """Start a SessionRecorder. Safe to call even if SDK not loaded."""
        try:
            await self.page.evaluate("""
                (() => {
                    window.__recorder = new Requestly.SessionRecorder({
                        network: true,
                        maxDuration: 1800000
                    });
                    window.__recorder.start();
                })();
            """)
            self.recorder_running = True
            logger.debug("Requestly SessionRecorder started")
        except Exception as e:
            logger.warning("Failed to start Requestly recorder: %s", e)
            self.recorder_running = False

    async def _stop_recorder(self):
        """Stop current recorder."""
        if not self.recorder_running:
            return
        try:
            await self.page.evaluate("""
                (() => {
                    try {
                        if (window.__recorder) {
                            window.__recorder.stop();
                        }
                    } catch(e) {
                        console.error('Recorder stop error:', e);
                    }
                })();
            """)
            self.recorder_running = False
            logger.debug("Requestly SessionRecorder stopped")
        except Exception as e:
            logger.warning("Error stopping Requestly recorder: %s", e)

    async def _pull_requestly_session(self) -> dict | None:
        """Pull the current session from Requestly recorder and return events dict."""
        try:
            result_json = await self.page.evaluate("""
                (() => {
                    try {
                        if (!window.__recorder) return '{}';
                        return JSON.stringify(window.__recorder.getSession());
                    } catch(e) {
                        return JSON.stringify({error: e.message});
                    }
                })();
            """)
            session = json.loads(result_json)
            return session
        except Exception as e:
            logger.warning("Error pulling Requestly session: %s", e)
            return None

    async def _requestly_periodic_pull(self):
        """Pull events from Requestly every REQUESTLY_PULL_INTERVAL seconds."""
        elapsed = time.time() - self.start_time
        logger.info(
            "Requestly periodic pull at t=%.0fs: pulling session data...",
            elapsed,
        )
        session = await self._pull_requestly_session()
        if session and session != {}:
            events = session.get("events", {})
            network_events = events.get("network", [])
            if isinstance(network_events, list):
                self.requestly_events.extend(network_events)
                self.requestly_event_count = len(self.requestly_events)
                logger.info(
                    "Pulled %d Requestly events (total: %d)",
                    len(network_events),
                    self.requestly_event_count,
                )

            # Stop old recorder and start a new one to clear memory
            await self._stop_recorder()
            await self._start_recorder()

    async def _requestly_final_dump(self) -> dict | None:
        """Final pull and stop of Requestly recorder. Returns the full session."""
        session = await self._pull_requestly_session()
        await self._stop_recorder()
        if session and session != {}:
            events = session.get("events", {})
            network_events = events.get("network", [])
            if isinstance(network_events, list):
                self.requestly_events.extend(network_events)
                self.requestly_event_count = len(self.requestly_events)
        else:
            session = {"events": {"network": self.requestly_events}, "attributes": {}}
        return session

    # ── Browser Setup ────────────────────────────────────────────────

    async def _create_browser(self):
        """Launch headless Chromium with stealth configuration."""
        p = self._playwright_context
        self.browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        logger.info("Browser launched")

        self.context = await self.browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="en-GB",
            timezone_id="Africa/Lagos",
            ignore_https_errors=True,
        )

        self.page = await self.context.new_page()

        # Stealth: hide automation indicators
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = { runtime: {} };
            // Override permissions
            const originalQuery = navigator.permissions.query;
            navigator.permissions.query = (params) => (
                params.name === 'notifications'
                    ? Promise.resolve({state: 'denied'})
                    : originalQuery(params)
            );
        """)

        logger.info("Browser context and page created")

    # ── Navigation ───────────────────────────────────────────────────

    async def _navigate_with_retry(self) -> bool:
        """Navigate to target URL with retries. Returns True on success."""
        for attempt in range(1, MAX_RETRIES_NAVIGATION + 1):
            try:
                logger.info(
                    "Navigation attempt %d/%d to %s",
                    attempt, MAX_RETRIES_NAVIGATION, MSPORT_URL,
                )
                await self.page.goto(MSPORT_URL, wait_until="load", timeout=30000)
                # Optional networkidle wait — wrap in try/except as the
                # site may have persistent streaming connections
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    logger.debug("networkidle wait timeout (non-critical)")
                logger.info("Navigation OK — URL: %s", self.page.url)
                return True
            except Exception as e:
                logger.warning(
                    "Navigation attempt %d failed: %s", attempt, e,
                )
                if attempt < MAX_RETRIES_NAVIGATION:
                    await asyncio.sleep(10)
        return False

    async def _reload_with_retry(self) -> bool:
        """Reload the current page with retries. Returns True on success."""
        for attempt in range(1, MAX_RETRIES_CRASH + 1):
            try:
                logger.info("Reload attempt %d/%d", attempt, MAX_RETRIES_CRASH)
                await self.page.reload(wait_until="load", timeout=30000)
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    logger.debug("networkidle wait timeout (non-critical)")
                logger.info("Reload OK — URL: %s", self.page.url)
                return True
            except Exception as e:
                logger.warning("Reload attempt %d failed: %s", attempt, e)
                if attempt < MAX_RETRIES_CRASH:
                    await asyncio.sleep(15)
        return False

    # ── Health Checks ────────────────────────────────────────────────

    async def _health_check(self) -> bool:
        """Check if the page is still responsive. Returns True if healthy."""
        try:
            await self.page.evaluate("1")
            return True
        except Exception as e:
            logger.warning("Health check failed: %s", e)
            return False

    # ── Heartbeat ────────────────────────────────────────────────────

    async def _heartbeat(self):
        """Log a heartbeat summary."""
        elapsed = time.time() - self.start_time
        try:
            current_url = self.page.url if self.page else "N/A"
        except Exception:
            current_url = "N/A"
        logger.info(
            "HEARTBEAT — elapsed=%.0fs events=%d requestly=%d url=%s",
            elapsed,
            self.playwright_event_count,
            self.requestly_event_count,
            current_url,
        )

    # ── Core Capture Loop ────────────────────────────────────────────

    async def run(self):
        """Main capture orchestration."""
        self._install_signal_handlers()
        self._open_events_file()

        try:
            # Start Playwright
            async with async_playwright() as p:
                self._playwright_context = p
                await self._create_browser()

                # Navigate with retry
                if not await self._navigate_with_retry():
                    logger.error("Failed to navigate after %d attempts — aborting", MAX_RETRIES_NAVIGATION)
                    await self._finalize(status="navigation_failed")
                    return

                # Setup event listeners (Layer 1)
                await self._setup_event_listeners()

                # Inject Requestly SDK (Layer 2)
                requestly_available = await self._inject_requestly()
                if requestly_available:
                    await self._start_recorder()

                # 30-minute capture loop
                deadline = self.start_time + CAPTURE_DURATION_SECONDS
                while time.time() < deadline and not self.graceful_shutdown:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break

                    # Wait for next interval (min of all intervals)
                    next_wake = min(
                        HEALTH_CHECK_INTERVAL,
                        HEARTBEAT_INTERVAL,
                        REQUESTLY_PULL_INTERVAL,
                    )
                    await asyncio.sleep(min(next_wake, remaining))

                    # Health check
                    if not await self._health_check():
                        logger.warning("Page unresponsive — attempting reload")
                        if await self._reload_with_retry():
                            # Re-inject listeners and Requestly after reload
                            await self._setup_event_listeners()
                            if requestly_available:
                                await self._start_recorder()
                        else:
                            logger.error("Page crash recovery failed — saving partial data and exiting")
                            break

                    # Periodic heartbeat
                    if time.time() - self.last_heartbeat_time >= HEARTBEAT_INTERVAL:
                        await self._heartbeat()
                        self.last_heartbeat_time = time.time()

                    # Periodic Requestly pull
                    if (
                        requestly_available
                        and time.time() - self.last_requestly_pull_time >= REQUESTLY_PULL_INTERVAL
                    ):
                        await self._requestly_periodic_pull()
                        self.last_requestly_pull_time = time.time()

                # Capture complete — finalize
                logger.info("Capture complete (%.0fs elapsed)", time.time() - self.start_time)

                # Final Requestly dump
                rq_session = None
                if requestly_available:
                    rq_session = await self._requestly_final_dump()

                await self._finalize(
                    status="completed",
                    rq_session=rq_session,
                )

        except asyncio.CancelledError:
            logger.warning("Capture cancelled")
            await self._finalize(status="cancelled")
        except Exception as e:
            logger.error("Unhandled exception: %s", e, exc_info=True)
            await self._finalize(status="error")
        finally:
            self._restore_signal_handlers()

    async def _finalize(self, status: str = "completed", rq_session: dict | None = None):
        """Clean shutdown: close browser, flush files, write metadata."""
        self.end_time = time.time()
        duration = self.end_time - self.start_time
        logger.info("Finalizing capture (status=%s, duration=%.0fs)", status, duration)

        # Final flush of events file
        self._flush_events_file()

        # Close browser
        if self.browser:
            try:
                await self.browser.close()
                logger.debug("Browser closed")
            except Exception:
                pass

        # Save Requestly session if available
        rq_path = self.output_dir / "requestly_session.json"
        if rq_session and rq_session != {}:
            try:
                with open(rq_path, "w", encoding="utf-8") as f:
                    json.dump(rq_session, f, indent=2, default=str)
                    f.flush()
                    os.fsync(f.fileno())
                logger.info("Requestly session saved (%d events)", self.requestly_event_count)
            except Exception as e:
                logger.warning("Failed to save Requestly session: %s", e)
        elif self.requestly_events:
            # Have accumulated events from periodic pulls but no final session
            fallback_session = {
                "attributes": {
                    "url": MSPORT_URL,
                    "startTime": self.start_time * 1000,
                    "duration": duration * 1000,
                },
                "events": {"network": self.requestly_events},
            }
            try:
                with open(rq_path, "w", encoding="utf-8") as f:
                    json.dump(fallback_session, f, indent=2, default=str)
                    f.flush()
                    os.fsync(f.fileno())
                logger.info("Requestly fallback session saved (%d events)", self.requestly_event_count)
            except Exception as e:
                logger.warning("Failed to save fallback session: %s", e)

        # Build and save HAR
        har_path = self.output_dir / "network.har"
        try:
            # Determine which session to use for HAR
            if not rq_session and self.requestly_events:
                rq_session = fallback_session
            if rq_session:
                har = build_har(rq_session, page_url=MSPORT_URL)
                with open(har_path, "w", encoding="utf-8") as f:
                    json.dump(har, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                har_count = len(har["log"]["entries"])
                logger.info("HAR saved (%d entries)", har_count)
        except Exception as e:
            logger.warning("Failed to save HAR: %s", e)

        # Close events file
        self._close_events_file()

        # Write index.json
        index_path = self.output_dir / "index.json"
        try:
            index = {
                "start_time": datetime.fromtimestamp(self.start_time, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S." + f"{int(self.start_time % 1 * 1000):03d}Z"
                ),
                "end_time": datetime.fromtimestamp(self.end_time, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S." + f"{int(self.end_time % 1 * 1000):03d}Z"
                ),
                "duration_seconds": round(duration, 1),
                "target_url": MSPORT_URL,
                "playwright_event_count": self.playwright_event_count,
                "requestly_event_count": self.requestly_event_count,
                "output_dir": str(self.output_dir),
                "status": status,
            }
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            logger.info("Index metadata written: %s", index_path)
        except Exception as e:
            logger.warning("Failed to write index.json: %s", e)

        logger.info("Capture finalized. Output: %s", self.output_dir)


# ──────────────────────────────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────────────────────────────
async def main():
    """Application entry point."""
    # Ensure output base directory exists
    OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)

    # Self-cleanup old captures
    cleanup_old_captures()

    # Create timestamped output directory
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_dir = OUTPUT_BASE_DIR / timestamp

    # Run capture
    capture = MsportNetworkCapture(output_dir)
    await capture.run()

    # Exit with appropriate code
    if capture.graceful_shutdown:
        sys.exit(0)
    elif hasattr(capture, "playwright_event_count") and capture.playwright_event_count == 0:
        logger.error("No events captured — exiting with error")
        sys.exit(1)
    else:
        logger.info("Successfully captured %d Playwright events and %d Requestly events",
                     capture.playwright_event_count, capture.requestly_event_count)
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
