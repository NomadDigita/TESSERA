from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
import time


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int


class MemoryRateLimiter:
    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        self._lock = RLock()
        self._windows: dict[str, tuple[int, int]] = {}

    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        current = int(self.clock())
        window = current // window_seconds
        with self._lock:
            previous_window, count = self._windows.get(key, (window, 0))
            count = count + 1 if previous_window == window else 1
            self._windows[key] = (window, count)
        retry = window_seconds - (current % window_seconds)
        return RateLimitResult(count <= limit, max(0, limit - count), retry)


class RedisRateLimiter:
    _script = """
    local count = redis.call('INCR', KEYS[1])
    if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
    local ttl = redis.call('TTL', KEYS[1])
    return {count, ttl}
    """

    def __init__(self, redis_url: str) -> None:
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("Distributed rate limiting requires redis") from exc
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)

    def consume(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        count, ttl = self.client.eval(self._script, 1, f"tessera:rate:{key}", limit, window_seconds)
        count, ttl = int(count), max(1, int(ttl))
        return RateLimitResult(count <= limit, max(0, limit - count), ttl)


def create_rate_limiter(redis_url: str):
    return RedisRateLimiter(redis_url) if redis_url else MemoryRateLimiter()
