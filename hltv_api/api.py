"""Read-only WSGI API; network requests never happen in API handlers."""
import json
import re
from urllib.parse import parse_qs


def create_app(store):
    def app(environ, start_response):
        def reply(code, body):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers = [("Content-Type", "application/json; charset=utf-8"),
                       ("Content-Length", str(len(data))), ("Cache-Control", "no-store")]
            if code == "405 Method Not Allowed":
                headers.append(("Allow", "GET"))
            start_response(code, headers)
            return [data]

        if environ.get("REQUEST_METHOD") != "GET":
            return reply("405 Method Not Allowed", {"error": "Use GET"})
        path = environ.get("PATH_INFO", "")
        if path == "/health":
            return reply("200 OK", {"status": "ok"})
        if path in {"/v1/matches", "/v1/players"}:
            query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
            try:
                limit = int(query.get("limit", ["100"])[0])
                offset = int(query.get("offset", ["0"])[0])
                status = query.get("status", [None])[0]
                search = query.get("q", [None])[0]
                if (not 1 <= limit <= 500 or not 0 <= offset <= 9223372036854775807
                        or (path == "/v1/matches" and status not in {None, "scheduled", "finished"})
                        or (path == "/v1/players" and (status is not None or (search is not None and len(search) > 128)))):
                    raise ValueError
            except ValueError:
                return reply("400 Bad Request", {"error": "Invalid query parameters"})
            records = store.list_players(search, limit, offset) if path == "/v1/players" else store.list(status, limit, offset)
            return reply("200 OK", {"data": records, "limit": limit, "offset": offset})
        match = re.fullmatch(r"/v1/matches/(\d{1,18})", path)
        if match:
            record = store.get(int(match[1]))
            if record:
                return reply("200 OK", {"data": record})
        player = re.fullmatch(r"/v1/players/(\d{1,18})", path)
        if player:
            record = store.get_player(int(player[1]))
            if record:
                return reply("200 OK", {"data": record})
        return reply("404 Not Found", {"error": "Not found"})
    return app
