"""Tests for deep readiness checks (WS3)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sovereign import health
from sovereign.health import (
    CheckResult,
    ReadinessCheck,
    callable_dependency,
    http_dependency,
    install_readiness,
)


def _app(checks: list[ReadinessCheck]) -> FastAPI:
    app = FastAPI()
    install_readiness(app, service="t", checks=checks)
    return app


def test_ready_when_all_checks_pass() -> None:
    def sync_ok() -> CheckResult:
        return CheckResult("sync", ok=True)

    async def async_ok() -> CheckResult:
        return CheckResult("async", ok=True)

    r = TestClient(_app([sync_ok, async_ok])).get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert {c["name"] for c in body["checks"]} == {"sync", "async"}


def test_not_ready_when_a_check_fails() -> None:
    r = TestClient(
        _app([lambda: CheckResult("up", ok=True), lambda: CheckResult("db", ok=False, detail="x")])
    ).get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert any(c["name"] == "db" and c["ok"] is False for c in body["checks"])


def test_raising_check_is_failed_not_500() -> None:
    def boom() -> CheckResult:
        raise RuntimeError("kapow")

    r = TestClient(_app([boom])).get("/readyz")
    assert r.status_code == 503
    assert r.json()["ready"] is False


def test_callable_dependency_reports_probe_failure() -> None:
    def failing_probe() -> None:
        raise ConnectionError("backend down")

    ok = callable_dependency("good", lambda: None)
    bad = callable_dependency("bad", failing_probe)
    r = TestClient(_app([ok, bad])).get("/readyz")
    assert r.status_code == 503
    checks = {c["name"]: c for c in r.json()["checks"]}
    assert checks["good"]["ok"] is True
    assert checks["bad"]["ok"] is False
    assert "backend down" in checks["bad"]["detail"]


def test_http_dependency_health(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        def __init__(self, *, status: int | None, exc: Exception | None) -> None:
            self._status, self._exc = status, exc

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_a: Any) -> bool:
            return False

        async def get(self, _url: str) -> Any:
            if self._exc is not None:
                raise self._exc
            return SimpleNamespace(status_code=self._status)

    import httpx

    # Healthy downstream (200) -> ok.
    monkeypatch.setattr(health.httpx, "AsyncClient", lambda **_k: _FakeClient(status=200, exc=None))
    r = TestClient(_app([http_dependency("peer", "http://peer/healthz")])).get("/readyz")
    assert r.status_code == 200

    # Unreachable downstream -> not ready.
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda **_k: _FakeClient(status=None, exc=httpx.ConnectError("down")),
    )
    r = TestClient(_app([http_dependency("peer", "http://peer/healthz")])).get("/readyz")
    assert r.status_code == 503
