"""Conservative public-page fetching with robots checks and bounded retries."""
import time
import random
import re
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from .parser import BASE, parse_matches
from .players import parse_players, parse_player_stats, player_path
from .transport import CurlTransport, FlareSolverrTransport, TransportError


class CollectionError(RuntimeError):
    pass


class Collector:
    def __init__(self, delay=8.0, user_agent="hltv-api/0.1", *, backend="stdlib",
                 flaresolverr_url=None, challenge_timeout=60):
        if delay < 5:
            raise ValueError("Request delay must be at least five seconds")
        self.delay = delay
        self.user_agent = user_agent
        self.last_request = None
        self.robots = None
        if backend not in {"stdlib", "curl"}:
            raise ValueError("Unknown HTTP backend")
        self.browser = (FlareSolverrTransport(flaresolverr_url, challenge_timeout)
                        if flaresolverr_url else None)
        self.transport = CurlTransport() if backend == "curl" else None
        self.browser_active = False

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self.transport:
                self.transport.close()

    def _wait(self):
        if self.last_request is not None:
            time.sleep(max(0, self.delay + random.uniform(0, 6)
                           - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()

    @staticmethod
    def _blocked(page):
        return bool(re.search(r"just a moment|verify you are human|cf-chl-|access denied|"
                              r"too many requests|error\s*1015", page, re.I))

    def _render(self, path):
        self._wait()
        self.browser_active = True
        page = self.browser.fetch(path)
        if self._blocked(page):
            raise CollectionError("Browser still blocked; collection stopped")
        return page

    def fetch(self, path):
        for attempt in range(3):
            try:
                if self.browser_active:
                    return self._render(path)
                self._wait()
                if self.transport:
                    page = self.transport.fetch(path)
                else:
                    request = Request(BASE + path, headers={"User-Agent": self.user_agent})
                    with urlopen(request, timeout=30) as response:
                        if response.url != BASE + path:
                            raise CollectionError("Unexpected HLTV redirect")
                        body = response.read(5_000_001)
                        if len(body) > 5_000_000:
                            raise CollectionError("Response exceeds five MB")
                        page = body.decode("utf-8")
                if self._blocked(page):
                    if self.browser and not re.search(r"too many requests|error\s*1015", page, re.I):
                        return self._render(path)
                    raise CollectionError("HLTV returned a blocked page; collection stopped")
                return page
            except HTTPError as exc:
                exc.close()
                if exc.code == 403 and self.browser:
                    try:
                        return self._render(path)
                    except TransportError as error:
                        raise CollectionError(str(error)) from None
                if exc.code in {401, 403, 429}:
                    raise CollectionError(f"HLTV returned HTTP {exc.code}; collection stopped") from exc
                if exc.code not in {500, 502, 503, 504} or attempt == 2:
                    raise CollectionError(f"HLTV returned HTTP {exc.code}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise CollectionError(f"HLTV request failed: {exc}") from exc
            except TransportError as exc:
                raise CollectionError(str(exc)) from None
            time.sleep(2 ** attempt)
        raise CollectionError("Request retries exhausted")

    def fetch_allowed(self, path):
        if self.robots is None:
            self.robots = RobotFileParser()
            robots_text = self.fetch("/robots.txt")
            # Chrome wraps plain-text documents in <pre> when rendering them.
            wrapped = re.search(r"<pre\b[^>]*>(.*?)</pre>", robots_text, re.I | re.S)
            if wrapped:
                robots_text = unescape(wrapped[1])
            if "<html" in robots_text.lower() or "<body" in robots_text.lower():
                raise CollectionError("robots.txt returned unexpected HTML")
            self.robots.parse(robots_text.splitlines())
        if not self.robots.can_fetch(self.user_agent, BASE + path):
            raise CollectionError(f"robots.txt disallows {path} for {self.user_agent}")
        crawl_delay = self.robots.crawl_delay(self.user_agent)
        if crawl_delay:
            self.delay = max(self.delay, crawl_delay)
        return self.fetch(path)

    def collect(self, kind, *, player_url=None):
        if kind not in {"upcoming", "results", "players"}:
            raise ValueError("Unknown collection kind")
        if player_url is not None:
            if kind != "players":
                raise ValueError("Player URLs require kind players")
            path, _ = player_path(player_url)
            return [parse_player_stats(self.fetch_allowed(path), player_url)]
        path = {"upcoming": "/matches", "results": "/results", "players": "/stats/players"}[kind]
        page = self.fetch_allowed(path)
        return parse_players(page) if kind == "players" else parse_matches(page, kind)
