"""Single API replica, persistent SQLite index; complete records mirrored to Drive."""
import json
import os
import sqlite3
from pathlib import Path

class Store:
    def __init__(self, path=None):
        self.path = path or os.environ.get('DATABASE_PATH', 'data/jobs.sqlite3')
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, record TEXT NOT NULL)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA journal_mode=WAL')
        return db

    def save(self, job):
        with self.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET state=excluded.state, record=excluded.record',
                       (job['id'], job['state'], json.dumps(job, allow_nan=False)))

    def get(self, ident):
        with self.connect() as db:
            row = db.execute('SELECT record FROM jobs WHERE id=?', (ident,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, offset=0):
        with self.connect() as db:
            rows = db.execute('SELECT record FROM jobs ORDER BY rowid DESC LIMIT 50 OFFSET ?', (offset,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def claim(self, ident):
        # Persist the claim before sending an external billable request. Unknown
        # submission outcomes require operator reconciliation, never blind retries.
        with self.connect() as db:
            return db.execute("UPDATE jobs SET state='submitting', record=json_set(record, '$.state', 'submitting') WHERE id=? AND state='uploading'", (ident,)).rowcount == 1
