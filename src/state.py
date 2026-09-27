"""The bot's own memory, in a small SQLite file (never the shop's database).

- where the last end-of-day report stopped (last invoice / return / deleted-line id)
- the item prices and stock at the last daily update, to tell what changed
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshot (
    id_item INTEGER PRIMARY KEY,
    price   REAL,
    cost    REAL,
    stock   REAL
);
"""


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path)
        try:
            with db:            # commits, or rolls back on error
                yield db
        finally:
            db.close()

    def get(self, key, default=None):
        with self._db() as db:
            row = db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value)))

    def snapshot(self) -> dict:
        """{id_item: {"price", "cost", "stock"}} from the last daily update; empty the first time."""
        with self._db() as db:
            rows = db.execute("SELECT id_item, price, cost, stock FROM snapshot").fetchall()
        return {r[0]: {"price": r[1], "cost": r[2], "stock": r[3]} for r in rows}

    def save_snapshot(self, items):
        with self._db() as db:
            db.execute("DELETE FROM snapshot")
            db.executemany("INSERT INTO snapshot (id_item, price, cost, stock) VALUES (?, ?, ?, ?)",
                           [(i.id, i.price, i.cost, i.stock) for i in items])
