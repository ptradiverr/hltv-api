import json
from unittest import TestCase
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from hltv_api.collector import Collector, CollectionError
from hltv_api.parser import BASE
from hltv_api.transport import FlareSolverrTransport, TransportError


class BrowserTests(TestCase):
    def test_403_falls_back_once_and_reuses_browser(self):
        collector = Collector(flaresolverr_url="http://localhost:8191")
        with patch("hltv_api.collector.urlopen", side_effect=HTTPError("url", 403, "blocked", {}, None)) as direct, patch.object(collector, "_wait"), patch.object(collector.browser, "fetch", return_value="page") as browser:
            self.assertEqual(collector.fetch("/matches"), "page")
            self.assertEqual(collector.fetch("/results"), "page")
            self.assertEqual(direct.call_count, 1)
            self.assertEqual(browser.call_count, 2)

    def test_429_does_not_launch_browser(self):
        collector = Collector(flaresolverr_url="http://localhost:8191")
        with patch("hltv_api.collector.urlopen", side_effect=HTTPError("url", 429, "limited", {}, None)), patch.object(collector.browser, "fetch") as browser:
            with self.assertRaises(CollectionError):
                collector.fetch("/matches")
            browser.assert_not_called()

    def test_challenge_after_browser_is_failure(self):
        collector = Collector(flaresolverr_url="http://localhost:8191")
        collector.browser_active = True
        with patch.object(collector.browser, "fetch", return_value="Just a moment"), self.assertRaises(CollectionError):
            collector.fetch("/results")

    def test_wrapped_robots_still_denies(self):
        collector = Collector()
        with patch.object(collector, "fetch", return_value="<html><pre>User-agent: *\nDisallow: /results</pre></html>"), self.assertRaises(CollectionError):
            collector.collect("results")

    def test_solver_validates_destination_and_destroys_session(self):
        browser = FlareSolverrTransport("http://localhost:8191")
        with patch.object(browser, "command", side_effect=[
            {"session": "test-session"},
            {"solution": {"url": BASE + "/other", "status": 200, "response": "page"}},
            {"status": "ok"},
        ]) as command:
            with self.assertRaises(TransportError):
                browser.fetch("/results")
            browser.close()
            self.assertEqual(command.call_args.args[0], {"cmd": "sessions.destroy", "session": "test-session"})
            self.assertIsNone(browser.session)

    def test_solver_does_not_leak_upstream_diagnostics(self):
        browser = FlareSolverrTransport("http://localhost:8191")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"status": "error", "message": "private-cookie"}).encode()
        with patch("hltv_api.transport.urlopen", return_value=response):
            with self.assertRaises(TransportError) as error:
                browser.command({"cmd": "sessions.create"})
            self.assertNotIn("private-cookie", str(error.exception))

    def test_remote_solver_is_rejected(self):
        with self.assertRaises(ValueError):
            FlareSolverrTransport("http://example.com:8191")
