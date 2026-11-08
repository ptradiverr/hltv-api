# HLTV API

A self-hosted, read-only JSON API for stored Counter-Strike match and player
data. Run it locally with Python or Docker and provide your own SQLite database.
This package contains the API server and database access code. It does not
collect data or contact HLTV. It is independent of and unaffiliated with HLTV.

## Python quick start

Install Python 3.11+ and Git, then:

```sh
git clone https://github.com/ptradiverr/hltv-api.git
cd hltv-api
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[server]'
python -m hltv_api --db ./hltv.sqlite3 serve
```

Open <http://127.0.0.1:8000/v1/matches>. A new database is initialized with empty
tables; an empty `data` list is expected until you supply data. To use an existing
compatible database, replace `./hltv.sqlite3` with its path.

On Windows, create the environment using an installed supported interpreter,
such as `py -3.13 -m venv .venv`, then activate `.venv\Scripts\Activate.ps1` in
PowerShell. The development server supports Windows; Gunicorn is for Linux/macOS.

## Docker

Build the API image from this source:

```sh
docker build -t hltv-api:local .
docker volume create hltv-data
docker run -d --name hltv-api --restart unless-stopped \
  --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp \
  -p 127.0.0.1:8000:8000 \
  --mount source=hltv-data,target=/data \
  hltv-api:local
```

The server uses `/data/hltv.sqlite3`. A new named volume starts with an empty
database. Provide a compatible database through your own data process or mount
a local database directory instead, ensuring UID/GID 10001 can write to it.

The manually dispatched **Build API image** workflow tests and publishes amd64
and ARM64 images to `ghcr.io/ptradiverr/hltv-api`. Use a digest from a build of
this API-only source. Older images published before the split include additional
components; rewriting Git history does not change or remove those images.

## Endpoints

All endpoints use `GET` and return JSON.

| Endpoint | Response |
| --- | --- |
| `/health` | API process liveness |
| `/v1/matches` | Stored matches, by descending ID |
| `/v1/matches?status=finished` | Finished matches |
| `/v1/matches?status=scheduled` | Scheduled matches |
| `/v1/matches/123` | One match, or HTTP 404 |
| `/v1/players` | Stored players, by nickname then ID |
| `/v1/players?q=example` | Literal nickname substring search |
| `/v1/players/123` | One player, or HTTP 404 |

List endpoints accept `limit` (1–500, default 100) and `offset` (default 0).
Responses wrap records in `data`; lists also include `limit` and `offset`.
Search text is limited to 128 characters. HTTP write methods are not supported.

```sh
curl 'http://127.0.0.1:8000/v1/matches?status=finished&limit=10'
curl 'http://127.0.0.1:8000/v1/players?q=example'
```

Match records may contain `id`, `url`, `status`, `team1`, `team2`, `event`,
`starts_at`, `score1`, and `score2`. Scores describe series results. Player
records contain `id`, `name`, and optional `country`, `url`, `teams`, `summary`,
and `statistics` sections. Missing metrics can be null. The database adds
`collected_at` in UTC; player section timestamps are tracked separately.
`/health` does not indicate whether your supplied data is fresh.

## Provide data

Use a compatible database from your own data pipeline. The Python storage API
can also write records locally. For example, from the project directory:

```python
from hltv_api.store import Store

store = Store("hltv.sqlite3")
store.save([{
    "id": 123,
    "status": "finished",
    "team1": "Example A",
    "team2": "Example B",
    "score1": 2,
    "score2": 1,
}])
store.save_players([{
    "id": 456,
    "name": "Example",
    "summary": {"maps": 50, "rating": {"version": "2.0", "value": 1.10}},
}])
```

These are fictional examples. The HTTP API does not ingest data. `Store.save`
upserts matches by integer ID and requires `status`. Finished matches cannot be
overwritten by an older scheduled record. `Store.save_players` requires `id`
and `name`, merges sections, and retains previously stored detail sections when
only a summary is updated.

Existing compatible databases are reused without discarding their records.
Keep SQLite on a local filesystem with working file locks. Use a single data
writer, keep backups, and stop the server and writer before copying database
files for a simple backup. A persistent volume does not provide replication.

## Hosting

The `serve` command is a development server. For Linux/macOS hosting:

```sh
HLTV_DB="$PWD/hltv.sqlite3" gunicorn --bind 127.0.0.1:8000 \
  --workers 1 --threads 4 hltv_api.wsgi:application
```

The Docker image uses Gunicorn and runs as UID 10001. If exposing your instance
beyond localhost, configure HTTPS, suitable access controls, and request limits
at a reverse proxy. The application has no built-in authentication or rate limits.

## Tests

```sh
python -m unittest discover -s tests -v
```
