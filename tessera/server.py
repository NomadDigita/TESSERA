from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse
import uuid

from .auth import AuthError, AuthManager
from .config import Settings
from .domain import DomainError
from .services import CapitalOrchestrator
from .storage import SQLiteStore
from .observability import LOGGER, METRICS


SETTINGS = Settings.from_env()
SETTINGS.prepare_runtime()
STORE = SQLiteStore(SETTINGS.database_path)
ORCH = CapitalOrchestrator(STORE, SETTINGS)
AUTH = AuthManager(STORE, SETTINGS.session_secret, SETTINGS.session_ttl_seconds) if SETTINGS.auth_enabled else None
if AUTH and STORE.count_users() == 0:
    if not SETTINGS.admin_password:
        raise RuntimeError("TESSERA_ADMIN_PASSWORD is required to bootstrap the first administrator")
    AUTH.create_user(SETTINGS.admin_username, SETTINGS.admin_password, "admin")

WEB_ROOT = Path(__file__).with_name("web")
STATIC_ROUTES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "TESSERA"

    def _send(self, payload, status: int = 200, content_type: str = "application/json") -> None:
        body = payload if isinstance(payload, bytes) else (payload.encode() if isinstance(payload, str) else json.dumps(payload).encode())
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-ID", getattr(self, "request_id", "unknown"))
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "public, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)
        path = urlparse(self.path).path
        duration_ms = round((perf_counter() - getattr(self, "request_started", perf_counter())) * 1000, 2)
        METRICS.inc("http_responses_total", labels={"method": self.command, "path": self._metric_path(path), "status": str(status)})
        LOGGER.info("http_request", extra={"context": {"request_id": getattr(self, "request_id", "unknown"), "method": self.command, "path": path, "status": status, "duration_ms": duration_ms}})

    @staticmethod
    def _metric_path(path: str) -> str:
        return "/api/runs/{id}" if path.startswith("/api/runs/") else path

    def _begin(self) -> None:
        self.request_id = self.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
        self.request_started = perf_counter()

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Request body exceeds 1 MB")
        return json.loads(self.rfile.read(length) or b"{}")

    def _principal(self, minimum_role: str = "viewer") -> dict | None:
        if not AUTH:
            return {"username": "local-dev", "role": "admin"}
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            self._send({"error": "Bearer token required"}, 401)
            return None
        try:
            principal = AUTH.verify(header[7:])
            AUTH.require(principal, minimum_role)
            return principal
        except AuthError as exc:
            self._send({"error": str(exc)}, 403 if str(exc) == "Insufficient permissions" else 401)
            return None

    def do_GET(self) -> None:
        self._begin()
        path = urlparse(self.path).path
        if path in STATIC_ROUTES:
            filename, content_type = STATIC_ROUTES[path]
            return self._send((WEB_ROOT / filename).read_bytes(), content_type=content_type)
        if path == "/api/health":
            return self._send(ORCH.health())
        if path == "/api/ready":
            ready, result = ORCH.readiness()
            return self._send(result, 200 if ready else 503)
        if path == "/metrics":
            METRICS.gauge("runs", len(ORCH.runs))
            METRICS.gauge("kill_switch", 1 if ORCH.kill_switch_enabled else 0)
            return self._send(METRICS.render(), content_type="text/plain; version=0.0.4")
        if not self._principal("viewer"):
            return
        if path == "/api/portfolio":
            return self._send(ORCH.broker.snapshot())
        if path == "/api/ledger":
            return self._send({"valid": ORCH.ledger.verify(), "entries": ORCH.ledger.json()})
        if path == "/api/model-calls":
            return self._send({"calls": ORCH.store.list_model_calls()})
        if path == "/api/strategies":
            return self._send({"strategies": ORCH.strategies.list()})
        if path.startswith("/api/market-graph/"):
            return self._send({"edges": ORCH.market_graph.neighbors(path.rsplit("/", 1)[-1])})
        if path.startswith("/api/market-twin/"):
            return self._send(ORCH.market_twin.estimate(path.rsplit("/", 1)[-1]))
        if path == "/api/runs":
            return self._send({"runs": [run.json() for run in ORCH.runs.values()]})
        if path.startswith("/api/runs/"):
            run = ORCH.runs.get(path.rsplit("/", 1)[-1])
            return self._send(run.json() if run else {"error": "run not found"}, 200 if run else 404)
        return self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:
        self._begin()
        path = urlparse(self.path).path
        try:
            data = self._body()
            if path == "/api/auth/login":
                if not AUTH:
                    return self._send({"error": "Authentication is disabled"}, 404)
                return self._send(AUTH.login(str(data.get("username", "")), str(data.get("password", ""))))
            if path == "/api/runs":
                if not self._principal("researcher"):
                    return
                run = ORCH.create_run(data, idempotency_key=self.headers.get("Idempotency-Key"))
                return self._send(run.json(), 201)
            if path == "/api/replay":
                if not self._principal("researcher"):
                    return
                return self._send(ORCH.replay(data["run_id"]).json(), 201)
            if path == "/api/market/observations":
                if not self._principal("researcher"):
                    return
                return self._send(ORCH.market_twin.observe(**data), 201)
            if path == "/api/market/relationships":
                if not self._principal("researcher"):
                    return
                return self._send(ORCH.market_graph.connect(**data), 201)
            if path == "/api/strategies":
                if not self._principal("researcher"):
                    return
                return self._send(ORCH.strategies.publish(data), 201)
            if path == "/api/risk/kill-switch":
                principal = self._principal("operator")
                if not principal:
                    return
                state = ORCH.set_kill_switch(bool(data.get("enabled")), bool(data.get("liquidate")), actor=principal["username"])
                return self._send(state)
            if path.startswith("/api/runs/"):
                if not self._principal("operator"):
                    return
                pieces = path.split("/")
                run_id, action = pieces[3], pieces[4]
                actions = {"approve": ORCH.approve, "reject": ORCH.reject, "reconcile": ORCH.reconcile}
                if action not in actions:
                    return self._send({"error": "unknown action"}, 404)
                return self._send(actions[action](run_id).json())
        except DomainError as exc:
            return self._send({"error": str(exc)}, 409)
        except AuthError as exc:
            return self._send({"error": str(exc)}, 401)
        except (KeyError, ValueError, json.JSONDecodeError, IndexError) as exc:
            return self._send({"error": str(exc)}, 400)
        return self._send({"error": "not found"}, 404)

    def log_message(self, format_string: str, *args) -> None:
        return


class TesseraHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host or SETTINGS.host
    port = port or SETTINGS.port
    LOGGER.info("server_start", extra={"context": {"host": host, "port": port, "mode": SETTINGS.broker_mode, "environment": SETTINGS.environment}})
    server = TesseraHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        ORCH.close()
        LOGGER.info("server_stop")
