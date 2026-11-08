# HLTV API

Independent Python collector and read-only JSON API for HLTV upcoming matches
and recent results. Uses Python 3.11+ and the standard library at runtime.
SQLite persists records between collection runs.
## Status

The standard HTTP client received HTTP 403 during development. With the optional
`curl_cffi` Chrome transport, a live smoke test on November 8, 2026 (UTC)
successfully collected and stored 100 results. A fetched live matches page
also parsed and stored 254 upcoming matches after updating the parser for
HLTV's current layout (live matches excluded). This is evidence for that run
and network connection, not a guarantee of continued access. Unit tests use
**synthetic fixtures**. The collector stops on 429 and checks robots.txt before
requesting listings. Optional FlareSolverr recovery is tested with mocks, not
against a live service. Saved HTML can also be imported without network access.

## Run

From this repository's root (no package installation required):

```sh
python3 -m hltv_api collect --kind upcoming
python3 -m hltv_api collect --kind results
python3 -m hltv_api serve
```

The default database is `hltv.sqlite3`. Specify another database before the
subcommand: `python3 -m hltv_api --db /path/to/hltv.sqlite3 serve`.
An installed console command is also available with `pip install .` in your
own virtual environment.

To exercise the complete storage/API flow offline using sample data:

```sh
python3 -m hltv_api collect --kind upcoming --html tests/fixtures/upcoming.html
python3 -m hltv_api collect --kind results --html tests/fixtures/results.html
python3 -m hltv_api serve
```

Then open <http://127.0.0.1:8000/v1/matches>. Fixture data is fictional; use a
separate database for actual collection.

## Endpoints

| Request | Response |
| --- | --- |
| `GET /health` | Process liveness (does not indicate collection freshness) |
| `GET /v1/matches` | Stored records ordered by match ID descending |
| `GET /v1/matches?status=finished&limit=50&offset=0` | Filtered, paginated records |
| `GET /v1/matches/2380001` | One match or HTTP 404 |

List and detail responses wrap records in `data`. Fields include `id`, `url`,
`status`, `team1`, `team2`, `event`, `starts_at`, `score1`, `score2`, and
`collected_at`. Times use UTC; unavailable fields are null. Scores are series
scores, not individual-map round scores. `collected_at` is the last successful
observation, not the match time. Limits range from 1 to 500.

## Collection behavior

- Each invocation requests one listing page; no full-history backfill or match
  detail scraping is implemented.
- Requests default to 8–14 seconds between starts (configurable minimum five seconds). A
  robots.txt crawl delay can increase this. Transient network/server failures
  receive up to three attempts. HTTP 429 stops immediately. With an explicitly
  configured browser service, a 403 triggers one browser attempt; unresolved
  challenges stop collection.
- Parsing completes before writes. Unexpected markup and ambiguous empty
  listings fail visibly and preserve stored records.
- Match IDs deduplicate reruns. Finished records cannot be overwritten by an
  older upcoming listing. Missing matches are retained: cancellation and live
  status tracking are not implemented. Check `collected_at` for stale data.
- Run collection as a separate scheduled job after validating access from your deployment network.
  Do not overlap collector runs or launch multiple independent collectors
  against HLTV; throttling is per process. API reads never scrape HLTV.

The bundled WSGI server binds to loopback and is intended for local development.
For hosting, use a production WSGI server with
`hltv_api.api.create_app(hltv_api.store.Store(database_path))`, and configure
authentication, TLS, and request limits at the reverse proxy. This repository
does not deploy infrastructure or expose an authenticated public service.

## Validate

```sh
python3 -m unittest discover -s tests -v
```

Tests cover parsing, blocked pages, robots checks, bounded retries, storage
updates, and API validation. GitHub Actions runs them on Python 3.11 and 3.13.

This project is independent of and unaffiliated with HLTV.

## Home cluster

The Dockerfile runs the API with Gunicorn as a non-root user. The optional
**Build home cluster image** GitHub Actions workflow runs tests, checks container
startup, and publishes amd64/ARM64 images to `ghcr.io/ptradiverr/hltv-api`.
It reports a digest to pin in the separate `ptradiverr/homelab` repository.
Image publication does not automatically change homelab desired state.

The homelab `hltv_api` Ansible role deploys one API/collector pod with a shared
SQLite volume and a private ClusterIP Service. The collector starts immediately
and then waits 30 minutes between cycles; failures preserve existing data.
The role remains disabled until `hltv_api_image` is set to a published digest.
See `homelab/docs/hltv-api.md` for release steps and SSH access instructions.

For container development, set `HLTV_DB` to a writable database path. The
production API entry point is `hltv_api.wsgi:application`; the collector process
is `python -m hltv_api.scheduler`. `HLTV_INTERVAL_SECONDS` defaults to 1800 and
must be at least 900. Use one collector and retain the single-replica deployment.

## Browser transport options

Fragella uses browser TLS fingerprints, persistent FlareSolverr sessions, slow
requests, and residential network exits. This collector implements the portable
HTTP/browser layers. It does not install or modify Fragella's Pi/WireGuard
infrastructure. No transport guarantees that HLTV will accept a request.

Install the optional HTTP client in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install '.[browser]'
.venv/bin/python -m hltv_api collect --kind results --backend curl
```

The `curl` backend uses a persistent `curl_cffi` Chrome profile with matching
default browser headers. Changing only the User-Agent does not reproduce a
browser's TLS or HTTP/2 behavior. `--user-agent` applies to the standard-library
backend and the robots policy check; it does not override browser headers.

On macOS, verify `python3 --version` before creating the virtual environment.
Apple's Python 3.9 does not meet this project's Python 3.11+ requirement.
Use an installed Python 3.11+ interpreter explicitly (for example,
`python3.13 -m venv .venv-py313`) and upgrade pip inside that environment.
The browser extra supports stable `curl_cffi` 0.13.0 as well as newer releases;
pre-release packages are not required.

For JavaScript challenges, run FlareSolverr locally (requires Docker):

```sh
docker run --rm --name hltv-browser -p 127.0.0.1:8191:8191 \
  ghcr.io/flaresolverr/flaresolverr:v3.5.2
.venv/bin/python -m hltv_api collect --kind results --backend curl \
  --flaresolverr-url http://127.0.0.1:8191 --challenge-timeout 60
```

FlareSolverr is an external, optional service; it is not started automatically.
The command above pins the same version referenced by Fragella's documentation;
this project's tests mock the service rather than launching that image.
On a 403 or challenge page the collector opens one persistent browser session
and keeps subsequent fetches in that browser. It validates the returned URL and
HTML, and destroys the session on exit. Cookies stay in that session and are
not logged, saved, or copied into a different client. Robots directives still
apply, including when the browser renders robots.txt inside a `<pre>` element.
An explicit rate limit stops collection instead of switching sessions or IPs.

Network origin is a separate factor: a datacenter address can remain blocked
even with browser transport. If you use your own residential exit, run both
the HTTP client and browser service through that same connection. This project
does not rotate IPs or configure a VPN. Keep one collector process and schedule
runs conservatively; API requests should read the cached database.

Upstream references: [curl_cffi](https://github.com/lexiforest/curl_cffi) and
[FlareSolverr API](https://github.com/FlareSolverr/FlareSolverr#usage).
