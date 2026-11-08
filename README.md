# HLTV API

Independent Python collector and read-only JSON API for HLTV upcoming matches
and recent results. Uses Python 3.11+ and the standard library at runtime.
SQLite persists records between collection runs. No Cytizen infrastructure or
Fragella code is required.

## Status

Initial scaffold. A live request to HLTV returned HTTP 403 during development.
Parsing is tested against **synthetic fixtures**, not verified against current
live pages. Live collection is not yet validated. The collector stops on
403/429 and checks robots.txt before requesting listings. It does not solve
challenges. If access is blocked, obtain permitted access from HLTV or import
HTML obtained through an authorized channel.

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
- Requests are sequential with at least five seconds between starts. A
  robots.txt crawl delay can increase this. Transient network/server failures
  receive up to three attempts; blocked requests stop immediately.
- Parsing completes before writes. Unexpected markup and ambiguous empty
  listings fail visibly and preserve stored records.
- Match IDs deduplicate reruns. Finished records cannot be overwritten by an
  older upcoming listing. Missing matches are retained: cancellation and live
  status tracking are not implemented. Check `collected_at` for stale data.
- Run collection as a separate scheduled job after live parsing is validated.
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
