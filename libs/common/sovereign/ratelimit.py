"""Shared in-process rate limiting (S4 hardening).

The security checklist requires rate limiting on every endpoint, but the
chassis previously shipped none. This module provides a dependency-free,
thread-safe token-bucket limiter plus a FastAPI middleware installer so
every service can opt in with a single call::

    from sovereign.ratelimit import install_rate_limit
    install_rate_limit(app)

The limiter keys on the caller's identity in priority order:
  1. the bearer token / basic credential (so one tenant can't exhaust
     another's budget),
  2. otherwise the client host.

`/healthz` is always exempt so liveness probes are never throttled.

This is an in-process limiter — correct for a single replica and a sane
default everywhere. Multi-replica deployments front it with a shared
store (Redis/Envoy local_ratelimit); the interface here is intentionally
small so that swap is mechanical. Limits come from settings
(`RATE_LIMIT_RPS`, `RATE_LIMIT_BURST`); setting RPS <= 0 disables it.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .settings import get_settings

# Cap the number of distinct buckets we retain so a flood of unique
# callers can't grow memory without bound. LRU eviction is fine: an
# evicted caller simply starts with a full bucket again.
_MAX_BUCKETS = 10_000


class TokenBucket:
    """A single token bucket. `capacity` tokens, refilled at `rate`/sec."""

    __slots__ = ("capacity", "rate", "tokens", "updated")

    def __init__(self, capacity: float, rate: float, now: float) -> None:
        self.capacity = capacity
        self.rate = rate
        self.tokens = capacity
        self.updated = now

    def allow(self, now: float, cost: float = 1.0) -> bool:
        # Refill proportional to elapsed time, capped at capacity.
        elapsed = max(0.0, now - self.updated)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.updated = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class RateLimiter:
    """Thread-safe LRU collection of per-key token buckets."""

    def __init__(self, rps: float, burst: float) -> None:
        self._rps = rps
        self._burst = burst
        self._buckets: OrderedDict[str, TokenBucket] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._rps > 0

    def allow(self, key: str, now: float | None = None) -> bool:
        if not self.enabled:
            return True
        ts = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(self._burst, self._rps, ts)
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)
            allowed = bucket.allow(ts)
            if len(self._buckets) > _MAX_BUCKETS:
                self._buckets.popitem(last=False)
            return allowed


def _caller_key(request: Request) -> str:
    """Identify the caller for bucketing. Prefer the credential so the
    limit is per-principal, not per-shared-NAT-egress-IP."""
    auth = request.headers.get("authorization")
    if auth:
        # Bucket on the credential, not the scheme word.
        return f"auth:{auth.split(' ', 1)[-1][:64]}"
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


def install_rate_limit(app: FastAPI) -> None:
    """Install the rate-limit middleware on `app`. No-op when RPS<=0."""
    s = get_settings()
    limiter = RateLimiter(rps=s.rate_limit_rps, burst=s.rate_limit_burst)
    if not limiter.enabled:
        return

    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):  # noqa: ANN001, ANN202
        # Liveness probes must never be throttled.
        if request.url.path == "/healthz":
            return await call_next(request)
        if not limiter.allow(_caller_key(request)):
            return JSONResponse(
                status_code=429,
                content={
                    "type": "about:blank",
                    "title": "too many requests",
                    "status": 429,
                    "detail": "rate limit exceeded; retry after a short backoff",
                    "service": s.service_name,
                },
                headers={"Retry-After": "1"},
            )
        return await call_next(request)
