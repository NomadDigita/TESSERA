# Security Model

## Sessions and abuse controls

- Tokens are HMAC-signed, expiring, and backed by revocable database sessions.
- Deactivation or role changes revoke all sessions immediately.
- Redis applies fixed-window limits consistently across API replicas; local mode
  uses an in-process limiter with the same contract.
- Login keys combine source address with a hash of the submitted username, avoiding
  plaintext identity data in Redis keys.
- Administrative identity changes require `admin` and enter the Causal Ledger.

## Trust boundaries

- News and user event text are untrusted data and are bounded before model use.
- LLM outputs are advisory and schema-validated.
- The deterministic Risk Constitution is the sole gate into execution.
- Bitget credentials remain server-side and demo-only.
- Browser sessions contain signed, expiring bearer tokens in session storage.

## Roles

| Role | Capabilities |
| --- | --- |
| viewer | Read dashboards, runs, portfolio, and ledger |
| researcher | Viewer access plus create and replay decisions |
| operator | Researcher access plus approvals, rejection, reconciliation, and kill switch |
| admin | Full application administration |

## Controls

- Scrypt password hashing with random salts.
- HMAC-SHA256 signed sessions with expiration and permission-change invalidation.
- Content Security Policy, frame denial, MIME sniff prevention, no-referrer policy.
- One-megabyte request limit and bounded model inputs.
- Idempotent run and execution transitions.
- Persistent kill switch and append-only hash-chained evidence.
- JSON logs redact known credential and token field names.
- Container runs as non-root with all Linux capabilities dropped.

## Current safety restriction

Real-money execution is intentionally unavailable. A future live adapter requires a separate security review, exchange reconciliation tests, position-mode verification, and explicit product authorization.
