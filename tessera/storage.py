from __future__ import annotations

import json
import sqlite3
from threading import RLock

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
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(scope, key)
                );
                CREATE TABLE IF NOT EXISTS model_calls (
                    call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    validation_status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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

    def get_idempotent_resource(self, scope: str, key: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT resource_id FROM idempotency_keys WHERE scope=? AND key=?", (scope, key)
            ).fetchone()
        return row["resource_id"] if row else None

    def save_idempotency_key(self, scope: str, key: str, resource_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO idempotency_keys(scope,key,resource_id) VALUES(?,?,?)",
                (scope, key, resource_id),
            )

    def record_model_call(self, call: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO model_calls(provider,model,agent,input_hash,latency_ms,validation_status)
                   VALUES(?,?,?,?,?,?)""",
                (call["provider"], call["model"], call["agent"], call["input_hash"],
                 call["latency_ms"], call["validation_status"]),
            )

    def list_model_calls(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM model_calls ORDER BY call_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def create_user(self, user: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO users(username,password_hash,role,active) VALUES(?,?,?,?)",
                (user["username"], user["password_hash"], user["role"], 1 if user.get("active", True) else 0),
            )

    def get_user(self, username: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["active"] = bool(user["active"])
        return user

    def count_users(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def ping(self) -> bool:
        try:
            with self._lock:
                return self._db.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    def close(self) -> None:
        self._db.close()
