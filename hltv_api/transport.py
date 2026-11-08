"""Optional browser transports. Sessions and cookies remain in memory."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .parser import BASE


class TransportError(RuntimeError):
    pass


class CurlTransport:
    def __init__(self):
        try:
            from curl_cffi import requests
        except ImportError:
            raise TransportError('Install the browser extra: pip install ".[browser]"') from None
        self.session = requests.Session(impersonate="chrome")
        self.request_error = requests.exceptions.RequestException

    def fetch(self, path):
        try:
            response = self.session.get(BASE + path, timeout=30)
        except self.request_error:
            raise URLError("Browser HTTP transport failed") from None
        if response.status_code >= 400:
            raise HTTPError(BASE + path, response.status_code, "HLTV request failed", response.headers, None)
        if response.url != BASE + path:
            raise TransportError("Unexpected HLTV redirect")
        if len(response.content) > 5_000_000:
            raise TransportError("Response exceeds five MB")
        return response.text

    def close(self):
        self.session.close()


class FlareSolverrTransport:
    def __init__(self, endpoint, timeout=60):
        parsed = urlparse(endpoint)
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            raise ValueError("FlareSolverr endpoint must be an HTTP localhost origin")
        if not 5 <= timeout <= 300:
            raise ValueError("Browser timeout must be between 5 and 300 seconds")
        self.endpoint = endpoint.rstrip("/") + "/v1"
        self.timeout = timeout
        self.session = None

    def command(self, payload):
        request = Request(self.endpoint, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout + 30) as response:
                raw = response.read(10_000_001)
            if len(raw) > 10_000_000:
                raise TransportError("FlareSolverr response too large")
            result = json.loads(raw)
        except (URLError, TimeoutError, ValueError):
            # Upstream diagnostics may contain cookies; never print them.
            raise TransportError("FlareSolverr connection or response failed") from None
        if not isinstance(result, dict) or result.get("status") != "ok":
            raise TransportError("FlareSolverr could not complete the request")
        return result

    def fetch(self, path):
        if not self.session:
            self.session = self.command({"cmd": "sessions.create"}).get("session")
            if not isinstance(self.session, str) or not self.session:
                raise TransportError("FlareSolverr did not create a session")
        result = self.command({"cmd": "request.get", "url": BASE + path,
                               "session": self.session, "maxTimeout": self.timeout * 1000})
        solution = result.get("solution")
        if not isinstance(solution, dict):
            raise TransportError("FlareSolverr did not return a page")
        status = solution.get("status", 0)
        if status in {401, 403, 429}:
            raise TransportError(f"Browser returned HTTP {status}; collection stopped")
        # Some solver versions report 200 even for blocked HTML. Collector also
        # inspects page content rather than trusting the status alone.
        if solution.get("url") != BASE + path or status != 200:
            raise TransportError("Browser did not reach the requested HLTV page")
        page = solution.get("response")
        if not isinstance(page, str) or not page or len(page.encode()) > 5_000_000:
            raise TransportError("Browser returned an empty or oversized page")
        return page

    def close(self):
        if self.session:
            try:
                self.command({"cmd": "sessions.destroy", "session": self.session})
            finally:
                self.session = None
