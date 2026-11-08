"""Local development server for the public API package."""
import argparse
from wsgiref.simple_server import make_server

from .api import create_app
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Serve stored match and player data")
    parser.add_argument("--db", default="hltv.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with make_server(args.host, args.port, create_app(Store(args.db))) as server:
        print(f"Serving http://{args.host}:{args.port}", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
