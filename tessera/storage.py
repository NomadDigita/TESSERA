from __future__ import annotations

import json
import sqlite3
import hashlib
from threading import RLock
from datetime import datetime, timedelta, timezone

from .domain import LedgerEntry, Run


def _decode_json(value):
    """Decode SQLite text and PostgreSQL JSON/JSONB values uniformly."""
    return value if isinstance(value, (dict, list)) else json.loads(value)


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
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    jti TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER,
                    FOREIGN KEY(username) REFERENCES users(username)
                );
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(username, expires_at);
                CREATE TABLE IF NOT EXISTS market_observations (
                    observation_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_observations_symbol_time
                    ON market_observations(symbol, observed_at DESC);
                CREATE TABLE IF NOT EXISTS market_edges (
                    edge_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_edges_source_target ON market_edges(source, target);
                CREATE TABLE IF NOT EXISTS strategy_versions (
                    strategy_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(strategy_id, version)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TEXT NOT NULL,
                    lease_until TEXT,
                    worker_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_claim
                    ON jobs(status, available_at, lease_until, created_at);
                CREATE TABLE IF NOT EXISTS replays (
                    replay_id TEXT PRIMARY KEY,
                    original_run_id TEXT NOT NULL,
                    replay_run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    artifact_key TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
            self._ensure_model_call_columns()

    def _ensure_model_call_columns(self) -> None:
        columns = {
            "run_id": "TEXT NOT NULL DEFAULT 'UNSCOPED'",
            "prompt_version": "TEXT NOT NULL DEFAULT 'agent-v1'",
            "output_hash": "TEXT NOT NULL DEFAULT ''",
            "token_usage": "TEXT NOT NULL DEFAULT '{}'",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, definition in columns.items():
            try:
                self._db.execute(f"ALTER TABLE model_calls ADD COLUMN {name} {definition}")
            except Exception:
                self._db.rollback()

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
            data = _decode_json(row["payload"])
            run = Run(**data)
            runs[run.run_id] = run
        return runs

    def append_ledger(self, entry: LedgerEntry) -> None:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT entry_hash FROM ledger_entries ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                previous = row["entry_hash"] if row else "GENESIS"
                raw = json.dumps(entry.payload, sort_keys=True, separators=(",", ":"))
                entry.payload_hash = hashlib.sha256(raw.encode()).hexdigest()
                entry.previous_hash = previous
                material = f"{entry.run_id}|{entry.entry_type}|{entry.actor}|{entry.payload_hash}|{previous}"
                entry.entry_hash = hashlib.sha256(material.encode()).hexdigest()
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
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    def load_ledger(self) -> list[LedgerEntry]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM ledger_entries ORDER BY sequence").fetchall()
        return [
            LedgerEntry(
                entry_id=row["entry_id"], run_id=row["run_id"], entry_type=row["entry_type"],
                actor=row["actor"], payload=_decode_json(row["payload"]), created_at=row["created_at"],
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
                """INSERT INTO model_calls(provider,model,agent,input_hash,latency_ms,validation_status,
                   run_id,prompt_version,output_hash,token_usage,retry_count) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (call["provider"], call["model"], call["agent"], call["input_hash"],
                 call["latency_ms"], call["validation_status"], call["run_id"],
                 call["prompt_version"], call["output_hash"],
                 json.dumps(call.get("token_usage", {}), sort_keys=True), call.get("retry_count", 0)),
            )

    def list_model_calls(self, limit: int = 100, run_id: str | None = None) -> list[dict]:
        with self._lock:
            if run_id:
                rows = self._db.execute(
                    "SELECT * FROM model_calls WHERE run_id=? ORDER BY call_id DESC LIMIT ?", (run_id, limit)
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM model_calls ORDER BY call_id DESC LIMIT ?", (limit,)
                ).fetchall()
        result = [dict(row) for row in rows]
        for call in result:
            call["token_usage"] = json.loads(call["token_usage"] or "{}")
        return result

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
            return int(self._db.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"])

    def list_users(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT username,role,active,created_at FROM users ORDER BY username"
            ).fetchall()
        return [{**dict(row), "active": bool(row["active"])} for row in rows]

    def update_user(self, username: str, *, role: str | None = None, active: bool | None = None) -> dict | None:
        user = self.get_user(username)
        if not user:
            return None
        new_role = role if role is not None else user["role"]
        new_active = active if active is not None else user["active"]
        with self._lock, self._db:
            self._db.execute("UPDATE users SET role=?,active=? WHERE username=?",
                             (new_role, 1 if new_active else 0, username))
        return self.get_user(username)

    def active_admin_count(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS count FROM users WHERE role='admin' AND active=1"
            ).fetchone()
        return int(row["count"])

    def create_session(self, session: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO auth_sessions(jti,username,issued_at,expires_at) VALUES(?,?,?,?)",
                (session["jti"], session["username"], session["issued_at"], session["expires_at"]),
            )

    def get_session(self, jti: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM auth_sessions WHERE jti=?", (jti,)).fetchone()
        return dict(row) if row else None

    def revoke_session(self, jti: str, revoked_at: int) -> bool:
        with self._lock, self._db:
            cursor = self._db.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE jti=? AND revoked_at IS NULL",
                (revoked_at, jti),
            )
        return cursor.rowcount > 0

    def revoke_user_sessions(self, username: str, revoked_at: int) -> int:
        with self._lock, self._db:
            cursor = self._db.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE username=? AND revoked_at IS NULL",
                (revoked_at, username),
            )
        return cursor.rowcount

    def list_active_sessions(self, username: str, current_time: int) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                """SELECT jti,username,issued_at,expires_at FROM auth_sessions
                   WHERE username=? AND revoked_at IS NULL AND expires_at>? ORDER BY issued_at DESC""",
                (username, current_time),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_market_observation(self, observation: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO market_observations(observation_id,symbol,observed_at,payload) VALUES(?,?,?,?)",
                (observation["observation_id"], observation["symbol"], observation["observed_at"],
                 json.dumps(observation, sort_keys=True, separators=(",", ":"))),
            )

    def list_market_observations(self, symbol: str, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM market_observations WHERE symbol=? ORDER BY observed_at DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        return [_decode_json(row["payload"]) for row in rows]

    def save_market_edge(self, edge: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO market_edges(edge_id,source,target,relation,payload) VALUES(?,?,?,?,?)",
                (edge["edge_id"], edge["source"], edge["target"], edge["relation"],
                 json.dumps(edge, sort_keys=True, separators=(",", ":"))),
            )

    def list_market_edges(self, asset: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM market_edges WHERE source=? OR target=? ORDER BY relation, edge_id",
                (asset, asset),
            ).fetchall()
        return [_decode_json(row["payload"]) for row in rows]

    def save_strategy_version(self, strategy: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO strategy_versions(strategy_id,version,created_at,payload) VALUES(?,?,?,?)",
                (strategy["strategy_id"], strategy["version"], strategy["created_at"],
                 json.dumps(strategy, sort_keys=True, separators=(",", ":"))),
            )

    def latest_strategy_version(self, strategy_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT payload FROM strategy_versions WHERE strategy_id=? ORDER BY version DESC LIMIT 1",
                (strategy_id,),
            ).fetchone()
        return _decode_json(row["payload"]) if row else None

    def list_strategy_versions(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM strategy_versions ORDER BY created_at DESC, version DESC"
            ).fetchall()
        return [_decode_json(row["payload"]) for row in rows]

    def enqueue_job(self, job: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO jobs(job_id,job_type,status,payload,attempts,available_at,created_at,updated_at)
                   VALUES(?,?, 'queued', ?,0,?,?,?)""",
                (job["job_id"], job["job_type"], json.dumps(job["payload"], sort_keys=True),
                 job["available_at"], job["created_at"], job["created_at"]),
            )

    def claim_job(self, worker_id: str, lease_seconds: int = 60) -> dict | None:
        current = datetime.now(timezone.utc)
        current_text = current.isoformat()
        lease_until = (current + timedelta(seconds=lease_seconds)).isoformat()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    """SELECT * FROM jobs
                       WHERE available_at<=? AND (status='queued' OR (status='running' AND lease_until<?))
                       ORDER BY created_at LIMIT 1""",
                    (current_text, current_text),
                ).fetchone()
                if not row:
                    self._db.commit()
                    return None
                self._db.execute(
                    """UPDATE jobs SET status='running', worker_id=?, lease_until=?,
                       attempts=attempts+1, updated_at=? WHERE job_id=?""",
                    (worker_id, lease_until, current_text, row["job_id"]),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get_job(row["job_id"])

    def finish_job(self, job_id: str, result: dict) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock, self._db:
            self._db.execute(
                """UPDATE jobs SET status='succeeded', result=?, error=NULL, lease_until=NULL,
                   updated_at=? WHERE job_id=? AND status='running'""",
                (json.dumps(result, sort_keys=True), timestamp, job_id),
            )

    def fail_job(self, job_id: str, error: str, max_attempts: int = 3) -> None:
        timestamp = datetime.now(timezone.utc)
        with self._lock, self._db:
            row = self._db.execute("SELECT attempts FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return
            terminal = int(row["attempts"]) >= max_attempts
            retry_at = (timestamp + timedelta(seconds=min(60, 2 ** int(row["attempts"])))).isoformat()
            self._db.execute(
                """UPDATE jobs SET status=?, error=?, lease_until=NULL, available_at=?,
                   updated_at=? WHERE job_id=?""",
                ("failed" if terminal else "queued", error[:2000], retry_at, timestamp.isoformat(), job_id),
            )

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        job["payload"] = json.loads(job["payload"])
        job["result"] = json.loads(job["result"]) if job["result"] else None
        return job

    def queue_depth(self) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT status, COUNT(*) AS count FROM jobs GROUP BY status").fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def save_replay(self, replay: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO replays(replay_id,original_run_id,replay_run_id,created_at,artifact_key,payload)
                   VALUES(?,?,?,?,?,?)""",
                (replay["replay_id"], replay["original_run_id"], replay["replay_run_id"],
                 replay["created_at"], replay["artifact"]["key"],
                 json.dumps(replay, sort_keys=True, separators=(",", ":"))),
            )

    def get_replay(self, replay_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT payload FROM replays WHERE replay_id=?", (replay_id,)).fetchone()
        return _decode_json(row["payload"]) if row else None

    def list_replays(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM replays ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_decode_json(row["payload"]) for row in rows]

    def ping(self) -> bool:
        try:
            with self._lock:
                return self._db.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        except sqlite3.Error:
            return False

    def close(self) -> None:
        self._db.close()


class _PostgresConnection:
    """Small compatibility boundary keeping storage semantics identical across engines."""

    def __init__(self, database_url: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL requires the 'postgres' TESSERA dependency") from exc
        self._connection = psycopg.connect(database_url, row_factory=dict_row, autocommit=True)

    @staticmethod
    def _sql(statement: str) -> str:
        statement = statement.replace("?", "%s")
        if statement.startswith("ALTER TABLE") and "ADD COLUMN" in statement and "IF NOT EXISTS" not in statement:
            statement = statement.replace("ADD COLUMN", "ADD COLUMN IF NOT EXISTS", 1)
        statement = statement.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        if "INSERT INTO idempotency_keys" in statement and "ON CONFLICT" not in statement:
            statement += " ON CONFLICT(scope,key) DO NOTHING"
        return statement

    def execute(self, statement: str, parameters=()):
        if statement.strip().upper() == "BEGIN IMMEDIATE":
            self._connection.execute("BEGIN")
            self._connection.execute("SELECT pg_advisory_xact_lock(1413829465)")
            return self._connection.execute("SELECT 1 AS ok")
        if "SELECT * FROM jobs" in statement and "ORDER BY created_at LIMIT 1" in statement:
            statement += " FOR UPDATE SKIP LOCKED"
        return self._connection.execute(self._sql(statement), parameters)

    def executescript(self, script: str) -> None:
        script = script.replace("PRAGMA journal_mode=WAL;", "").replace("PRAGMA foreign_keys=ON;", "")
        script = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        self.rollback() if exc_type else self.commit()


class PostgreSQLStore(SQLiteStore):
    """Production store with the same transactional contract as SQLiteStore."""

    def __init__(self, database_url: str) -> None:
        self.path = database_url
        self._lock = RLock()
        self._db = _PostgresConnection(database_url)
        self._migrate()

    def _migrate(self) -> None:
        self._db.execute("CREATE EXTENSION IF NOT EXISTS vector")
        super()._migrate()
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS asset_embeddings (
                embedding_id TEXT PRIMARY KEY,
                asset TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding vector(1536) NOT NULL,
                metadata TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )

    def ping(self) -> bool:
        try:
            with self._lock:
                return self._db.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
        except Exception:
            return False


def create_store(database_url: str, sqlite_path: str):
    if database_url:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return PostgreSQLStore(database_url)
    return SQLiteStore(sqlite_path)
