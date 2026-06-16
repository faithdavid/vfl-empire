#!/usr/bin/env python3
"""
10-minute interactive MSport VFL EPL network capture.

Dual monitoring:
  Layer 1 — Playwright request/response listeners → events_playwright.ndjson
  Layer 2 — CDP Network domain (full headers + bodies) → events_cdp.ndjson

Actively navigates virtual EPL: fixtures, matchdays, event details, results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

CAPTURE_SECONDS = 10 * 60
OUTPUT_BASE = Path("/home/ubuntu/faith-workspace/vfl-empire/network-capture")
MSPORT_VIRTUAL = "https://www.msport.com/ng/web/virtual"
MSPORT_RESULTS = "https://www.msport.com/ng/web/virtual/result"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MAX_BODY = 200 * 1024
API_HINTS = (
    "facts-center",
    "virtual",
    "event",
    "match",
    "season",
    "result",
    "table",
    "standing",
    "odds",
    "fixture",
)


def setup_logger(log_path: Path) -> logging.Logger:
    log = logging.getLogger("vfl_capture_10m")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(fh)
    log.addHandler(sh)
    return log


def is_api_url(url: str) -> bool:
    u = url.lower()
    return any(h in u for h in API_HINTS)


def api_path(url: str) -> str:
    try:
        p = urlparse(url)
        return p.path + (("?" + p.query) if p.query else "")
    except Exception:
        return url


class DualCapture:
    def __init__(self):
        self.out_dir: Path | None = None
        self.log: logging.Logger | None = None
        self.start = time.time()
        self.pw_fh = None
        self.cdp_fh = None
        self.pw_count = 0
        self.cdp_count = 0
        self.api_endpoints: dict[str, int] = {}
        self.page = None
        self.cdp = None
        self._cdp_requests: dict[str, dict] = {}
        self._cdp_responses: dict[str, dict] = {}

    def _write(self, fh, payload: dict, counter_attr: str):
        fh.write(json.dumps(payload, default=str) + "\n")
        setattr(self, counter_attr, getattr(self, counter_attr) + 1)
        url = payload.get("url", "")
        if is_api_url(url):
            key = f"{payload.get('method', 'GET')} {api_path(url)}"
            self.api_endpoints[key] = self.api_endpoints.get(key, 0) + 1

    async def setup_playwright_layer(self):
        async def on_response(response):
            req = response.request
            url = req.url
            body = b""
            try:
                body = await response.body()
                body_txt = body[:MAX_BODY].decode("utf-8", errors="replace")
            except Exception:
                body_txt = ""
            self._write(
                self.pw_fh,
                {
                    "layer": "playwright",
                    "ts": time.time(),
                    "method": req.method,
                    "url": url,
                    "status": response.status,
                    "resource_type": req.resource_type,
                    "request_headers": dict(req.headers),
                    "response_headers": dict(response.headers),
                    "body_preview": body_txt[:MAX_BODY],
                    "body_size": len(body),
                    "body_truncated": len(body) > MAX_BODY,
                },
                "pw_count",
            )

        self.page.on("response", on_response)

    async def setup_cdp_layer(self):
        self.cdp = await self.page.context.new_cdp_session(self.page)
        await self.cdp.send("Network.enable", {"maxTotalBufferSize": 50_000_000})

        def on_request(params):
            rid = params.get("requestId")
            req = params.get("request", {})
            self._cdp_requests[rid] = {
                "method": req.get("method"),
                "url": req.get("url"),
                "ts": time.time(),
                "request_headers": req.get("headers", {}),
                "post_data": (req.get("postData") or "")[:4000],
            }

        def on_response(params):
            rid = params.get("requestId")
            resp = params.get("response", {})
            self._cdp_responses[rid] = {
                "status": resp.get("status"),
                "headers": resp.get("headers", {}),
                "mime_type": resp.get("mimeType"),
            }

        def on_finished(params):
            rid = params.get("requestId")
            base = self._cdp_requests.pop(rid, {})
            resp_meta = self._cdp_responses.pop(rid, {})
            if not base:
                return
            asyncio.create_task(self._cdp_finish(rid, base, resp_meta))

        self.cdp.on("Network.requestWillBeSent", on_request)
        self.cdp.on("Network.responseReceived", on_response)
        self.cdp.on("Network.loadingFinished", on_finished)
        self.log.info("CDP Network layer enabled")

    async def _cdp_finish(self, request_id: str, base: dict, resp_meta: dict):
        url = base.get("url", "")
        status = resp_meta.get("status")
        headers = resp_meta.get("headers", {})
        body_txt = ""
        raw_len = 0
        try:
            resp = await self.cdp.send("Network.getResponseBody", {"requestId": request_id})
            raw = resp.get("body") or ""
            raw_len = len(raw)
            body_txt = raw[:MAX_BODY]
        except Exception:
            body_txt = ""
        self._write(
            self.cdp_fh,
            {
                "layer": "cdp",
                "ts": base.get("ts"),
                "method": base.get("method"),
                "url": url,
                "status": status,
                "request_headers": base.get("request_headers"),
                "post_data": base.get("post_data"),
                "response_headers": headers,
                "body_preview": body_txt[:MAX_BODY],
                "body_size": raw_len,
                "body_truncated": raw_len > MAX_BODY,
            },
            "cdp_count",
        )

    async def dismiss_popups(self):
        for sel in (
            '.virtual-push-dialog .close',
            '[class*="close"]',
            'button:has-text("OK")',
            'button:has-text("Close")',
        ):
            try:
                loc = self.page.locator(sel).first
                if await loc.is_visible(timeout=500):
                    await loc.click(timeout=1000)
                    await asyncio.sleep(0.5)
            except Exception:
                pass

    async def click_matchday_tabs(self):
        tabs = self.page.locator(".match-day-bar >> visible=true")
        count = await tabs.count()
        for i in range(min(count, 6)):
            try:
                tab = tabs.nth(i)
                await tab.click(timeout=3000)
                await asyncio.sleep(2)
                self.log.info("Clicked matchday tab %d/%d", i + 1, count)
            except Exception as e:
                self.log.debug("Matchday tab %d failed: %s", i, e)

    async def click_virtual_events(self):
        events = self.page.locator(".virtual-event")
        count = await events.count()
        limit = min(count, 8)
        for i in range(limit):
            try:
                ev = events.nth(i)
                await ev.scroll_into_view_if_needed(timeout=3000)
                await ev.click(timeout=4000)
                await asyncio.sleep(2.5)
                self.log.info("Opened virtual event %d/%d", i + 1, limit)
                # try expand markets / details inside panel
                for sel in (
                    "text=Statistics",
                    "text=Head to Head",
                    "text=Standings",
                    "text=More",
                    ".m-market-group",
                ):
                    try:
                        loc = self.page.locator(sel).first
                        if await loc.is_visible(timeout=800):
                            await loc.click(timeout=2000)
                            await asyncio.sleep(1)
                    except Exception:
                        pass
                await self.page.go_back(timeout=8000)
                await asyncio.sleep(1.5)
            except Exception as e:
                self.log.debug("Event click %d failed: %s", i, e)
                try:
                    await self.page.goto(MSPORT_VIRTUAL, wait_until="domcontentloaded", timeout=20000)
                except Exception:
                    pass

    async def browse_results_page(self):
        try:
            await self.page.goto(MSPORT_RESULTS, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(3)
            self.log.info("On results page: %s", self.page.url)
            for _ in range(5):
                try:
                    prev = self.page.locator('text=Previous, button:has-text("Prev"), [class*="prev"]').first
                    if await prev.is_visible(timeout=1000):
                        await prev.click(timeout=3000)
                        await asyncio.sleep(2)
                except Exception:
                    break
        except Exception as e:
            self.log.warning("Results page navigation failed: %s", e)

    async def interaction_loop(self, deadline: float):
        cycle = 0
        while time.time() < deadline:
            cycle += 1
            elapsed = time.time() - self.start
            self.log.info(
                "Interaction cycle %d (t=%.0fs) pw=%d cdp=%d apis=%d",
                cycle,
                elapsed,
                self.pw_count,
                self.cdp_count,
                len(self.api_endpoints),
            )
            try:
                if cycle % 3 == 1:
                    await self.page.goto(MSPORT_VIRTUAL, wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(2)
                await self.dismiss_popups()
                await self.click_matchday_tabs()
                await self.click_virtual_events()
                if cycle % 2 == 0:
                    await self.browse_results_page()
                    await self.page.goto(MSPORT_VIRTUAL, wait_until="domcontentloaded", timeout=25000)
                await self.page.evaluate("window.scrollBy(0, 400)")
                await asyncio.sleep(4)
            except Exception as e:
                self.log.warning("Cycle %d error: %s", cycle, e)
                try:
                    await self.page.goto(MSPORT_VIRTUAL, wait_until="domcontentloaded", timeout=25000)
                except Exception:
                    pass
            await asyncio.sleep(8)

    def _open_outputs(self, out_dir: Path):
        self.out_dir = out_dir
        self.log = setup_logger(out_dir / "capture.log")
        self.pw_fh = open(out_dir / "events_playwright.ndjson", "w", encoding="utf-8")
        self.cdp_fh = open(out_dir / "events_cdp.ndjson", "w", encoding="utf-8")

    async def run(self):
        out_dir = OUTPUT_BASE / datetime.now().strftime("%Y-%m-%d_%H%M%S_interactive")
        out_dir.mkdir(parents=True, exist_ok=True)
        self._open_outputs(out_dir)
        self.log.info("Starting 10-minute dual capture → %s", out_dir)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-GB",
                timezone_id="Africa/Lagos",
            )
            self.page = await context.new_page()
            await self.page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => false});"
            )

            await self.setup_playwright_layer()
            await self.page.goto(MSPORT_VIRTUAL, wait_until="domcontentloaded", timeout=30000)
            await self.setup_cdp_layer()
            await asyncio.sleep(3)

            deadline = self.start + CAPTURE_SECONDS
            interact_task = asyncio.create_task(self.interaction_loop(deadline))
            while time.time() < deadline:
                await asyncio.sleep(30)
                self.log.info(
                    "HEARTBEAT t=%.0fs pw=%d cdp=%d unique_api_paths=%d url=%s",
                    time.time() - self.start,
                    self.pw_count,
                    self.cdp_count,
                    len(self.api_endpoints),
                    self.page.url,
                )
            interact_task.cancel()
            try:
                await interact_task
            except asyncio.CancelledError:
                pass

            await browser.close()

        if self.pw_fh:
            self.pw_fh.close()
        if self.cdp_fh:
            self.cdp_fh.close()

        summary = {
            "started_at": datetime.fromtimestamp(self.start, tz=timezone.utc).isoformat(),
            "duration_seconds": CAPTURE_SECONDS,
            "playwright_events": self.pw_count,
            "cdp_events": self.cdp_count,
            "unique_api_endpoints": len(self.api_endpoints),
            "top_api_endpoints": sorted(
                self.api_endpoints.items(), key=lambda x: -x[1]
            )[:80],
        }
        with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        self.log.info("Done. summary=%s", json.dumps(summary, indent=2)[:2000])


if __name__ == "__main__":
    asyncio.run(DualCapture().run())