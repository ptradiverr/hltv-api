import argparse
import json
from pathlib import Path
import sys
from wsgiref.simple_server import make_server

from .api import create_app
from .collector import CollectionError, Collector
from .parser import ParseError, parse_matches
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="HLTV collector and JSON API")
    parser.add_argument("--db", default="hltv.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("--kind", choices=["upcoming", "results"], required=True)
    collect.add_argument("--html", type=Path, help="Import saved HTML without network access")
    collect.add_argument("--delay", type=float, default=5)
    collect.add_argument("--user-agent", default="hltv-api/0.1")
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        store = Store(args.db)
        if args.command == "collect":
            records = (parse_matches(args.html.read_text(encoding="utf-8"), args.kind) if args.html
                       else Collector(args.delay, args.user_agent).collect(args.kind))
            store.save(records)
            print(json.dumps({"saved": len(records), "kind": args.kind}))
        else:
            with make_server(args.host, args.port, create_app(store)) as server:
                print(f"Serving http://{args.host}:{args.port}", flush=True)
                server.serve_forever()
    except (CollectionError, ParseError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
