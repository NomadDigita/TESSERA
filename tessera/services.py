from __future__ import annotations

from threading import RLock
from .config import Settings
from .domain import CausalLedger, ExecutionFrozen, OrderIntent, Run, now, uid
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
            if item["symbol"] not in {"NVDA", "QQQ", "TSLA", "AAPL"}:
                violations.append({"rule": "ASSET_NOT_ALLOWED", "observed": item["symbol"], "limit": "NVDA/QQQ/TSLA/AAPL", "severity": "hard"})
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


class AgentRuntime:
    names = ["market_intelligence", "cross_market_analyst", "market_twin_analyst", "adversarial_debater", "portfolio_constructor", "liquidity_guardian"]

    def run(self, event: dict) -> list[dict]:
        severity = float(event.get("severity", 0.72))
        title = event.get("title", "Unspecified market event")
        outputs = [
            {"agent": "market_intelligence", "decision": "EVENT_CONFIRMED", "confidence": round(min(0.98, severity + 0.12), 2), "finding": f"{title} is material enough to reprice tokenized equities."},
            {"agent": "cross_market_analyst", "decision": "RISK_ON_HEDGE", "confidence": 0.74, "finding": "Technology exposure and crypto liquidity are likely to move together."},
            {"agent": "market_twin_analyst", "decision": "UNDERPRICED_EVENT", "confidence": 0.78, "finding": "Market Twin fair-value range implies a positive repricing gap."},
            {"agent": "adversarial_debater", "decision": "CHALLENGE", "confidence": 0.68, "finding": "Weekend liquidity may make the apparent edge untradeable; cap notional."},
            {"agent": "portfolio_constructor", "decision": "PROPOSE_PAIR", "confidence": 0.76, "finding": "Use a capped long NVDA / smaller QQQ hedge proposal."},
            {"agent": "liquidity_guardian", "decision": "PASS_WITH_CAP", "confidence": 0.81, "finding": "Spread is acceptable under the demo liquidity profile with a $1,500 notional cap."},
        ]
        return outputs


class CapitalOrchestrator:
    def __init__(self, store: SQLiteStore | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or Settings(database_path=":memory:")
        self.store = store or SQLiteStore(":memory:")
        self.runs: dict[str, Run] = self.store.load_runs()
        self.ledger = CausalLedger(self.store.load_ledger(), self.store.append_ledger)
        self.broker = MockPaperBroker(self.store)
        self.risk = RiskConstitution(self.settings.max_order_notional, self.settings.require_human_approval,
                                     self.settings.max_gross_exposure, self.settings.max_single_asset_exposure)
        self.agents = AgentRuntime()
        self._lock = RLock()

    def create_run(self, event: dict, replay_of: str | None = None, idempotency_key: str | None = None) -> Run:
        with self._lock:
            if idempotency_key:
                existing = self.store.get_idempotent_resource("create_run", idempotency_key)
                if existing:
                    return self.runs[existing]
        run_id = uid()
        event = {"title": event.get("title", "Demo event"), "severity": float(event.get("severity", 0.72)), "symbols": event.get("symbols") or ["NVDA", "QQQ"]}
        run = Run(run_id, event, "RUNNING", now(), replay_of=replay_of)
        self.runs[run_id] = run
        self.ledger.append(run_id, "event", "system:event_ingestor", event)
        run.agents = self.agents.run(event)
        for output in run.agents:
            self.ledger.append(run_id, "agent_output", f"agent:{output['agent']}", output)
        proposal_orders = [{"symbol": "NVDA", "side": "BUY", "quantity": 5.0, "reference_price": 150.0, "reason": "Market Twin repricing gap", "sector": "Technology"}]
        run.proposals = [{"strategy": "AfterHoursEventRotation", "version": 1, "proposed_orders": proposal_orders, "confidence": 0.76}]
        parliament = {"decision": "approve", "vote_summary": {"approve": 4, "defer": 1, "reject": 1}, "confidence": 0.76, "dissent": ["Weekend liquidity may widen unexpectedly"], "proposed_orders": proposal_orders, "evidence_refs": ["market_twin:fair_value_range", "agent:liquidity_guardian"]}
        run.parliament = parliament
        self.ledger.append(run_id, "vote", "capital_parliament", parliament)
        run.risk = self.risk.evaluate(parliament, self.broker.snapshot(), event)
        self.ledger.append(run_id, "risk_check", "risk_constitution", run.risk)
        run.transition({"require_approval": "AWAITING_APPROVAL", "allow": "APPROVED", "deny": "REJECTED"}[run.risk["decision"]])
        self.store.save_run(run)
        if idempotency_key:
            self.store.save_idempotency_key("create_run", idempotency_key, run_id)
        return run

    def approve(self, run_id: str) -> Run:
        run = self.runs[run_id]
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
        run.transition("EXECUTED")
        self.ledger.append(run_id, "approval", "operator", {"approved": True})
        self.ledger.append(run_id, "fill", "execution_engine", receipt)
        run.autopsy = {"thesis": "Event-driven repricing gap", "expected": "Positive NVDA repricing", "realized": "Paper fill completed", "risk_controls": "Notional cap applied", "lesson": "Monitor spread before scaling"}
        self.ledger.append(run_id, "outcome", "portfolio_autopsy", run.autopsy)
        self.store.save_run(run)
        return run

    def reject(self, run_id: str) -> Run:
        run = self.runs[run_id]
        if run.status == "REJECTED":
            return run
        run.transition("REJECTED")
        self.ledger.append(run_id, "approval", "operator", {"approved": False})
        self.store.save_run(run)
        return run

    def replay(self, run_id: str) -> Run:
        original = self.runs[run_id]
        return self.create_run(dict(original.event), replay_of=run_id)

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
        return {"status": "ok", "environment": self.settings.environment, "mode": self.settings.broker_mode, "live_trading": self.settings.live_trading_enabled, "ledger_valid": self.ledger.verify(), "runs": len(self.runs), "kill_switch": self.kill_switch_enabled, "database": "sqlite"}

    def close(self) -> None:
        self.store.close()
