from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class BlockedByRobots(Exception):
    pass


class Fetcher:
    """Polite HTTP client: per-request delay, retries with backoff, robots.txt."""

    def __init__(self, user_agent: str, delay: float = 1.0, timeout: float = 20.0,
                 respect_robots: bool = True, retries: int = 3, client: httpx.Client | None = None):
        self.delay = delay
        self.retries = retries
        self.respect_robots = respect_robots
        self.user_agent = user_agent
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last = 0.0

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.client.get(f"{origin}/robots.txt")
                # a missing robots.txt means everything is allowed
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                rp.parse([])
            self._robots[origin] = rp
        return self._robots[origin].can_fetch(self.user_agent, url)

    def _wait(self):
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.monotonic()

    def get(self, url: str) -> str:
        if not self._allowed(url):
            raise BlockedByRobots(url)
        for attempt in range(1, self.retries + 1):
            self._wait()
            try:
                r = self.client.get(url)
                if r.status_code in RETRY_STATUS and attempt < self.retries:
                    wait = float(r.headers.get("Retry-After", 2 ** attempt))
                    log.warning("%s -> %s, retrying in %.0fs", url, r.status_code, wait)
                    time.sleep(min(wait, 60))
                    continue
                r.raise_for_status()
                return r.text
            except httpx.TransportError as e:
                if attempt == self.retries:
                    raise
                log.warning("%s -> %s, retrying", url, e)
                time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    def close(self):
        self.client.close()


class BrowserFetcher:
    """Same interface, but renders JavaScript with a headless Chromium."""

    def __init__(self, user_agent: str, delay: float = 1.0, timeout: float = 20.0, **_):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise SystemExit("render_js needs: pip install 'price-watch[js]' && playwright install chromium") from e
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page(user_agent=user_agent)
        self._page.set_default_timeout(timeout * 1000)
        self.delay = delay

    def get(self, url: str) -> str:
        time.sleep(self.delay)
        self._page.goto(url, wait_until="networkidle")
        return self._page.content()

    def close(self):
        self._browser.close()
        self._pw.stop()
