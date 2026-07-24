"""
Polite HTTP fetching layer.

Everything that touches the network goes through Fetcher. It handles the four
things that separate a working scraper from one that gets IP-banned in a minute:

  1. robots.txt compliance (per-domain, cached)
  2. per-domain rate limiting, including Crawl-delay if the site declares one
  3. on-disk response caching, so re-running during development doesn't re-hit
     the server (this matters more than people expect - most of the load a
     careless scraper generates is the same page fetched 200 times while you
     debug your selectors)
  4. exponential backoff on 429 / 5xx

Default behaviour obeys robots.txt, mirroring Scrapy's ROBOTSTXT_OBEY.
"""

from __future__ import annotations

import hashlib
import logging
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)


class RobotsDisallowed(Exception):
    """Raised when robots.txt forbids fetching a URL."""


class FetchError(Exception):
    """Raised when a URL could not be fetched after retries."""


@dataclass
class Fetcher:
    user_agent: str
    cache_dir: Path = Path(".cache")
    min_delay: float = 2.0          # seconds between requests to the same host
    timeout: float = 20.0
    max_retries: int = 3
    respect_robots: bool = True
    cache_ttl: float = 60 * 60 * 6  # 6 hours

    _last_request: dict[str, float] = field(default_factory=dict, init=False)
    _robots: dict[str, urllib.robotparser.RobotFileParser | None] = field(
        default_factory=dict, init=False
    )
    _session: requests.Session = field(default_factory=requests.Session, init=False)

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session.headers.update({"User-Agent": self.user_agent})

    # ------------------------------------------------------------------
    # robots.txt
    # ------------------------------------------------------------------
    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlparse(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host in self._robots:
            return self._robots[host]

        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{host}/robots.txt")
        try:
            # Deliberately a bare request: robots.txt itself is never gated by
            # robots.txt, and routing it through self.get() would recurse.
            resp = self._session.get(f"{host}/robots.txt", timeout=self.timeout)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            else:
                # No robots.txt served - conventionally means "no restrictions".
                parser.parse([])
        except requests.RequestException as exc:
            log.warning("could not read robots.txt for %s (%s); assuming allowed", host, exc)
            parser.parse([])

        self._robots[host] = parser
        return parser

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parser = self._robots_for(url)
        return parser is None or parser.can_fetch(self.user_agent, url)

    def _crawl_delay(self, url: str) -> float:
        parser = self._robots_for(url)
        if parser is None:
            return self.min_delay
        try:
            declared = parser.crawl_delay(self.user_agent)
        except Exception:
            declared = None
        return max(self.min_delay, float(declared)) if declared else self.min_delay

    # ------------------------------------------------------------------
    # cache
    # ------------------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".html")

    def _cached(self, url: str) -> str | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.cache_ttl:
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    def get(self, url: str, *, use_cache: bool = True) -> str:
        """Fetch a URL as text. Raises RobotsDisallowed or FetchError."""
        if use_cache:
            hit = self._cached(url)
            if hit is not None:
                log.debug("cache hit %s", url)
                return hit

        if not self.allowed(url):
            raise RobotsDisallowed(
                f"robots.txt at {urlparse(url).netloc} disallows {self.user_agent} on {url}"
            )

        host = urlparse(url).netloc
        delay = self._crawl_delay(url)
        elapsed = time.time() - self._last_request.get(host, 0.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
                self._last_request[host] = time.time()

                if resp.status_code == 200:
                    self._cache_path(url).write_text(resp.text, encoding="utf-8")
                    return resp.text

                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                    log.warning("%s on %s - backing off %.1fs", resp.status_code, url, wait)
                    time.sleep(wait)
                    last_exc = FetchError(f"HTTP {resp.status_code}")
                    continue

                if resp.status_code in (401, 403):
                    raise FetchError(
                        f"HTTP {resp.status_code} on {url}. This usually means bot "
                        f"protection (Cloudflare/PerimeterX/Akamai), not a bad URL. "
                        f"No amount of retrying fixes it - the site does not want "
                        f"automated clients. Use their API if they have one."
                    )

                raise FetchError(f"HTTP {resp.status_code} on {url}")

            except requests.RequestException as exc:
                last_exc = exc
                log.warning("request failed (attempt %d/%d): %s", attempt, self.max_retries, exc)
                time.sleep(2 ** attempt)

        raise FetchError(f"gave up on {url}: {last_exc}")
