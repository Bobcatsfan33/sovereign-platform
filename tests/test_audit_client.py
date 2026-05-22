"""Tests for the in-process audit client (libs/common/sovereign/audit.py).

The Audit class is a thin HTTP wrapper around the audit service. These
tests verify that emit() builds the right payload, attaches the bearer
header, and tolerates transport failures without raising.
"""

from __future__ import annotations

import json

import httpx
import pytest
from sovereign.audit import Audit


def test_emit_posts_audit_event_with_bearer() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(202, json={"accepted": True})

    transport = httpx.MockTransport(handler)
    audit = Audit(service="test-svc")
    audit._client = httpx.Client(transport=transport)  # type: ignore[assignment]

    audit.emit(
        action="instance.provisioned",
        resource="svc/demo",
        details="rendered ok",
        actor="alice",
        tenant_id="acme",
        decision="allow",
        metadata={"plan": "standard-regional"},
    )

    assert len(captured) == 1
    req = captured[0]
    assert req.url.path == "/events"
    assert req.headers["Authorization"] == "Bearer test-token"
    payload = json.loads(req.content)
    assert payload["action"] == "instance.provisioned"
    assert payload["resource"] == "svc/demo"
    assert payload["tenant_id"] == "acme"
    assert payload["actor"] == "alice"
    assert payload["metadata"]["details"] == "rendered ok"
    assert payload["metadata"]["plan"] == "standard-regional"
    assert payload["metadata"]["emitted_by"] == "test-svc"


def test_emit_swallows_transport_errors(caplog: pytest.LogCaptureFixture) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    audit = Audit(service="test-svc")
    audit._client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[assignment]

    # Should not raise — best-effort emission.
    audit.emit(action="x", resource="y")
    assert any("audit emit failed" in r.message for r in caplog.records)


def test_emit_logs_non_2xx_response(caplog: pytest.LogCaptureFixture) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    audit = Audit(service="test-svc")
    audit._client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[assignment]

    audit.emit(action="x", resource="y")
    assert any("audit service returned 500" in r.message for r in caplog.records)


def test_default_actor_is_system() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(202, json={"accepted": True})

    audit = Audit(service="test-svc")
    audit._client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[assignment]

    audit.emit(action="x", resource="y")
    payload = json.loads(captured[0].content)
    assert payload["actor"] == "system"
    assert payload["tenant_id"] == "default"
    assert payload["decision"] == "allow"


def test_close_releases_client() -> None:
    audit = Audit()
    audit.close()
