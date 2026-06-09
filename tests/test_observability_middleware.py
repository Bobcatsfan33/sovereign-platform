"""Tests for the request observability middleware (E5)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sovereign.observability import install_metrics_endpoint
from sovereign.tracing import parse_traceparent


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/boom")
    def boom() -> dict[str, bool]:
        raise RuntimeError("kaboom")

    install_metrics_endpoint(app, service="test-svc")
    return app


def test_response_carries_traceparent() -> None:
    r = TestClient(_app()).get("/ok")
    assert r.status_code == 200
    assert parse_traceparent(r.headers.get("traceparent")) is not None


def test_incoming_trace_id_is_propagated() -> None:
    incoming = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    r = TestClient(_app()).get("/ok", headers={"traceparent": incoming})
    parsed = parse_traceparent(r.headers["traceparent"])
    assert parsed is not None
    assert parsed[0] == "a" * 32  # same trace, new span


def test_metrics_endpoint_includes_red_metrics() -> None:
    client = TestClient(_app())
    client.get("/ok")
    body = client.get("/metrics").text
    assert "sovereign_http_requests_total" in body
    assert 'service="test-svc"' in body
    assert 'route="/ok"' in body
    assert "sovereign_http_request_duration_seconds_bucket" in body


def test_error_path_is_counted_as_500() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    assert client.get("/boom").status_code == 500
    body = client.get("/metrics").text
    assert 'status="500"' in body
