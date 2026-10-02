from __future__ import annotations

from dataclasses import asdict
from .domain import CausalLedger, OrderIntent, Run, now, uid


class MockPaperBroker:
    def __init__(self) -> None:
        self.cash = 10000.0
        self.positions: dict[str, dict] = {}

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
        return {"order_id": uid(), "symbol": order.symbol, "side": order.side, "quantity": order.quantity, "fill_price": order.reference_price, "status": "FILLED", "notional": round(notional, 2), "filled_at": now()}

    def cancel(self, symbol: str) -> dict:
        position = self.positions.get(symbol)
        if not position or position["quantity"] == 0:
            return {"status": "NO_POSITION", "symbol": symbol}
        side = "SELL" if position["quantity"] > 0 else "BUY"
        order = OrderIntent(symbol, side, abs(position["quantity"]), position["avg_price"], "Risk Constitution liquidation")
        receipt = self.place(order)
        self.positions[symbol]["quantity"] = 0.0
        return {"status": "LIQUIDATED", "symbol": symbol, "receipt": receipt}


class RiskConstitution:
    version = "constitution-v1"

    def evaluate(self, proposal: dict, portfolio: dict, event: dict) -> dict:
        violations = []
        orders = proposal.get("proposed_orders", [])
        if not orders:
            violations.append({"rule": "NO_ORDER", "observed": 0, "limit": 1, "severity": "hard"})
        for item in orders:
            notional = item["quantity"] * item["reference_price"]
            if notional > 1500:
                violations.append({"rule": "MAX_ORDER_NOTIONAL", "observed": round(notional, 2), "limit": 1500, "severity": "hard"})
            if item["symbol"] not in {"NVDA", "QQQ", "TSLA", "AAPL"}:
                violations.append({"rule": "ASSET_NOT_ALLOWED", "observed": item["symbol"], "limit": "NVDA/QQQ/TSLA/AAPL", "severity": "hard"})
        if float(event.get("severity", 0.5)) > 0.95:
            violations.append({"rule": "EXTREME_EVENT_REQUIRES_APPROVAL", "observed": event.get("severity"), "limit": 0.95, "severity": "soft"})
        hard = any(x["severity"] == "hard" for x in violations)
        decision = "deny" if hard else "require_approval"
        return {"decision": decision, "violations": violations, "approved_orders": [] if hard else orders, "constitution_version": self.version}


class AgentRuntime:
    names = ["market_intelligence", "cross_market_analyst", "market_twin_analyst", "adversarial_debater", "portfolio_constructor", "liquidity_guardian"]

    def run(self, event: dict) -> list[dict]:
        severity = float(event.get("severity", 0.72))
        title = event.get("title", "Unspecified market event")
        symbols = event.get("symbols") or ["NVDA", "QQQ"]
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
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}
        self.ledger = CausalLedger()
        self.broker = MockPaperBroker()
        self.risk = RiskConstitution()
        self.agents = AgentRuntime()

    def create_run(self, event: dict, replay_of: str | None = None) -> Run:
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
        parliament = {"decision": "approve", "vote_summary": {"approve": 4, "defer": 1, "reject": 1}, "confidence": 0.76, "dissent": ["Weekend liquidity may widen unexpectedly"], "proposed_orders": proposal_orders, "evidence_refs": ["market_twin:fai_value_range", "agent:liquidity_guardian"]}
        run.parliament = parliament
        self.ledger.append(run_id, "vote", "capital_parliament", parliament)
        run.risk = self.risk.evaluate(parliament, self.broker.snapshot(), event)
        self.ledger.append(run_id, "risk_check", "risk_constitution", run.risk)
        run.status = "AWAITING_APPROVAL" if run.risk["decision"] == "require_approval" else "REJECTED"
        return run

    def approve(self, run_id: str) -> Run:
        run = self.runs[run_id]
        if run.status != "AWAITING_APPROVAL":
            return run
        order = run.risk["approved_orders"][0]
        receipt = self.broker.place(OrderIntent(**order))
        run.order = receipt
        run.status = "EXECUTED"
        self.ledger.append(run_id, "approval", "operator", {"approved": True})
        self.ledger.append(run_id, "fill", "execution_engine", receipt)
        run.autopsy = {"thesis": "Event-driven repricing gap", "expected": "Positive NVDA repricing", "realized": "Paper fill completed", "risk_controls": "Notional cap applied", "lesson": "Monitor spread before scaling"}
        self.ledger.append(run_id, "outcome", "portfolio_autopsy", run.autopsy)
        return run

    def reject(self, run_id: str) -> Run:
        run = self.runs[run_id]
        run.status = "REJECTED"
        self.ledger.append(run_id, "approval", "operator", {"approved": False})
        return run

    def replay(self, run_id: str) -> Run:
        original = self.runs[run_id]
        return self.create_run(dict(original.event), replay_of=run_id)

    def health(self) -> dict:
        return {"status": "ok", "mode": "mock-paper", "live_trading": False, "ledger_valid": self.ledger.verify(), "runs": len(self.runs), "kill_switch": False}
