from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from statistics import mean, pstdev

from .domain import now, uid


@dataclass(frozen=True)
class MarketObservation:
    observation_id: str
    symbol: str
    price: float
    observed_at: str
    source: str = "injected"
    volatility: float | None = None
    liquidity_score: float | None = None

    def json(self) -> dict:
        return asdict(self)


class MarketGraph:
    """Small, explainable relationship graph backed by the system of record."""

    def __init__(self, store) -> None:
        self.store = store

    def connect(self, source: str, target: str, relation: str, weight: float,
                evidence: dict | None = None) -> dict:
        if not 0 <= weight <= 1:
            raise ValueError("Relationship weight must be between 0 and 1")
        edge = {
            "edge_id": uid(), "source": source.upper(), "target": target.upper(),
            "relation": relation, "weight": float(weight), "evidence": evidence or {},
            "created_at": now(),
        }
        self.store.save_market_edge(edge)
        return edge

    def neighbors(self, asset: str) -> list[dict]:
        return self.store.list_market_edges(asset.upper())


class MarketTwin:
    """Deterministic fair-value estimator; uncertainty expands when evidence is thin."""

    minimum_observations = 3

    def __init__(self, store, graph: MarketGraph) -> None:
        self.store = store
        self.graph = graph

    def observe(self, symbol: str, price: float, observed_at: str | None = None,
                source: str = "injected", volatility: float | None = None,
                liquidity_score: float | None = None) -> dict:
        if price <= 0:
            raise ValueError("Observed price must be positive")
        item = MarketObservation(uid(), symbol.upper(), float(price), observed_at or now(), source,
                                 volatility, liquidity_score)
        self.store.save_market_observation(item.json())
        return item.json()

    def estimate(self, symbol: str, event_severity: float = 0.5) -> dict:
        symbol = symbol.upper()
        observations = self.store.list_market_observations(symbol, limit=100)
        if len(observations) < self.minimum_observations:
            return {
                "symbol": symbol, "status": "insufficient_data", "observation_count": len(observations),
                "required_observations": self.minimum_observations, "evidence_refs": [x["observation_id"] for x in observations],
                "generated_at": now(),
            }
        prices = [float(x["price"]) for x in observations]
        baseline = mean(prices)
        dispersion = pstdev(prices) if len(prices) > 1 else 0.0
        event_adjustment = max(-0.04, min(0.04, (float(event_severity) - 0.5) * 0.08))
        graph_bias = sum(float(x["weight"]) for x in self.graph.neighbors(symbol)) / 100
        fair_value = baseline * (1 + event_adjustment + min(graph_bias, 0.02))
        standard_error = max(dispersion / sqrt(len(prices)), baseline * 0.005)
        latest = prices[0]
        return {
            "symbol": symbol, "status": "estimated", "fair_value": round(fair_value, 6),
            "fair_value_range": [round(fair_value - 1.96 * standard_error, 6), round(fair_value + 1.96 * standard_error, 6)],
            "latest_price": latest, "expected_return": round((fair_value / latest) - 1, 6),
            "confidence": round(min(0.9, 0.45 + len(prices) / 100), 3),
            "observation_count": len(observations), "method": "mean+event+graph-v1",
            "evidence_refs": [x["observation_id"] for x in observations], "generated_at": now(),
        }


class StrategyGenomeRegistry:
    """Immutable strategy versions with stable content hashes."""

    def __init__(self, store) -> None:
        self.store = store

    def publish(self, genome: dict) -> dict:
        required = {"name", "hypothesis", "signals", "universe", "holding_period", "risk_profile"}
        missing = sorted(required - genome.keys())
        if missing:
            raise ValueError(f"Missing strategy fields: {', '.join(missing)}")
        strategy_id = str(genome.get("strategy_id") or uid())
        latest = self.store.latest_strategy_version(strategy_id)
        version = int(latest["version"]) + 1 if latest else 1
        record = {**genome, "strategy_id": strategy_id, "version": version, "created_at": now()}
        self.store.save_strategy_version(record)
        return record

    def list(self) -> list[dict]:
        return self.store.list_strategy_versions()
