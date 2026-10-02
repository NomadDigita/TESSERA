from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8787
    database_path: str = "data/tessera.db"
    environment: str = "development"
    broker_mode: str = "mock-paper"
    live_trading_enabled: bool = False
    require_human_approval: bool = True
    max_order_notional: float = 1500.0

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            host=os.getenv("TESSERA_HOST", "127.0.0.1"),
            port=int(os.getenv("TESSERA_PORT", "8787")),
            database_path=os.getenv("TESSERA_DATABASE_PATH", "data/tessera.db"),
            environment=os.getenv("TESSERA_ENV", "development"),
            broker_mode=os.getenv("TESSERA_BROKER_MODE", "mock-paper"),
            live_trading_enabled=_bool("TESSERA_LIVE_TRADING_ENABLED", False),
            require_human_approval=_bool("TESSERA_REQUIRE_HUMAN_APPROVAL", True),
            max_order_notional=float(os.getenv("TESSERA_MAX_ORDER_NOTIONAL", "1500")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("TESSERA_PORT must be between 1 and 65535")
        if self.max_order_notional <= 0:
            raise ValueError("TESSERA_MAX_ORDER_NOTIONAL must be positive")
        if self.broker_mode != "mock-paper":
            raise ValueError("Only mock-paper broker mode is supported in this release")
        if self.live_trading_enabled:
            raise ValueError("Live trading is intentionally disabled")

    def prepare_runtime(self) -> None:
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
