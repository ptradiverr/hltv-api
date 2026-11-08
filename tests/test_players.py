import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hltv_api.api import create_app
from hltv_api.collector import Collector, CollectionError
from hltv_api.parser import ParseError
from hltv_api.players import parse_players, parse_player_stats, player_path
from hltv_api.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.hltv.org/stats/players/123/sample"


def fixture(name):
    return (FIXTURES / f"{name}.html").read_text()


class PlayerParserTests(unittest.TestCase):
    def test_listing_identity_and_numeric_values(self):
        player, other = parse_players(fixture("players"))
        self.assertEqual(player["id"], 123)
        self.assertEqual(player["name"], "Sample")
        self.assertEqual(player["country"], "France")
        self.assertEqual(player["teams"], [{"id": 456, "name": "Example Team"}])
        self.assertEqual(player["summary"]["maps"], 1200)
        self.assertEqual(player["summary"]["rounds"], 30000)
        self.assertEqual(player["summary"]["rating"], {"version": "2.0", "value": 1.20})
        self.assertEqual(other["summary"]["kd_difference"], -200)
        self.assertIsNone(other["country"])

    def test_rating_version_comes_from_page(self):
        player = parse_players(fixture("players").replace('ratingDesc">2.0', 'ratingDesc">1.0'))[0]
        self.assertEqual(player["summary"]["rating"]["version"], "1.0")

    def test_profile_keeps_rating_versions_separate(self):
        player = parse_player_stats(fixture("player"), URL)
        self.assertEqual(player["statistics"]["headshot_percentage"], 45.2)
        self.assertEqual(player["statistics"]["kills"], 25000)
        self.assertEqual(player["statistics"]["damage_per_round"], 82.5)
        self.assertEqual(player["statistics"]["ratings"], {"1.0": 1.20, "2.0": 1.30})

    def test_optional_unavailable_stats_are_null(self):
        page = fixture("player").replace("45.2%", "-").replace("82.5", "N/A")
        statistics = parse_player_stats(page, URL)["statistics"]
        self.assertIsNone(statistics["headshot_percentage"])
        self.assertIsNone(statistics["damage_per_round"])

    def test_malformed_or_blocked_listings_fail_atomically(self):
        for page in ("Just a moment", "<table></table>", fixture("players").replace("0.99", "bad"), fixture("players").replace("ratingDesc", "unknown").replace("2.0", "unknown")):
            with self.subTest(page=page), self.assertRaises(ParseError):
                parse_players(page)

    def test_profile_identity_and_metrics_are_validated(self):
        for page in (fixture("player").replace("/player/123/", "/player/999/"), fixture("player").replace("25,000", "bad"), fixture("player").replace("45.2%", "101%"), fixture("player").replace("30,000", "-1")):
            with self.subTest(page=page), self.assertRaises(ParseError):
                parse_player_stats(page, URL)

    def test_listing_refresh_preserves_profile_rating_version(self):
        page = fixture("players").replace('ratingDesc">2.0', 'ratingDesc">3.0')
        self.assertEqual(parse_players(page)[0]["summary"]["rating"]["version"], "3.0")

    def test_player_url_is_fixed_origin_and_unfiltered(self):
        for url in ("https://example.com/stats/players/123/sample", URL + "?startDate=2026-01-01", URL + "#stats", URL.replace("https", "http"), URL.replace("123", "0"), URL.replace("www.hltv.org", "name:password@www.hltv.org")):
            with self.subTest(url=url), self.assertRaises(ValueError):
                player_path(url)


class PlayerStoreApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "data.sqlite3")
        self.app = create_app(self.store)

    def request(self, path, query=""):
        result = []
        body = b"".join(self.app({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query}, lambda code, headers: result.append(code)))
        return result[0], json.loads(body)

    def test_summary_and_details_survive_refresh_in_either_order(self):
        self.store.save_players([parse_player_stats(fixture("player"), URL)])
        self.store.save_players(parse_players(fixture("players")))
        self.store.save_players([parse_player_stats(fixture("player"), URL)])
        self.store.save_players(parse_players(fixture("players")))
        player = self.store.get_player(123)
        self.assertEqual(player["summary"]["rating"]["value"], 1.20)
        self.assertEqual(player["statistics"]["ratings"]["2.0"], 1.30)
        for field in ("collected_at", "summary_collected_at", "statistics_collected_at"):
            self.assertTrue(player[field].endswith("+00:00"))
        self.assertEqual(len(self.store.list_players()), 2)

    def test_search_pagination_and_detail(self):
        self.store.save_players(parse_players(fixture("players")))
        status, response = self.request("/v1/players", "q=sam&limit=1")
        self.assertEqual(status, "200 OK")
        self.assertEqual(response["data"][0]["id"], 123)
        self.assertEqual(self.request("/v1/players", "q=%25")[1]["data"], [])
        self.assertEqual(self.request("/v1/players", "limit=1&offset=1")[1]["data"][0]["id"], 123)
        self.assertEqual(self.request("/v1/players/123")[1]["data"]["name"], "Sample")
        self.assertEqual(self.request("/v1/players/999")[0], "404 Not Found")
        self.assertEqual(self.store.list(), [])

    def test_invalid_api_parameters_are_rejected(self):
        for query in ("limit=0", "limit=501", "offset=-1", "offset=99999999999999999999999", "status=finished", "q=" + "a" * 129):
            with self.subTest(query=query):
                self.assertEqual(self.request("/v1/players", query)[0], "400 Bad Request")

    def test_existing_database_is_upgraded_without_losing_matches(self):
        import sqlite3
        from contextlib import closing
        path = Path(self.tmp.name) / "old.sqlite3"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE matches (id INTEGER PRIMARY KEY, status TEXT, payload TEXT, collected_at TEXT)")
            db.execute("INSERT INTO matches VALUES (1, 'finished', '{}', 'now')")
        upgraded = Store(path)
        self.assertEqual(upgraded.get(1)["collected_at"], "now")
        self.assertEqual(upgraded.list_players(), [])

    def test_multi_record_write_failure_rolls_back_entire_batch(self):
        players = parse_players(fixture("players"))
        players[1].pop("name")
        with self.assertRaises(KeyError):
            self.store.save_players(players)
        self.assertEqual(self.store.list_players(), [])


class PlayerCollectorTests(unittest.TestCase):
    def test_listing_is_parsed_after_robots_check(self):
        collector = Collector()
        with patch.object(collector, "fetch", side_effect=["User-agent: *\nAllow: /", fixture("players")]) as fetch:
            self.assertEqual(len(collector.collect("players")), 2)
            self.assertEqual([c.args[0] for c in fetch.call_args_list], ["/robots.txt", "/stats/players"])

    def test_profile_robots_denial_prevents_fetch(self):
        collector = Collector()
        with patch.object(collector, "fetch", return_value="User-agent: *\nDisallow: /stats/") as fetch:
            with self.assertRaises(CollectionError):
                collector.collect("players", player_url=URL)
            fetch.assert_called_once_with("/robots.txt")

    def test_profile_url_validation_happens_before_requests(self):
        collector = Collector()
        with patch.object(collector, "fetch") as fetch:
            with self.assertRaises(ValueError):
                collector.collect("players", player_url="https://example.com/")
            fetch.assert_not_called()

    def test_profile_fetch_uses_same_robots_and_transport_path(self):
        collector = Collector()
        with patch.object(collector, "fetch", side_effect=["User-agent: *\nAllow: /", fixture("player")]) as fetch:
            player, = collector.collect("players", player_url=URL)
            self.assertEqual(player["id"], 123)
            self.assertEqual(fetch.call_args.args[0], "/stats/players/123/sample")
