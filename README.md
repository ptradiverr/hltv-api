# HLTV API

Run your own collector and JSON API for HLTV results and upcoming matches.
Records are stored in SQLite, so API requests read saved data without making
another request to HLTV. Each installation uses its own database and internet
connection. No account or API key is required by this application.

Install with Python or run the published Docker image. This project is
independent of and unaffiliated with HLTV.

## Install with Python

You need **Python 3.11 or newer** and Git. Check your version:

```sh
python3 --version
```

On macOS, the system Python may be too old. Install a newer version from
[python.org](https://www.python.org/downloads/) and use it to create the
environment, for example `python3.13 -m venv .venv`.

```sh
git clone https://github.com/ptradiverr/hltv-api.git
cd hltv-api
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[browser,server]'
```

On Windows, use `py -3.13 -m venv .venv` with Python 3.13 installed, then
`.venv\Scripts\Activate.ps1` in PowerShell. The development server works on
Windows; Gunicorn is for Linux/macOS, including Linux containers and WSL.

### Collect data and start the API

Run these from the repository directory with the environment activated:

```sh
python -m hltv_api collect --kind results --backend curl
python -m hltv_api collect --kind upcoming --backend curl
python -m hltv_api serve
```

Open **<http://127.0.0.1:8000/v1/matches>**. Leave the server terminal running.
The collection commands print the number of records saved. They fetch the
recent results and upcoming matches listings, rather than all match history.

Data is saved in `hltv.sqlite3` in the current directory. Rerunning collection
updates matches by ID without creating duplicates. To choose another database,
put `--db` before the subcommand every time:

```sh
python -m hltv_api --db ./matches.sqlite3 collect --kind results --backend curl
python -m hltv_api --db ./matches.sqlite3 serve
```

### Keep the data updated

In a second terminal, change to the same repository directory and activate the
environment. Start the collector loop:

```sh
source .venv/bin/activate
HLTV_DB="$PWD/hltv.sqlite3" python -m hltv_api.scheduler
```

The loop collects results and upcoming matches immediately, then waits **30
minutes after each cycle** before collecting again. Keep the terminal running;
press Ctrl+C to stop. Use one loop per database and avoid manual collection
while the loop is active. The API server alone does not collect data.

On PowerShell, first set `$env:HLTV_DB = "$PWD/hltv.sqlite3"`, then run
`python -m hltv_api.scheduler`.

To collect hourly instead:

```sh
HLTV_DB="$PWD/hltv.sqlite3" HLTV_INTERVAL_SECONDS=3600 python -m hltv_api.scheduler
```

The minimum interval is 900 seconds. Requests within a cycle default to 8–14
seconds apart; robots.txt crawl delays can increase this. A failed cycle keeps
saved data and waits for the next cycle before trying again.

## Run with Docker

You need Docker running. Published images support Linux amd64 and ARM64,
including Raspberry Pis running a 64-bit operating system.

Use a published image digest rather than assuming a `latest` tag exists. This
example uses a published version; find other versions in the
[container package](https://github.com/ptradiverr/hltv-api/pkgs/container/hltv-api).

```sh
export HLTV_IMAGE='ghcr.io/ptradiverr/hltv-api@sha256:3e7e5e63d5d1d08b28a457e41e81440854f4312fcd752d180ced2396da64f323'
docker pull "$HLTV_IMAGE"
docker volume create hltv-data

docker run -d --name hltv-api --restart unless-stopped \
  --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp \
  -p 127.0.0.1:8000:8000 \
  --mount source=hltv-data,target=/data \
  "$HLTV_IMAGE"

docker run -d --name hltv-collector --restart unless-stopped \
  --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp \
  --mount source=hltv-data,target=/data \
  -e HLTV_INTERVAL_SECONDS=1800 \
  "$HLTV_IMAGE" python -m hltv_api.scheduler
```

Open **<http://127.0.0.1:8000/v1/matches>**. The API and collector share the
`hltv-data` volume. An empty `data` list is expected until collection succeeds.
The image contains application code, not a prepopulated database.

Check progress:

```sh
docker logs --tail 50 hltv-collector
docker logs --tail 50 hltv-api
```

Stop and remove the containers while keeping saved data:

```sh
docker stop hltv-api hltv-collector
docker rm hltv-api hltv-collector
```

To update, stop/remove both containers, choose a newer image digest, pull it,
and repeat the two `docker run` commands using the same volume. Keep only one
collector running. Deleting the `hltv-data` volume deletes your records.

Alternatively, build from a local checkout:

```sh
docker build -t hltv-api:local .
export HLTV_IMAGE=hltv-api:local
```

Then use the same volume and container commands above, skipping `docker pull`.
Docker shell examples work in macOS/Linux terminals or WSL.

## Use the API

The default address is `http://127.0.0.1:8000`. Endpoints use `GET` and return JSON.

| Endpoint | Response |
| --- | --- |
| `/health` | API process liveness; does not indicate collection freshness |
| `/v1/matches` | Stored matches, ordered by match ID descending |
| `/v1/matches?status=finished` | Finished matches |
| `/v1/matches?status=scheduled` | Upcoming matches |
| `/v1/matches?limit=50&offset=50` | A page of records starting at offset 50 |
| `/v1/matches/2380001` | One stored match, or HTTP 404 if absent |

The default page size is 100. `limit` accepts 1–500; `offset` starts at zero.
Filters and pagination can be combined:

```sh
curl 'http://127.0.0.1:8000/v1/matches?status=finished&limit=10&offset=0'
```

List responses contain a `data` array, `limit`, and `offset`. A single-match
response contains one object in `data`. Match fields are:

| Field | Meaning |
| --- | --- |
| `id` | HLTV match ID |
| `url` | Source match page |
| `status` | `scheduled` or `finished` |
| `team1`, `team2` | Team names, when known |
| `event` | Tournament name, when available |
| `starts_at` | Match start time in UTC, when available |
| `score1`, `score2` | Finished series score, such as 2–1 |
| `collected_at` | Last successful observation of this record, in UTC |

Unavailable values are `null`. Scores describe the series result, not
individual-map round scores. Use `collected_at` to judge freshness.

## Troubleshooting

**HTTP 403 or challenge page:** install the `browser` extra and use
`--backend curl` for manual collection, as shown above. The scheduled collector
already uses it. Access depends on your network and HLTV's current protections;
success on another machine is not a guarantee for your connection.

**HTTP 429:** collection stops for that attempt. Let the next scheduled cycle
try again instead of starting more collectors or shortening the interval.

**No rows found:** the listing may be empty or HLTV's page structure may have
changed. Update your checkout/image and check the project's issues. Parsing
failures preserve existing records.

**Empty or stale data:** check collector logs, database paths, and `collected_at`.
The Python server does not collect data by itself. Both Docker containers must
mount the same named volume.

**Installation fails:** check `python --version` inside the activated environment,
upgrade pip, and update your checkout. If the environment uses an old Python,
create a new environment with Python 3.11+.

**Port 8000 is busy:** stop another API instance, use `serve --port 8001` for
Python, or change Docker's mapping to `-p 127.0.0.1:8001:8000`.

### Optional browser fallback for Python installations

For JavaScript challenges, manual collection can connect to a local
[FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) service:

```sh
docker run -d --rm --name hltv-browser -p 127.0.0.1:8191:8191 \
  ghcr.io/flaresolverr/flaresolverr:v3.5.2

python -m hltv_api collect --kind results --backend curl \
  --flaresolverr-url http://127.0.0.1:8191 --challenge-timeout 60
```

This option applies to manual commands; the scheduler has no FlareSolverr
configuration option. Only HTTP localhost service URLs are accepted. The address
above assumes Python runs on your host, outside Docker. Stop the optional
service with `docker stop hltv-browser` when finished.

Recovery uses one browser session per collector and stops if the page remains
blocked. It cannot guarantee access. robots.txt directives still apply, and
explicit rate limits stop collection. This integration is tested with mocks;
it has not been verified against HLTV with a live FlareSolverr service.

## Hosting and storage

The Python `serve` command is for local development; the Docker image uses
Gunicorn. On a Linux/macOS host installation, run the production server with:

```sh
HLTV_DB="$PWD/hltv.sqlite3" gunicorn --bind 127.0.0.1:8000 \
  --workers 1 --threads 4 hltv_api.wsgi:application
```

Examples bind API access to your own machine. If you expose your instance beyond
localhost, put HTTPS, appropriate access controls, and request limits in front
of it. The application has no built-in authentication or rate limiting.

Keep SQLite on a local filesystem with working file locks. API reads and one
collector may share it. Multiple collectors and network filesystems such as NFS
are not supported by this deployment model. Persistent storage survives container
replacement but provides no backups or replication. Stop both processes before
copying the database for a simple backup.

Collection covers match listings only. Player statistics, rosters, rankings,
individual map details, live status, cancellation tracking, and full-history
backfill are not implemented. Records missing from later listings are retained.

## Development

Run offline tests from a checkout:

```sh
python -m unittest discover -s tests -v
```

Try collection without contacting HLTV using synthetic fixtures and a separate
database:

```sh
python -m hltv_api --db sample.sqlite3 collect --kind results --html tests/fixtures/results.html
python -m hltv_api --db sample.sqlite3 serve --port 8001
```

Fixture data is fictional. Live access can change as HLTV changes its pages or
protections.
