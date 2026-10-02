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

Intelligence endpoints:

- `GET|POST /api/strategies` — list or publish immutable Strategy Genome versions
- `POST /api/market/observations` — record source-attributed market evidence
- `POST /api/market/relationships` — add a weighted Market Graph edge
- `GET /api/market-twin/{symbol}` — calculate an evidence-bound fair-value range
- `GET /api/market-graph/{asset}` — inspect an asset's causal relationships

The Market Twin is deterministic and returns `insufficient_data` instead of
inventing a forecast when fewer than three observations are available.

Durable worker mode:

- `POST /api/runs/async` enqueues a decision run and returns `202 Accepted`.
- `GET /api/jobs/{job_id}` reports queued, running, retrying, failed, or succeeded state.
- `python -m tessera.worker` runs the separately deployable worker.

Jobs use atomic leases, bounded retries, idempotent run creation, and a database-
serialized causal ledger. Docker Compose starts both API and worker processes.

## Production data plane

Production mode requires PostgreSQL with pgvector and Redis. PostgreSQL is the
system of record and serializes ledger writes with an advisory transaction lock.
Redis Streams wakes workers through a consumer group; durable job state, leases,
and retries remain in PostgreSQL so Redis message loss cannot lose a decision run.

```dotenv
TESSERA_ENV=production
DATABASE_URL=postgresql://tessera:strong-password@postgres:5432/tessera
REDIS_URL=redis://redis:6379/0
TESSERA_AUTH_ENABLED=true
TESSERA_SESSION_SECRET=<at-least-32-random-characters>
TESSERA_ADMIN_PASSWORD=<at-least-12-characters>
```

`docker compose up --build` starts the API, worker, pgvector PostgreSQL, and
persistent Redis and S3-compatible object storage services. Replace all example
credentials before deployment.

Replay evidence is persisted as canonical JSON with a SHA-256 integrity reference:

- `GET /api/replays` lists replay records.
- `GET /api/replays/{replay_id}` returns artifact metadata.
- `GET /api/replays/{replay_id}/bundle` verifies and returns the pinned evidence bundle.

Each bundle contains original and replay run snapshots, strategy versions, model-call
audit records, Constitution version, and the relevant causal-ledger entries.

See [operations](docs/operations.md) and [security](docs/security.md) for deployment and incident procedures.
