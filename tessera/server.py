from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from .auth import AuthError, AuthManager
from .config import Settings
from .domain import DomainError
from .services import CapitalOrchestrator
from .storage import SQLiteStore

SETTINGS = Settings.from_env()
SETTINGS.prepare_runtime()
STORE = SQLiteStore(SETTINGS.database_path)
ORCH = CapitalOrchestrator(STORE, SETTINGS)
AUTH = AuthManager(STORE, SETTINGS.session_secret, SETTINGS.session_ttl_seconds) if SETTINGS.auth_enabled else None
if AUTH and STORE.count_users() == 0:
    if not SETTINGS.admin_password:
        raise RuntimeError("TESSERA_ADMIN_PASSWORD is required to bootstrap the first administrator")
    AUTH.create_user(SETTINGS.admin_username, SETTINGS.admin_password, "admin")

HTML = r'''<!doctype html><html><head><meta charset="utf-8"><title>TESSERA</title>
<style>body{margin:0;background:#09111f;color:#e6edf7;font:15px system-ui}main{max-width:1180px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;align-items:center}.mark{color:#74e1c1;font-size:28px;font-weight:800;letter-spacing:4px}.muted{color:#8fa3bd}.grid{display:grid;grid-template-columns:1.2fr .8fr;gap:18px;margin-top:22px}.card{background:#111e32;border:1px solid #263a55;border-radius:14px;padding:18px}.metric{font-size:30px;font-weight:700;margin:4px 0 12px}.pill{display:inline-block;padding:5px 9px;border-radius:20px;background:#183d45;color:#74e1c1;font-size:12px}.row{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #21314a}.btn{background:#74e1c1;color:#06131b;border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}.btn.alt{background:#263a55;color:#e6edf7}.bar{height:8px;background:#253b55;border-radius:6px;overflow:hidden}.fill{height:100%;background:#74e1c1}.small{font-size:12px}.mono{font-family:ui-monospace,monospace}.danger{color:#ff9e9e}pre{white-space:pre-wrap;max-height:270px;overflow:auto;color:#b9c9dc}</style></head>
<body><main><div class="top"><div><div class="mark">TESSERA</div><div class="muted">Autonomous capital infrastructure</div></div><span class="pill">MOCK PAPER · LIVE OFF</span></div>
<div class="grid"><section><div class="card"><div class="muted">CAPITAL PARLIAMENT</div><div id="status" class="metric">Ready</div><div id="event" class="muted">Inject an event to start the institutional loop.</div><br><button class="btn" onclick="run()">Run demo event</button> <button class="btn alt" onclick="replay()">Replay last run</button></div>
<div class="card" style="margin-top:18px"><div class="muted">AGENT COUNCIL</div><div id="agents"></div></div></section>
<section><div class="card"><div class="muted">PAPER PORTFOLIO</div><div id="portfolio" class="metric">$10,000.00</div><div id="positions" class="muted">No positions</div><br><div class="small muted">RISK CONSTITUTION · v1 · hard vetoes enabled</div><div class="bar"><div class="fill" style="width:31%"></div></div><br><button id="approve" class="btn" onclick="approve()" style="display:none">Approve paper order</button><button id="reject" class="btn alt" onclick="reject()" style="display:none">Reject</button></div>
<div class="card" style="margin-top:18px"><div class="muted">CAUSAL LEDGER</div><div id="ledger" class="small mono"></div></div></section></div></main>
<script>let current=null;async function get(u,o){let r=await fetch(u,o);return r.json()}function render(x){current=x;document.getElementById('status').textContent=x.status;document.getElementById('event').textContent=x.event.title+' · severity '+x.event.severity;document.getElementById('agents').innerHTML=x.agents.map(a=>`<div class="row"><span>${a.agent.replaceAll('_',' ')}</span><span class="pill">${a.decision}</span></div>`).join('');document.getElementById('approve').style.display=x.status==='AWAITING_APPROVAL'?'inline-block':'none';document.getElementById('reject').style.display=x.status==='AWAITING_APPROVAL'?'inline-block':'none';loadPortfolio();loadLedger()}async function run(){render(await get('/api/runs',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title:'Weekend AI export controls surprise',severity:.82,symbols:['NVDA','QQQ']})}))}async function approve(){render(await get('/api/runs/'+current.run_id+'/approve',{method:'POST'}))}async function reject(){render(await get('/api/runs/'+current.run_id+'/reject',{method:'POST'}))}async function replay(){if(current)render(await get('/api/replay',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({run_id:current.run_id})}))}async function loadPortfolio(){let p=await get('/api/portfolio');document.getElementById('portfolio').textContent='$'+Number(p.cash).toLocaleString(undefined,{minimumFractionDigits:2});document.getElementById('positions').textContent=p.positions.length?p.positions.map(x=>x.symbol+' '+x.quantity+' units').join(' · '):'No positions'}async function loadLedger(){let l=await get('/api/ledger');document.getElementById('ledger').textContent=l.valid?'✓ chain verified · '+l.entries.length+' entries':'✕ ledger invalid'}loadPortfolio();loadLedger()</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else (payload.encode() if isinstance(payload, str) else json.dumps(payload).encode())
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _principal(self, minimum_role: str = "viewer"):
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
            status = 403 if str(exc) == "Insufficient permissions" else 401
            self._send({"error": str(exc)}, status)
            return None

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/": return self._send(HTML, content_type="text/html; charset=utf-8")
        if path == "/api/health": return self._send(ORCH.health())
        if not self._principal("viewer"): return
        if path == "/api/portfolio": return self._send(ORCH.broker.snapshot())
        if path == "/api/ledger": return self._send({"valid": ORCH.ledger.verify(), "entries": ORCH.ledger.json()})
        if path == "/api/model-calls": return self._send({"calls": ORCH.store.list_model_calls()})
        if path == "/api/runs": return self._send({"runs": [x.json() for x in ORCH.runs.values()]})
        if path.startswith("/api/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            run = ORCH.runs.get(run_id)
            return self._send(run.json() if run else {"error": "run not found"}, 200 if run else 404)
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self._body()
            if path == "/api/auth/login":
                if not AUTH: return self._send({"error": "Authentication is disabled"}, 404)
                return self._send(AUTH.login(str(data.get("username", "")), str(data.get("password", ""))))
            if path == "/api/runs":
                if not self._principal("researcher"): return
                return self._send(ORCH.create_run(data, idempotency_key=self.headers.get("Idempotency-Key")).json(), 201)
            if path == "/api/replay":
                if not self._principal("researcher"): return
                return self._send(ORCH.replay(data["run_id"]).json(), 201)
            if path == "/api/risk/kill-switch":
                principal = self._principal("operator")
                if not principal: return
                return self._send(ORCH.set_kill_switch(bool(data.get("enabled")), bool(data.get("liquidate")), actor=principal["username"]).copy())
            if path.startswith("/api/runs/"):
                if not self._principal("operator"): return
                pieces = path.split("/")
                run_id, action = pieces[3], pieces[4]
                if action == "approve": return self._send(ORCH.approve(run_id).json())
                if action == "reject": return self._send(ORCH.reject(run_id).json())
                if action == "reconcile": return self._send(ORCH.reconcile(run_id).json())
                return self._send({"error": "unknown action"}, 404)
        except DomainError as exc:
            return self._send({"error": str(exc)}, 409)
        except AuthError as exc:
            return self._send({"error": str(exc)}, 401)
        except (KeyError, ValueError, json.JSONDecodeError, IndexError) as exc:
            return self._send({"error": str(exc)}, 400)
        return self._send({"error": "not found"}, 404)

    def log_message(self, *_):
        return


def serve(host: str | None = None, port: int | None = None):
    host = host or SETTINGS.host
    port = port or SETTINGS.port
    print(f"TESSERA running at http://{host}:{port} ({SETTINGS.broker_mode} mode)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
