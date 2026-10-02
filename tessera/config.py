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
    max_gross_exposure: float = 5000.0
    max_single_asset_exposure: float = 2500.0
    llm_provider: str = "deterministic"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    dashscope_api_key: str = ""
    bitget_api_key: str = ""
    bitget_api_secret: str = ""
    bitget_api_passphrase: str = ""
    bitget_base_url: str = "https://api.bitget.com"
    auth_enabled: bool = False
    session_secret: str = ""
    session_ttl_seconds: int = 28800
    admin_username: str = "admin"
    admin_password: str = ""

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
            max_gross_exposure=float(os.getenv("TESSERA_MAX_GROSS_EXPOSURE", "5000")),
            max_single_asset_exposure=float(os.getenv("TESSERA_MAX_SINGLE_ASSET_EXPOSURE", "2500")),
            llm_provider=os.getenv("TESSERA_LLM_PROVIDER", "deterministic"),
            qwen_base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            qwen_model=os.getenv("QWEN_MODEL", "qwen-plus"),
            dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            bitget_api_key=os.getenv("BITGET_API_KEY", ""),
            bitget_api_secret=os.getenv("BITGET_API_SECRET", ""),
            bitget_api_passphrase=os.getenv("BITGET_API_PASSPHRASE", ""),
            bitget_base_url=os.getenv("BITGET_BASE_URL", "https://api.bitget.com"),
            auth_enabled=_bool("TESSERA_AUTH_ENABLED", False),
            session_secret=os.getenv("TESSERA_SESSION_SECRET", ""),
            session_ttl_seconds=int(os.getenv("TESSERA_SESSION_TTL_SECONDS", "28800")),
            admin_username=os.getenv("TESSERA_ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("TESSERA_ADMIN_PASSWORD", ""),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("TESSERA_PORT must be between 1 and 65535")
        if self.max_order_notional <= 0:
            raise ValueError("TESSERA_MAX_ORDER_NOTIONAL must be positive")
        if self.max_gross_exposure <= 0 or self.max_single_asset_exposure <= 0:
            raise ValueError("Exposure limits must be positive")
        if self.broker_mode not in {"mock-paper", "bitget-demo"}:
            raise ValueError("TESSERA_BROKER_MODE must be mock-paper or bitget-demo")
        if self.broker_mode == "bitget-demo" and not all((self.bitget_api_key, self.bitget_api_secret, self.bitget_api_passphrase)):
            raise ValueError("Bitget demo credentials are required when TESSERA_BROKER_MODE=bitget-demo")
        if not self.bitget_base_url.startswith("https://"):
            raise ValueError("BITGET_BASE_URL must use HTTPS")
        if self.live_trading_enabled:
            raise ValueError("Live trading is intentionally disabled")
        if self.llm_provider not in {"deterministic", "qwen"}:
            raise ValueError("TESSERA_LLM_PROVIDER must be deterministic or qwen")
        if self.llm_provider == "qwen" and not self.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is required when TESSERA_LLM_PROVIDER=qwen")
        if self.environment == "production" and not self.auth_enabled:
            raise ValueError("Authentication must be enabled in production")
        if self.auth_enabled and len(self.session_secret) < 32:
            raise ValueError("TESSERA_SESSION_SECRET must contain at least 32 characters")
        if self.session_ttl_seconds < 300 or self.session_ttl_seconds > 86400:
            raise ValueError("Session TTL must be between 5 minutes and 24 hours")

    def prepare_runtime(self) -> None:
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
