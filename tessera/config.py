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
    database_url: str = ""
    redis_url: str = ""
    artifact_path: str = "data/artifacts"
    object_storage_endpoint: str = ""
    object_storage_bucket: str = ""
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_region: str = "us-east-1"
    environment: str = "development"
    broker_mode: str = "mock-paper"
    live_trading_enabled: bool = False
    require_human_approval: bool = True
    max_order_notional: float = 1500.0
    max_gross_exposure: float = 5000.0
    max_single_asset_exposure: float = 2500.0
    max_sector_exposure: float = 3500.0
    max_daily_loss: float = 500.0
    max_drawdown_pct: float = 0.10
    max_spread_bps: float = 40.0
    max_slippage_bps: float = 30.0
    max_data_age_seconds: int = 120
    min_decision_confidence: float = 0.55
    max_leverage: float = 1.0
    llm_provider: str = "deterministic"
    llm_fallback_provider: str = "deterministic"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    dashscope_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    bitget_api_key: str = ""
    bitget_api_secret: str = ""
    bitget_api_passphrase: str = ""
    bitget_base_url: str = "https://api.bitget.com"
    auth_enabled: bool = False
    session_secret: str = ""
    session_ttl_seconds: int = 28800
    login_rate_limit: int = 5
    api_rate_limit: int = 120
    admin_username: str = "admin"
    admin_password: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            host=os.getenv("TESSERA_HOST", "127.0.0.1"),
            port=int(os.getenv("TESSERA_PORT", "8787")),
            database_path=os.getenv("TESSERA_DATABASE_PATH", "data/tessera.db"),
            database_url=os.getenv("DATABASE_URL", ""),
            redis_url=os.getenv("REDIS_URL", ""),
            artifact_path=os.getenv("TESSERA_ARTIFACT_PATH", "data/artifacts"),
            object_storage_endpoint=os.getenv("OBJECT_STORAGE_ENDPOINT", ""),
            object_storage_bucket=os.getenv("OBJECT_STORAGE_BUCKET", ""),
            object_storage_access_key=os.getenv("OBJECT_STORAGE_ACCESS_KEY", ""),
            object_storage_secret_key=os.getenv("OBJECT_STORAGE_SECRET_KEY", ""),
            object_storage_region=os.getenv("OBJECT_STORAGE_REGION", "us-east-1"),
            environment=os.getenv("TESSERA_ENV", "development"),
            broker_mode=os.getenv("TESSERA_BROKER_MODE", "mock-paper"),
            live_trading_enabled=_bool("TESSERA_LIVE_TRADING_ENABLED", False),
            require_human_approval=_bool("TESSERA_REQUIRE_HUMAN_APPROVAL", True),
            max_order_notional=float(os.getenv("TESSERA_MAX_ORDER_NOTIONAL", "1500")),
            max_gross_exposure=float(os.getenv("TESSERA_MAX_GROSS_EXPOSURE", "5000")),
            max_single_asset_exposure=float(os.getenv("TESSERA_MAX_SINGLE_ASSET_EXPOSURE", "2500")),
            max_sector_exposure=float(os.getenv("TESSERA_MAX_SECTOR_EXPOSURE", "3500")),
            max_daily_loss=float(os.getenv("TESSERA_MAX_DAILY_LOSS", "500")),
            max_drawdown_pct=float(os.getenv("TESSERA_MAX_DRAWDOWN_PCT", "0.10")),
            max_spread_bps=float(os.getenv("TESSERA_MAX_SPREAD_BPS", "40")),
            max_slippage_bps=float(os.getenv("TESSERA_MAX_SLIPPAGE_BPS", "30")),
            max_data_age_seconds=int(os.getenv("TESSERA_MAX_DATA_AGE_SECONDS", "120")),
            min_decision_confidence=float(os.getenv("TESSERA_MIN_DECISION_CONFIDENCE", "0.55")),
            max_leverage=float(os.getenv("TESSERA_MAX_LEVERAGE", "1.0")),
            llm_provider=os.getenv("TESSERA_LLM_PROVIDER", "deterministic"),
            llm_fallback_provider=os.getenv("TESSERA_LLM_FALLBACK_PROVIDER", "deterministic"),
            qwen_base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            qwen_model=os.getenv("QWEN_MODEL", "qwen-plus"),
            dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            gemini_base_url=os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
            bitget_api_key=os.getenv("BITGET_API_KEY", ""),
            bitget_api_secret=os.getenv("BITGET_API_SECRET", ""),
            bitget_api_passphrase=os.getenv("BITGET_API_PASSPHRASE", ""),
            bitget_base_url=os.getenv("BITGET_BASE_URL", "https://api.bitget.com"),
            auth_enabled=_bool("TESSERA_AUTH_ENABLED", False),
            session_secret=os.getenv("TESSERA_SESSION_SECRET", ""),
            session_ttl_seconds=int(os.getenv("TESSERA_SESSION_TTL_SECONDS", "28800")),
            login_rate_limit=int(os.getenv("TESSERA_LOGIN_RATE_LIMIT", "5")),
            api_rate_limit=int(os.getenv("TESSERA_API_RATE_LIMIT", "120")),
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
        if min(self.max_sector_exposure, self.max_daily_loss, self.max_spread_bps,
               self.max_slippage_bps, self.max_data_age_seconds, self.max_leverage) <= 0:
            raise ValueError("Risk limits must be positive")
        if not 0 < self.max_drawdown_pct < 1 or not 0 <= self.min_decision_confidence <= 1:
            raise ValueError("Drawdown and confidence limits are invalid")
        if self.broker_mode not in {"mock-paper", "bitget-demo"}:
            raise ValueError("TESSERA_BROKER_MODE must be mock-paper or bitget-demo")
        if self.broker_mode == "bitget-demo" and not all((self.bitget_api_key, self.bitget_api_secret, self.bitget_api_passphrase)):
            raise ValueError("Bitget demo credentials are required when TESSERA_BROKER_MODE=bitget-demo")
        if not self.bitget_base_url.startswith("https://"):
            raise ValueError("BITGET_BASE_URL must use HTTPS")
        if self.live_trading_enabled:
            raise ValueError("Live trading is intentionally disabled")
        providers = {"deterministic", "qwen", "gemini"}
        if self.llm_provider not in providers or self.llm_fallback_provider not in providers:
            raise ValueError("LLM providers must be deterministic, qwen, or gemini")
        if self.llm_provider == "qwen" and not self.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is required when TESSERA_LLM_PROVIDER=qwen")
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when TESSERA_LLM_PROVIDER=gemini")
        if self.llm_fallback_provider == "qwen" and not self.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is required when the LLM fallback is qwen")
        if self.llm_fallback_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when the LLM fallback is gemini")
        if self.environment == "production" and not self.auth_enabled:
            raise ValueError("Authentication must be enabled in production")
        if self.environment == "production" and not self.database_url:
            raise ValueError("DATABASE_URL is required in production")
        if self.environment == "production" and not self.redis_url:
            raise ValueError("REDIS_URL is required in production")
        if self.environment == "production" and not all((self.object_storage_endpoint,
                                                           self.object_storage_bucket,
                                                           self.object_storage_access_key,
                                                           self.object_storage_secret_key)):
            raise ValueError("S3-compatible object storage configuration is required in production")
        if self.database_url and not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        if self.redis_url and not self.redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must be a Redis URL")
        if self.auth_enabled and len(self.session_secret) < 32:
            raise ValueError("TESSERA_SESSION_SECRET must contain at least 32 characters")
        if self.session_ttl_seconds < 300 or self.session_ttl_seconds > 86400:
            raise ValueError("Session TTL must be between 5 minutes and 24 hours")
        if self.login_rate_limit < 1 or self.api_rate_limit < 1:
            raise ValueError("Rate limits must be positive")

    def prepare_runtime(self) -> None:
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        if not self.object_storage_bucket:
            Path(self.artifact_path).mkdir(parents=True, exist_ok=True)
