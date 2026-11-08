"""Conservative public-page fetching with robots checks and bounded retries."""
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from .parser import BASE, parse_matches


class CollectionError(RuntimeError):
    pass


class Collector:
    def __init__(self, delay=5.0, user_agent="hltv-api/0.1"):
        if delay < 5:
            raise ValueError("Request delay must be at least five seconds")
        self.delay = delay
        self.user_agent = user_agent
        self.last_request = None
        self.robots = None

    def fetch(self, path):
        for attempt in range(3):
            if self.last_request is not None:
                time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            try:
                request = Request(BASE + path, headers={"User-Agent": self.user_agent})
                with urlopen(request, timeout=30) as response:
                    if not response.url.startswith(BASE + "/"):
                        raise CollectionError("Unexpected redirect away from HLTV")
                    body = response.read(5_000_001)
                    if len(body) > 5_000_000:
                        raise CollectionError("Response exceeds five MB")
                    return body.decode("utf-8")
            except HTTPError as exc:
                if exc.code in {401, 403, 429}:
                    raise CollectionError(f"HLTV returned HTTP {exc.code}; collection stopped") from exc
                if exc.code not in {500, 502, 503, 504} or attempt == 2:
                    raise CollectionError(f"HLTV returned HTTP {exc.code}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise CollectionError(f"HLTV request failed: {exc}") from exc
            time.sleep(2 ** attempt)
        raise CollectionError("Request retries exhausted")

    def collect(self, kind):
        if kind not in {"upcoming", "results"}:
            raise ValueError("Unknown collection kind")
        if self.robots is None:
            self.robots = RobotFileParser()
            self.robots.parse(self.fetch("/robots.txt").splitlines())
        path = "/matches" if kind == "upcoming" else "/results"
        if not self.robots.can_fetch(self.user_agent, BASE + path):
            raise CollectionError(f"robots.txt disallows {path} for {self.user_agent}")
        crawl_delay = self.robots.crawl_delay(self.user_agent)
        if crawl_delay:
            self.delay = max(self.delay, crawl_delay)
        return parse_matches(self.fetch(path), kind)
