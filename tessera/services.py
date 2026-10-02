from __future__ import annotations

from threading import RLock
import re
from .agents import AgentCouncil, CapitalParliament
from .bitget import BitgetCredentials, BitgetDemoClient
from .config import Settings
from .domain import CausalLedger, ExecutionFrozen, OrderIntent, Run, now, uid
from .llm import DeterministicProvider, LLMRouter, QwenProvider
from .intelligence import MarketGraph, MarketTwin, StrategyGenomeRegistry
from .events import NullEventBus
from .artifacts import create_artifact_store
from .observability import METRICS
from .storage import SQLiteStore


class MockPaperBroker:
    def __init__(self, store: SQLiteStore | None = None) -> None:
        self.store = store
        state = store.get_state("paper_portfolio", {"cash": 10000.0, "positions": {}}) if store else {"cash": 10000.0, "positions": {}}
        self.cash = float(state["cash"])
        self.positions: dict[str, dict] = state["positions"]

    def _persist(self) -> None:
        if self.store:
            self.store.set_state("paper_portfolio", {"cash": self.cash, "positions": self.positions})

    def snapshot(self) -> dict:
        return {"cash": round(self.cash, 2), "positions": list(self.positions.values()), "mode": "mock-paper"}

    def place(self, order: OrderIntent) -> dict:
        notional = order.quantity * order.reference_price
        signed = notional if order.side == "BUY" else -notional
        self.cash -= signed
        current = self.positions.get(order.symbol, {"symbol": order.symbol, "quantity": 0.0, "avg_price": order.reference_price})
        current["quantity"] = round(current["quantity"] + (order.quantity if order.side == "BUY" else -order.quantity), 6)
        current["avg_price"] = order.reference_price
        self.positions[order.symbol] = current
        self._persist()
        return {"order_id": uid(), "symbol": order.symbol, "side": order.side, "quantity": order.quantity, "fill_price": order.reference_price, "status": "FILLED", "notional": round(notional, 2), "filled_at": now()}

    def cancel(self, symbol: str) -> dict:
        position = self.positions.get(symbol)
        if not position or position["quantity"] == 0:
            return {"status": "NO_POSITION", "symbol": symbol}
        side = "SELL" if position["quantity"] > 0 else "BUY"
        order = OrderIntent(symbol, side, abs(position["quantity"]), position["avg_price"], "Risk Constitution liquidation")
        receipt = self.place(order)
        self.positions[symbol]["quantity"] = 0.0
        self._persist()
        return {"status": "LIQUIDATED", "symbol": symbol, "receipt": receipt}

    def liquidate_all(self) -> list[dict]:
        return [self.cancel(symbol) for symbol, position in list(self.positions.items()) if position["quantity"] != 0]

    def order_status(self, receipt: dict) -> dict:
        return receipt


class BitgetDemoBroker:
    """Demo-only exchange broker. Submission and fills are deliberately separate states."""

    def __init__(self, client: BitgetDemoClient) -> None:
        self.client = client

    def snapshot(self) -> dict:
        assets = self.client.get_assets().get("data") or []
        positions = self.client.get_positions().get("data") or []
        return {"cash": 0.0, "assets": assets, "positions": self._positions(positions), "mode": "bitget-demo"}

    @staticmethod
    def _positions(items: list[dict]) -> list[dict]:
        normalized = []
        for item in items:
            normalized.append({
                "symbol": item.get("symbol", ""),
                "quantity": float(item.get("total", item.get("qty", item.get("position", 0))) or 0),
                "avg_price": float(item.get("openPriceAvg", item.get("avgPrice", 0)) or 0),
            })
        return normalized

    def place(self, order: OrderIntent) -> dict:
        client_oid = f"tessera-{uid().replace('-', '')[:20]}"
        result = self.client.place_order(
            symbol=order.symbol, side=order.side.lower(), quantity=order.quantity,
            order_type="limit", price=order.reference_price, client_oid=client_oid,
        )
        data = result["data"]
        return {
            "order_id": data["orderId"], "client_oid": data.get("clientOid") or client_oid,
            "symbol": order.symbol, "side": order.side, "quantity": order.quantity,
            "limit_price": order.reference_price, "status": "SUBMITTED", "submitted_at": now(),
        }

    def order_status(self, receipt: dict) -> dict:
        result = self.client.get_order(order_id=receipt["order_id"])
        data = result["data"]
        status = str(data.get("orderStatus", "unknown")).lower()
        mapped = {"filled": "FILLED", "cancelled": "CANCELLED", "canceled": "CANCELLED", "rejected": "FAILED"}.get(status, "SUBMITTED")
        return {**receipt, "status": mapped, "exchange_status": status, "fill_price": float(data.get("avgPrice") or 0)}

    def cancel(self, symbol: str, receipt: dict | None = None) -> dict:
        if not receipt:
            return {"status": "NO_ORDER", "symbol": symbol}
        result = self.client.cancel_order(symbol=symbol, order_id=receipt["order_id"])
        return {"status": "CANCELLED", "symbol": symbol, "exchange": result["data"]}

    def liquidate_all(self) -> list[dict]:
        # Automatic market liquidation is intentionally disabled until symbol-specific
        # quantity semantics are verified against the connected demo account.
        return []


class RiskConstitution:
    version = "constitution-v1"

    def __init__(self, max_order_notional: float = 1500.0, require_human_approval: bool = True,
                 max_gross_exposure: float = 5000.0, max_single_asset_exposure: float = 2500.0) -> None:
        self.max_order_notional = max_order_notional
        self.require_human_approval = require_human_approval
        self.max_gross_exposure = max_gross_exposure
        self.max_single_asset_exposure = max_single_asset_exposure

    def evaluate(self, proposal: dict, portfolio: dict, event: dict) -> dict:
        violations = []
        orders = proposal.get("proposed_orders", [])
        if not orders:
            violations.append({"rule": "NO_ORDER", "observed": 0, "limit": 1, "severity": "hard"})
        for item in orders:
            notional = item["quantity"] * item["reference_price"]
            if notional > self.max_order_notional:
                violations.append({"rule": "MAX_ORDER_NOTIONAL", "observed": round(notional, 2), "limit": self.max_order_notional, "severity": "hard"})
            symbol = item["symbol"]
            if symbol not in {"NVDA", "QQQ", "TSLA", "AAPL"} and not re.fullmatch(r"r[A-Z]{1,10}USDT", symbol):
                violations.append({"rule": "ASSET_NOT_ALLOWED", "observed": symbol, "limit": "approved symbols or r<US_TICKER>USDT", "severity": "hard"})
            current = next((p for p in portfolio.get("positions", []) if p["symbol"] == item["symbol"]), None)
            current_exposure = abs(current["quantity"] * current["avg_price"]) if current else 0.0
            if current_exposure + notional > self.max_single_asset_exposure:
                violations.append({"rule": "MAX_SINGLE_ASSET_EXPOSURE", "observed": round(current_exposure + notional, 2), "limit": self.max_single_asset_exposure, "severity": "hard"})
        gross = sum(abs(p["quantity"] * p["avg_price"]) for p in portfolio.get("positions", []))
        proposed = sum(abs(x["quantity"] * x["reference_price"]) for x in orders)
        if gross + proposed > self.max_gross_exposure:
            violations.append({"rule": "MAX_GROSS_EXPOSURE", "observed": round(gross + proposed, 2), "limit": self.max_gross_exposure, "severity": "hard"})
        if float(event.get("severity", 0.5)) > 0.95:
            violations.append({"rule": "EXTREME_EVENT_REQUIRES_APPROVAL", "observed": event.get("severity"), "limit": 0.95, "severity": "soft"})
        hard = any(x["severity"] == "hard" for x in violations)
        decision = "deny" if hard else ("require_approval" if self.require_human_approval else "allow")
        return {"decision": decision, "violations": violations, "approved_orders": [] if hard else orders, "constitution_version": self.version}


class CapitalOrchestrator:
    def __init__(self, store: SQLiteStore | None = None, settings: Settings | None = None, broker=None,
                 event_bus=None, artifact_store=None) -> None:
        self.settings = settings or Settings(database_path=":memory:")
        self.store = store or SQLiteStore(":memory:")
        self.event_bus = event_bus or NullEventBus()
        self.artifact_store = artifact_store or create_artifact_store(self.settings)
        self.runs: dict[str, Run] = self.store.load_runs()
        self.ledger = CausalLedger(self.store.load_ledger(), self.store.append_ledger, self.store.load_ledger)
        if broker is not None:
            self.broker = broker
        elif self.settings.broker_mode == "bitget-demo":
            credentials = BitgetCredentials(self.settings.bitget_api_key, self.settings.bitget_api_secret, self.settings.bitget_api_passphrase)
            self.broker = BitgetDemoBroker(BitgetDemoClient(credentials, self.settings.bitget_base_url))
        else:
            self.broker = MockPaperBroker(self.store)
        self.risk = RiskConstitution(self.settings.max_order_notional, self.settings.require_human_approval,
                                     self.settings.max_gross_exposure, self.settings.max_single_asset_exposure)
        provider = QwenProvider(self.settings.dashscope_api_key, self.settings.qwen_base_url, self.settings.qwen_model) if self.settings.llm_provider == "qwen" else DeterministicProvider()
        self.agents = AgentCouncil(LLMRouter(provider, self.store.record_model_call))
        self.parliament = CapitalParliament()
        self.market_graph = MarketGraph(self.store)
        self.market_twin = MarketTwin(self.store, self.market_graph)
        self.strategies = StrategyGenomeRegistry(self.store)
        self._ensure_default_strategy()
        self._lock = RLock()

    def _ensure_default_strategy(self) -> None:
        strategy_id = "after-hours-event-rotation"
        if self.store.latest_strategy_version(strategy_id):
            return
        self.strategies.publish({
            "strategy_id": strategy_id,
            "name": "AfterHoursEventRotation",
            "hypothesis": "Tokenized equities can reprice material events before native markets reopen.",
            "signals": ["event_severity", "cross_market_confirmation", "fair_value_gap"],
            "universe": ["NVDA", "TSLA", "QQQ", "AAPL"],
            "holding_period": "1h-24h", "risk_profile": "medium",
            "capital_requirements": {"minimum": 100, "maximum": 1500},
            "constraints": {"max_position_pct": 0.2, "max_drawdown_pct": 0.05},
        })

    def create_run(self, event: dict, replay_of: str | None = None, idempotency_key: str | None = None) -> Run:
        with self._lock:
            if idempotency_key:
                existing = self.store.get_idempotent_resource("create_run", idempotency_key)
                if existing:
                    return self._get_run(existing)
        run_id = uid()
        event = {"title": event.get("title", "Demo event"), "severity": float(event.get("severity", 0.72)), "symbols": event.get("symbols") or ["NVDA", "QQQ"], "observations": event.get("observations") or []}
        run = Run(run_id, event, "RUNNING", now(), replay_of=replay_of)
        self.runs[run_id] = run
        self.ledger.append(run_id, "event", "system:event_ingestor", event)
        for observation in event["observations"]:
            recorded = self.market_twin.observe(**observation)
            self.ledger.append(run_id, "observation", "market_twin", recorded)
        twin = self.market_twin.estimate(event["symbols"][0], event["severity"])
        self.ledger.append(run_id, "market_twin", "market_twin", twin)
        run.agents = self.agents.run(event)
        for output in run.agents:
            self.ledger.append(run_id, "agent_output", f"agent:{output['agent']}", output)
        parliament = self.parliament.deliberate(run.agents, event)
        run.proposals = [{"strategy_id": "after-hours-event-rotation", "strategy": "AfterHoursEventRotation", "version": 1, "proposed_orders": parliament["proposed_orders"], "confidence": parliament["confidence"], "market_twin": twin}]
        run.parliament = parliament
        self.ledger.append(run_id, "vote", "capital_parliament", parliament)
        run.risk = self.risk.evaluate(parliament, self.broker.snapshot(), event)
        self.ledger.append(run_id, "risk_check", "risk_constitution", run.risk)
        run.transition({"require_approval": "AWAITING_APPROVAL", "allow": "APPROVED", "deny": "REJECTED"}[run.risk["decision"]])
        self.store.save_run(run)
        if idempotency_key:
            self.store.save_idempotency_key("create_run", idempotency_key, run_id)
        METRICS.inc("decision_runs_total", labels={"status": run.status})
        return run

    def refresh_runs(self) -> dict[str, Run]:
        self.runs = self.store.load_runs()
        return self.runs

    def _get_run(self, run_id: str) -> Run:
        runs = self.refresh_runs()
        if run_id not in runs:
            raise KeyError(run_id)
        return runs[run_id]

    def enqueue_run(self, event: dict) -> dict:
        job_id = uid()
        timestamp = now()
        job = {"job_id": job_id, "job_type": "create_run", "payload": event,
               "available_at": timestamp, "created_at": timestamp}
        self.store.enqueue_job(job)
        self.event_bus.publish("tessera:jobs", {"job_id": job_id, "job_type": "create_run"})
        self.ledger.append("SYSTEM", "job_queued", "capital_orchestrator", {"job_id": job_id, "job_type": "create_run"})
        return self.store.get_job(job_id)

    def approve(self, run_id: str) -> Run:
        run = self._get_run(run_id)
        if run.status == "EXECUTED":
            return run
        if self.kill_switch_enabled:
            raise ExecutionFrozen("Execution is frozen by the global kill switch")
        if run.status not in {"AWAITING_APPROVAL", "APPROVED"}:
            return run
        run.transition("EXECUTING")
        self.store.save_run(run)
        order = run.risk["approved_orders"][0]
        receipt = self.broker.place(OrderIntent(**order))
        run.order = receipt
        run.transition("EXECUTED" if receipt["status"] == "FILLED" else "SUBMITTED")
        self.ledger.append(run_id, "approval", "operator", {"approved": True})
        self.ledger.append(run_id, "fill" if receipt["status"] == "FILLED" else "order", "execution_engine", receipt)
        if receipt["status"] == "FILLED":
            self._autopsy(run)
        self.store.save_run(run)
        METRICS.inc("execution_actions_total", labels={"status": run.status})
        return run

    def reconcile(self, run_id: str) -> Run:
        run = self._get_run(run_id)
        if run.status != "SUBMITTED" or not run.order:
            return run
        receipt = self.broker.order_status(run.order)
        run.order = receipt
        if receipt["status"] == "FILLED":
            run.transition("EXECUTED")
            self.ledger.append(run_id, "fill", "execution_engine", receipt)
            self._autopsy(run)
        elif receipt["status"] in {"FAILED", "CANCELLED"}:
            run.transition("FAILED" if receipt["status"] == "FAILED" else "CANCELLED")
            self.ledger.append(run_id, "order_terminal", "execution_engine", receipt)
        self.store.save_run(run)
        return run

    def _autopsy(self, run: Run) -> None:
        run.autopsy = {"thesis": "Event-driven repricing gap", "expected": "Positive repricing", "realized": "Fill confirmed", "risk_controls": "Notional cap applied", "lesson": "Monitor spread before scaling"}
        self.ledger.append(run.run_id, "outcome", "portfolio_autopsy", run.autopsy)

    def reject(self, run_id: str) -> Run:
        run = self._get_run(run_id)
        if run.status == "REJECTED":
            return run
        run.transition("REJECTED")
        self.ledger.append(run_id, "approval", "operator", {"approved": False})
        self.store.save_run(run)
        return run

    def replay(self, run_id: str) -> Run:
        original = self._get_run(run_id)
        replay_run = self.create_run(dict(original.event), replay_of=run_id)
        replay_id = uid()
        bundle = {
            "schema": "tessera-replay-bundle-v1", "replay_id": replay_id,
            "created_at": now(), "original_run": original.json(), "replay_run": replay_run.json(),
            "strategy_versions": self.strategies.list(),
            "constitution_version": self.risk.version,
            "model_calls": self.store.list_model_calls(limit=1000),
            "ledger_entries": [entry for entry in self.ledger.json()
                               if entry["run_id"] in {original.run_id, replay_run.run_id}],
        }
        artifact = self.artifact_store.put_json(f"replays/{replay_id}.json", bundle)
        record = {"replay_id": replay_id, "original_run_id": original.run_id,
                  "replay_run_id": replay_run.run_id, "created_at": bundle["created_at"],
                  "artifact": artifact, "status": "complete"}
        self.store.save_replay(record)
        self.ledger.append(replay_run.run_id, "replay_bundle", "replay_director", record)
        return replay_run

    def replay_bundle(self, replay_id: str) -> dict:
        replay = self.store.get_replay(replay_id)
        if not replay:
            raise KeyError(replay_id)
        bundle = self.artifact_store.get_json(replay["artifact"]["key"])
        from .artifacts import canonical_json
        import hashlib
        observed = hashlib.sha256(canonical_json(bundle)).hexdigest()
        if observed != replay["artifact"]["sha256"]:
            raise ValueError("Replay bundle integrity check failed")
        return bundle

    @property
    def kill_switch_enabled(self) -> bool:
        return bool(self.store.get_state("kill_switch", {"enabled": False})["enabled"])

    def set_kill_switch(self, enabled: bool, liquidate: bool = False, actor: str = "operator") -> dict:
        with self._lock:
            liquidations = self.broker.liquidate_all() if enabled and liquidate else []
            state = {"enabled": enabled, "updated_at": now(), "actor": actor, "liquidations": liquidations}
            self.store.set_state("kill_switch", state)
            self.ledger.append("SYSTEM", "risk_control", "risk_constitution", state)
            return state

    def health(self) -> dict:
        database = "postgresql" if self.settings.database_url else "sqlite"
        event_bus = "redis-streams" if self.settings.redis_url else "local-polling"
        return {"status": "ok", "environment": self.settings.environment, "mode": self.settings.broker_mode, "live_trading": self.settings.live_trading_enabled, "ledger_valid": self.ledger.verify(), "runs": len(self.runs), "kill_switch": self.kill_switch_enabled, "database": database, "event_bus": event_bus, "queue": self.store.queue_depth()}

    def readiness(self) -> tuple[bool, dict]:
        checks = {"database": self.store.ping(), "event_bus": self.event_bus.ping(),
                  "artifact_store": self.artifact_store.ping(), "ledger": self.ledger.verify(),
                  "live_trading_disabled": not self.settings.live_trading_enabled}
        ready = all(checks.values())
        return ready, {"status": "ready" if ready else "not_ready", "checks": checks}

    def close(self) -> None:
        self.event_bus.close()
        self.store.close()
