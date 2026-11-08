import json
from pathlib import Path
import tempfile
import unittest

from hltv_api.api import create_app
from hltv_api.store import Store


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "api.sqlite3"
        self.store = Store(self.path)
        self.app = create_app(self.store)

    def request(self, path, query="", method="GET"):
        result = []
        response = self.app({"REQUEST_METHOD": method, "PATH_INFO": path,
                             "QUERY_STRING": query}, lambda status, headers: result.append((status, dict(headers))))
        return result[0][0], json.loads(b"".join(response))

    def test_health_and_empty_database(self):
        self.assertEqual(self.request("/health"), ("200 OK", {"status": "ok"}))
        for path in ("/v1/matches", "/v1/players"):
            self.assertEqual(self.request(path)[1]["data"], [])

    def test_match_updates_and_filters(self):
        self.store.save([{"id": 1, "status": "scheduled"}])
        self.store.save([{"id": 1, "status": "finished", "score1": 2, "score2": 1}])
        self.store.save([{"id": 1, "status": "scheduled"}])
        self.assertEqual(self.request("/v1/matches", "status=scheduled")[1]["data"], [])
        self.assertEqual(self.request("/v1/matches/1")[1]["data"]["score1"], 2)
        self.assertEqual(len(self.request("/v1/matches")[1]["data"]), 1)

    def test_players_keep_both_sections_and_freshness(self):
        self.store.save_players([{"id": 1, "name": "Example", "summary": {"maps": 50}}])
        self.store.save_players([{"id": 1, "name": "Example", "statistics": {"kills": 1000}}])
        player = self.request("/v1/players/1")[1]["data"]
        self.assertEqual(player["summary"]["maps"], 50)
        self.assertEqual(player["statistics"]["kills"], 1000)
        for key in ("collected_at", "summary_collected_at", "statistics_collected_at"):
            self.assertTrue(player[key].endswith("+00:00"))

    def test_search_and_pagination(self):
        self.store.save_players([{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}])
        self.assertEqual(self.request("/v1/players", "q=ALP")[1]["data"][0]["id"], 1)
        self.assertEqual(self.request("/v1/players", "limit=1&offset=1")[1]["data"][0]["id"], 2)
        self.assertEqual(self.request("/v1/players", "q=%25")[1]["data"], [])
        self.assertEqual(self.request("/v1/players", "q=%27%20OR%201%3D1--")[1]["data"], [])

    def test_invalid_pagination_is_rejected(self):
        for path in ("/v1/matches", "/v1/players"):
            for query in ("limit=0", "limit=501", "limit=no", "offset=-1", "offset=99999999999999999999999"):
                with self.subTest(path=path, query=query):
                    self.assertEqual(self.request(path, query)[0], "400 Bad Request")

    def test_read_only_http_and_missing_resources(self):
        for path in ("/v1/matches", "/v1/players", "/health"):
            for method in ("POST", "PUT", "DELETE"):
                self.assertEqual(self.request(path, method=method)[0], "405 Method Not Allowed")
        for path in ("/v1/matches/123", "/v1/players/123", "/unknown"):
            self.assertEqual(self.request(path)[0], "404 Not Found")

    def test_records_survive_reopening_database(self):
        self.store.save([{"id": 1, "status": "finished"}])
        self.store.save_players([{"id": 2, "name": "Example"}])
        reopened = Store(self.path)
        self.assertEqual(reopened.get(1)["status"], "finished")
        self.assertEqual(reopened.get_player(2)["name"], "Example")

    def test_invalid_player_batch_rolls_back(self):
        with self.assertRaises(KeyError):
            self.store.save_players([{"id": 1, "name": "Example"}, {"id": 2}])
        self.assertEqual(self.store.list_players(), [])


if __name__ == "__main__":
    unittest.main()
