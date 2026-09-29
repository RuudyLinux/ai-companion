"""
Fixed-window rate limiting, configured centrally (core/config.py RATE_LIMIT_* env vars).

Usage on a route:  dependencies=[Depends(rate_limit("chat"))]

Keys are per user when signed in, per client IP otherwise. The in-memory backend is
per-process; set REDIS_URL to share counters across processes/instances.
"""

import logging
import threading
import time

from fastapi import Request

from core.config import settings
from core.errors import RateLimited

log = logging.getLogger("app.rate_limit")

_PERIODS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def parse_limit(spec: str) -> tuple[int, int]:
    count, _, period = spec.partition("/")
    if period not in _PERIODS or not count.isdigit():
        raise ValueError(f"Invalid rate limit {spec!r}; expected e.g. '10/minute'")
    return int(count), _PERIODS[period]


class MemoryBackend:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, tuple[int, float]] = {}

    def hit(self, key: str, window: int) -> tuple[int, int]:
        """Returns (count in current window, seconds until the window resets)."""
        current = time.time()
        with self._lock:
            count, reset_at = self._counters.get(key, (0, 0.0))
            if current >= reset_at:
                count, reset_at = 0, current + window
            count += 1
            self._counters[key] = (count, reset_at)
            if len(self._counters) > 50_000:  # drop expired keys occasionally
                self._counters = {k: v for k, v in self._counters.items() if v[1] > current}
        return count, max(1, int(reset_at - current))

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()


class RedisBackend:
    def __init__(self, url: str):
        import redis  # optional dependency, only needed when REDIS_URL is set

        self._redis = redis.Redis.from_url(url)

    def hit(self, key: str, window: int) -> tuple[int, int]:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window, nx=True)
        pipe.ttl(key)
        count, _, ttl = pipe.execute()
        return int(count), max(1, int(ttl))

    def reset(self) -> None:
        pass


def _make_backend():
    if settings.redis_url:
        try:
            return RedisBackend(settings.redis_url)
        except ImportError:
            log.warning("REDIS_URL is set but the redis package isn't installed; using in-memory rate limits")
    return MemoryBackend()


backend = _make_backend()


def _client_key(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def check_rate_limit(name: str, key: str) -> None:
    spec = settings.rate_limits.get(name)
    if not spec or spec == "off":
        return
    limit, window = parse_limit(spec)
    count, retry_after = backend.hit(f"rl:{name}:{key}", window)
    if count > limit:
        raise RateLimited(retry_after=retry_after)


def rate_limit(name: str):
    spec = settings.rate_limits.get(name)
    if spec and spec != "off":
        parse_limit(spec)  # fail fast on bad config at startup, not on first request

    def dependency(request: Request) -> None:
        check_rate_limit(name, _client_key(request))

    return dependency
