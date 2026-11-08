import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from hltv_api.api import create_app
from hltv_api.collector import CollectionError, Collector
from hltv_api.parser import ParseError, parse_matches
from hltv_api.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(kind):
    return (FIXTURES / f"{kind}.html").read_text()


class ParserTests(unittest.TestCase):
    def test_result_identity_teams_score_and_entities(self):
        record, = parse_matches(fixture("results"), "results")
        self.assertEqual(record["id"], 2380001)
        self.assertEqual((record["team1"], record["team2"]), ("Team A", "Team B"))
        self.assertEqual((record["score1"], record["score2"]), (2, 1))
        self.assertEqual(record["event"], "Test & Event")

    def test_upcoming_timestamp_is_utc(self):
        record, = parse_matches(fixture("upcoming"), "upcoming")
        self.assertEqual(record["starts_at"], "2025-01-01T00:00:00+00:00")
        self.assertIsNone(record["score1"])

    def test_unknown_teams_supported(self):
        page = '<div class="upcomingMatch"><a href="/matches/123/tbd">TBD</a></div>'
        self.assertIsNone(parse_matches(page, "upcoming")[0]["team1"])

    def test_current_upcoming_layout_excludes_live_and_deduplicates(self):
        row = '''<div class="match-wrapper" live="false">
          <a href="/matches/123/test"><div class="match-time" data-unix="1735689600000"></div></a>
          <div class="match-event" data-event-headline="Event">Event Quarterfinal</div>
          <div class="match-teamname">Team A</div><div class="match-teamname">Team B</div>
          </div>'''
        records = parse_matches(row + row + row.replace('live="false"', 'live="true"').replace('/123/', '/456/'), "upcoming")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event"], "Event")
        self.assertEqual(records[0]["team2"], "Team B")

    def test_broken_or_blocked_pages_fail(self):
        for page in ("<html>Just a moment</html>", "<html>empty</html>",
                     fixture("results").replace("result-score", "changed-score"),
                     fixture("results").replace("/matches/2380001/", "/other/2380001/")):
            with self.subTest(page=page), self.assertRaises(ParseError):
                parse_matches(page, "results")


class StoreAndApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name) / "test.sqlite3")
        self.app = create_app(self.store)

    def request(self, path, query="", method="GET"):
        status = []
        body = b"".join(self.app({"PATH_INFO": path, "QUERY_STRING": query,
                                  "REQUEST_METHOD": method}, lambda code, headers: status.append(code)))
        return status[0], json.loads(body)

    def test_upsert_and_no_finished_regression(self):
        self.store.save(parse_matches(fixture("upcoming"), "upcoming"))
        self.store.save(parse_matches(fixture("results"), "results"))
        self.store.save(parse_matches(fixture("upcoming"), "upcoming"))
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.get(2380001)["status"], "finished")
        self.assertTrue(self.store.get(2380001)["collected_at"].endswith("+00:00"))

    def test_api_filters_and_validation(self):
        self.store.save(parse_matches(fixture("results"), "results"))
        self.assertEqual(self.request("/v1/matches", "status=scheduled")[1]["data"], [])
        self.assertEqual(self.request("/v1/matches/2380001")[1]["data"]["score1"], 2)
        for query in ("limit=0", "limit=501", "offset=-1", "limit=bad", "status=bad"):
            self.assertTrue(self.request("/v1/matches", query)[0].startswith("400"))
        self.assertTrue(self.request("/v1/matches/999")[0].startswith("404"))
        self.assertTrue(self.request("/v1/matches", method="POST")[0].startswith("405"))


class CollectorTests(unittest.TestCase):
    def test_robots_denial_prevents_listing_request(self):
        collector = Collector()
        with patch.object(collector, "fetch", return_value="User-agent: *\nDisallow: /results") as fetch:
            with self.assertRaises(CollectionError):
                collector.collect("results")
            fetch.assert_called_once_with("/robots.txt")

    def test_robots_crawl_delay_is_respected(self):
        collector = Collector()
        with patch.object(collector, "fetch", side_effect=["User-agent: *\nCrawl-delay: 20\nAllow: /", fixture("results")]):
            self.assertEqual(len(collector.collect("results")), 1)
        self.assertEqual(collector.delay, 20)

    def test_blocked_requests_are_not_retried(self):
        for code in (403, 429):
            with patch("hltv_api.collector.urlopen", side_effect=HTTPError("url", code, "blocked", {}, None)) as fetch:
                with self.assertRaises(CollectionError):
                    Collector().fetch("/results")
                self.assertEqual(fetch.call_count, 1)

    def test_server_errors_have_bounded_retries(self):
        with patch("hltv_api.collector.urlopen", side_effect=HTTPError("url", 503, "unavailable", {}, None)) as fetch, patch("hltv_api.collector.time.sleep"):
            with self.assertRaises(CollectionError):
                Collector().fetch("/results")
            self.assertEqual(fetch.call_count, 3)


if __name__ == "__main__":
    unittest.main()
