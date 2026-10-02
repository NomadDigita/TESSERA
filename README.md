# TESSERA — Autonomous Capital Infrastructure

TESSERA is a controlled multi-agent investment institution for tokenized US equities and cross-market portfolios.

```text
event → specialist agents → Capital Parliament → Risk Constitution
      → human approval → paper/demo execution → Causal Ledger → autopsy/replay
```

LLMs research and recommend. Deterministic policy controls capital. No model can bypass portfolio limits, permissions, the kill switch, or human approval.

## Current capabilities

- Seven-agent structured research council with Qwen and deterministic providers
- Evidence-weighted Capital Parliament
- Portfolio-aware Risk Constitution with hard vetoes
- Persistent paper portfolio and Bitget UTA V3 demo adapter
- Tamper-evident Causal Ledger and deterministic replay
- Fill reconciliation and post-trade autopsy
- Authentication, role-based permissions, and expiring sessions
- Operational web console, readiness probes, metrics, and JSON logs
- SQLite durability, restart recovery, Docker packaging, and CI

Real-money execution is intentionally disabled.

## Run locally

Python 3.10+ is required. No third-party runtime dependency is needed.

```powershell
Copy-Item .env.example .env
python -m tessera
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787).

Or use Docker:

```powershell
docker compose up --build
```

## Production authentication

Set these values in `.env` before starting a production environment:

```dotenv
TESSERA_ENV=production
TESSERA_AUTH_ENABLED=true
TESSERA_SESSION_SECRET=<at-least-32-random-characters>
TESSERA_ADMIN_USERNAME=admin
TESSERA_ADMIN_PASSWORD=<at-least-12-characters>
```

Remove the bootstrap password from the deployment environment after the first administrator has been persisted.

## External providers

Qwen:

```dotenv
TESSERA_LLM_PROVIDER=qwen
DASHSCOPE_API_KEY=<secret>
QWEN_MODEL=qwen-plus
```

Bitget demo:

```dotenv
TESSERA_BROKER_MODE=bitget-demo
BITGET_API_KEY=<demo-key>
BITGET_API_SECRET=<demo-secret>
BITGET_API_PASSPHRASE=<demo-passphrase>
BITGET_BASE_URL=https://api.bitget.com
```

Create the API key while the Bitget account is in Demo mode. The client automatically attaches `paptrading: 1` to every private request.

## Verification

```powershell
python -m compileall -q tessera tests
python -m unittest discover -s tests -v
```

Operational endpoints:

- `GET /api/health` — process liveness and safety mode
- `GET /api/ready` — database and ledger readiness
- `GET /metrics` — Prometheus-compatible metrics

See [operations](docs/operations.md) and [security](docs/security.md) for deployment and incident procedures.
