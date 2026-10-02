# TESSERA — Autonomous Capital Infrastructure

TESSERA is a safe, deterministic vertical slice of an autonomous investment institution. It demonstrates:

`event → multi-agent debate → portfolio proposal → Risk Constitution → human approval → paper execution → Causal Ledger → replay`

## Run

Use the bundled Python runtime if Python is not on PATH:

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m tessera
```

Then open http://127.0.0.1:8787.

To inject a scenario from PowerShell:

```powershell
$body = @{ title = "Weekend AI export controls surprise"; severity = 0.82; symbols = @("NVDA", "QQQ") } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8787/api/runs -Method Post -ContentType 'application/json' -Body $body
```

The default broker is `mock-paper`. Live Bitget credentials are intentionally not supported by this MVP.

## API

- `POST /api/runs` — create an event-driven investment run
- `GET /api/runs` — list runs
- `GET /api/runs/{id}` — inspect the full run
- `POST /api/runs/{id}/approve` — approve a paper order
- `POST /api/runs/{id}/reject` — reject a proposal
- `POST /api/runs/{id}/cancel` — cancel a paper position
- `POST /api/replay` — deterministic replay of a run
- `GET /api/portfolio` — paper portfolio
- `GET /api/ledger` — tamper-evident causal ledger
- `GET /api/health` — health and safety state

## What is implemented

Implemented: six deterministic agents, Capital Parliament, Market Twin estimate, Strategy Genome, hard Risk Constitution, human approval, mock paper broker, portfolio autopsy, replay, and hash-chained ledger.

Adapter seams are ready for Qwen and Bitget, but external credentials and live trading are deliberately excluded from this first slice.
