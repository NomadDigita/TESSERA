from __future__ import annotations

from collections import defaultdict
import json
import logging
import sys
from threading import RLock
from time import time


SENSITIVE = {"password", "secret", "api_key", "api_secret", "passphrase", "authorization", "token", "access_token"}


def _is_sensitive(key: str) -> bool:
    normalized = key.lower()
    return normalized in SENSITIVE or any(marker in normalized for marker in
                                           ("password", "secret", "api_key", "passphrase", "authorization", "token"))


def _redact(value):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if _is_sensitive(key) else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": int(time() * 1000),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if context:
            payload.update(_redact(context))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("tessera")
    logger.setLevel(level.upper())
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return logger


class Metrics:
    def __init__(self) -> None:
        self._lock = RLock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    @staticmethod
    def _key(name: str, labels: dict[str, str] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
        return name, tuple(sorted((labels or {}).items()))

    def inc(self, name: str, value: float = 1, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += value

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    def render(self) -> str:
        lines = []
        with self._lock:
            values = list(self._counters.items()) + list(self._gauges.items())
        for (name, labels), value in sorted(values):
            suffix = "{" + ",".join(f'{key}="{item}"' for key, item in labels) + "}" if labels else ""
            lines.append(f"tessera_{name}{suffix} {value:g}")
        return "\n".join(lines) + "\n"


METRICS = Metrics()
LOGGER = configure_logging()
