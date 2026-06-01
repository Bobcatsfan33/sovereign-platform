"""Tests for the shared rate limiter (S4 hardening)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sovereign.ratelimit import RateLimiter, install_rate_limit


def test_token_bucket_allows_burst_then_throttles() -> None:
    rl = RateLimiter(rps=1.0, burst=3.0)
    # Freeze time so refill doesn't interfere.
    assert rl.allow("k", now=0.0) is True
    assert rl.allow("k", now=0.0) is True
    assert rl.allow("k", now=0.0) is True
    # Burst exhausted at the same instant.
    assert rl.allow("k", now=0.0) is False


def test_token_bucket_refills_over_time() -> None:
    rl = RateLimiter(rps=2.0, burst=2.0)
    assert rl.allow("k", now=0.0) is True
    assert rl.allow("k", now=0.0) is True
    assert rl.allow("k", now=0.0) is False
    # After 1s at 2 rps, two tokens are back.
    assert rl.allow("k", now=1.0) is True
    assert rl.allow("k", now=1.0) is True
    assert rl.allow("k", now=1.0) is False


def test_keys_are_independent() -> None:
    rl = RateLimiter(rps=1.0, burst=1.0)
    assert rl.allow("a", now=0.0) is True
    assert rl.allow("a", now=0.0) is False
    # A different caller has its own budget.
    assert rl.allow("b", now=0.0) is True


def test_disabled_when_rps_non_positive() -> None:
    rl = RateLimiter(rps=0.0, burst=5.0)
    assert rl.enabled is False
    for _ in range(100):
        assert rl.allow("k", now=0.0) is True


def test_middleware_returns_429_after_burst(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sovereign import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(settings_mod.Settings, "rate_limit_rps", 1.0)
    monkeypatch.setattr(settings_mod.Settings, "rate_limit_burst", 2.0)

    app = FastAPI()
    install_rate_limit(app)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(app)
    # Two requests inside the burst succeed; the third is throttled.
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    r = client.get("/ping")
    assert r.status_code == 429
    assert r.json()["title"] == "too many requests"
    assert r.headers.get("Retry-After") == "1"

    # /healthz is exempt no matter what.
    for _ in range(10):
        assert client.get("/healthz").status_code == 200

    settings_mod.get_settings.cache_clear()


def test_middleware_noop_when_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sovereign import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(settings_mod.Settings, "rate_limit_rps", 0.0)

    app = FastAPI()
    install_rate_limit(app)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    client = TestClient(app)
    for _ in range(50):
        assert client.get("/ping").status_code == 200

    settings_mod.get_settings.cache_clear()
