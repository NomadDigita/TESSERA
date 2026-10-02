from __future__ import annotations

from dataclasses import asdict
import json
import sqlite3
from threading import RLock
from typing import Iterable

from .domain import LedgerEntry, Run


class SQLiteStore:
    """Durable system of record. Methods are intentionally small and transactional."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._lock = RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self._db:
            self._db.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    replay_of TEXT,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ledger_entries (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_ledger_run ON ledger_entries(run_id, sequence);
                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def save_run(self, run: Run) -> None:
        payload = json.dumps(run.json(), sort_keys=True, separators=(",", ":"))
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO runs(run_id,status,created_at,replay_of,payload)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,
                   replay_of=excluded.replay_of,payload=excluded.payload""",
                (run.run_id, run.status, run.created_at, run.replay_of, payload),
            )

    def load_runs(self) -> dict[str, Run]:
        with self._lock:
            rows = self._db.execute("SELECT payload FROM runs ORDER BY created_at").fetchall()
        runs: dict[str, Run] = {}
        for row in rows:
            data = json.loads(row["payload"])
            run = Run(**data)
            runs[run.run_id] = run
        return runs

    def append_ledger(self, entry: LedgerEntry) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO ledger_entries(entry_id,run_id,entry_type,actor,created_at,payload,
                   payload_hash,previous_hash,entry_hash) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    entry.entry_id,
                    entry.run_id,
                    entry.entry_type,
                    entry.actor,
                    entry.created_at,
                    json.dumps(entry.payload, sort_keys=True, separators=(",", ":")),
                    entry.payload_hash,
                    entry.previous_hash,
                    entry.entry_hash,
                ),
            )

    def load_ledger(self) -> list[LedgerEntry]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM ledger_entries ORDER BY sequence").fetchall()
        return [
            LedgerEntry(
                entry_id=row["entry_id"], run_id=row["run_id"], entry_type=row["entry_type"],
                actor=row["actor"], payload=json.loads(row["payload"]), created_at=row["created_at"],
                payload_hash=row["payload_hash"], previous_hash=row["previous_hash"], entry_hash=row["entry_hash"],
            )
            for row in rows
        ]

    def set_state(self, key: str, value: dict) -> None:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO system_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, encoded),
            )

    def get_state(self, key: str, default: dict) -> dict:
        with self._lock:
            row = self._db.execute("SELECT value FROM system_state WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def close(self) -> None:
        self._db.close()
