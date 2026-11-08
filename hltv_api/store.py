import json
import sqlite3
from datetime import datetime, timezone
from contextlib import closing, contextmanager


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY, status TEXT NOT NULL,
                payload TEXT NOT NULL, collected_at TEXT NOT NULL)""")

    @contextmanager
    def connection(self):
        # sqlite3's own context manager commits/rolls back, but does not close.
        # A persistent API must release each connection promptly.
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            with db:
                yield db

    def save(self, records):
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            for record in records:
                db.execute("""INSERT INTO matches VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                    payload=excluded.payload, collected_at=excluded.collected_at
                    WHERE matches.status != 'finished' OR excluded.status = 'finished'""",
                           (record["id"], record["status"], json.dumps(record), now))

    def list(self, status=None, limit=100, offset=0):
        with self.connection() as db:
            rows = db.execute("""SELECT payload, collected_at FROM matches
                WHERE (? IS NULL OR status = ?) ORDER BY id DESC LIMIT ? OFFSET ?""",
                              (status, status, limit, offset)).fetchall()
        return [dict(json.loads(payload), collected_at=at) for payload, at in rows]

    def get(self, match_id):
        with self.connection() as db:
            row = db.execute("SELECT payload, collected_at FROM matches WHERE id = ?", (match_id,)).fetchone()
        return dict(json.loads(row[0]), collected_at=row[1]) if row else None
