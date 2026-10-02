# TESSERA Operations Runbook

## Required production services

- PostgreSQL 16 with pgvector is the authoritative state and audit store.
- Redis 7 Streams provides worker wakeups; PostgreSQL retains durable job state.
- API and worker use the same `DATABASE_URL` and `REDIS_URL`.
- S3-compatible object storage retains immutable replay evidence bundles; configure
  endpoint, bucket, access key, secret key, and region consistently on API and worker.
- Use managed TLS endpoints (`sslmode=require`, `rediss://`) outside the private
  container network, rotate passwords, and do not use Compose example credentials.

Production startup fails closed when authentication, PostgreSQL, or Redis is absent.

## Runtime modes

- `mock-paper`: deterministic local and staging execution. No external orders.
- `bitget-demo`: Bitget UTA demo API only. Every private request carries `paptrading: 1`.
- Live trading is rejected during configuration validation.

## Health endpoints

- `/api/health`: process liveness and public safety mode.
- `/api/ready`: database, event bus, ledger, and live-trading safety readiness. Returns 503 on failure.
- `/metrics`: Prometheus-compatible process metrics without portfolio or credential data.

## Startup

1. Copy `.env.example` to `.env` and fill secrets locally.
2. Keep `TESSERA_LIVE_TRADING_ENABLED=false`.
3. For production, enable authentication and provide a 32+ character session secret.
4. Bootstrap the first administrator with a 12+ character password, then rotate the environment value after provisioning.
5. Run `docker compose up --build -d`.
6. Confirm `/api/ready` returns 200 and `tessera_ledger` remains valid in the console.

## Incident controls

1. Activate **Freeze execution** in the console. This persists across restarts.
2. Do not request automatic Bitget liquidation until connected-symbol quantity semantics are validated.
3. Preserve PostgreSQL, Redis persistence, and application logs. SQLite is only the local fallback.
4. Inspect the Causal Ledger, request IDs, model-call audit, and exchange order status.
5. Resume only after the root cause is documented and risk limits are reviewed.

## Backup and recovery

- Stop writes or freeze execution before copying the SQLite database.
- Back up `/var/lib/tessera/tessera.db` and its WAL/SHM companions together.
- Restore into a new volume, start in `mock-paper`, verify `/api/ready`, ledger integrity, runs, and positions, then reconnect external demo providers.

## Secret rotation

- Bitget and Qwen secrets are environment-only and never returned by APIs.
- Rotating the session secret invalidates every active session.
- After rotating Bitget credentials, validate account reads before permitting approvals.
