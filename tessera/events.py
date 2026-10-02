from __future__ import annotations

from dataclasses import dataclass, field
from threading import Condition
import time


class NullEventBus:
    def publish(self, stream: str, payload: dict) -> str | None:
        return None

    def wait(self, stream: str, timeout_seconds: float = 1.0) -> str | None:
        time.sleep(timeout_seconds)
        return None

    def acknowledge(self, stream: str, message_id: str) -> None:
        return None

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None


class RedisStreamBus:
    def __init__(self, redis_url: str, group: str = "tessera-workers", consumer: str = "worker") -> None:
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("Redis Streams requires the 'redis' TESSERA dependency") from exc
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.group = group
        self.consumer = consumer
        self._groups: set[str] = set()

    def _ensure_group(self, stream: str) -> None:
        if stream in self._groups:
            return
        try:
            self.client.xgroup_create(stream, self.group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._groups.add(stream)

    def publish(self, stream: str, payload: dict) -> str:
        return str(self.client.xadd(stream, {key: str(value) for key, value in payload.items()}, maxlen=10000))

    def wait(self, stream: str, timeout_seconds: float = 1.0) -> str | None:
        self._ensure_group(stream)
        rows = self.client.xreadgroup(self.group, self.consumer, {stream: ">"}, count=1,
                                      block=max(1, int(timeout_seconds * 1000)))
        return str(rows[0][1][0][0]) if rows else None

    def acknowledge(self, stream: str, message_id: str) -> None:
        self.client.xack(stream, self.group, message_id)

    def ping(self) -> bool:
        return bool(self.client.ping())

    def close(self) -> None:
        self.client.close()


@dataclass
class MemoryEventBus:
    messages: list[str] = field(default_factory=list)
    _condition: Condition = field(default_factory=Condition)

    def publish(self, stream: str, payload: dict) -> str:
        with self._condition:
            message_id = f"{stream}:{len(self.messages) + 1}"
            self.messages.append(message_id)
            self._condition.notify()
            return message_id

    def wait(self, stream: str, timeout_seconds: float = 1.0) -> str | None:
        with self._condition:
            if not self.messages:
                self._condition.wait(timeout_seconds)
            return self.messages.pop(0) if self.messages else None

    def acknowledge(self, stream: str, message_id: str) -> None:
        return None

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None


def create_event_bus(redis_url: str, consumer: str = "worker"):
    return RedisStreamBus(redis_url, consumer=consumer) if redis_url else NullEventBus()
