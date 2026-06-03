"""Runtime observability contract tests."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _assert_metrics_endpoint(app: Any, service: str) -> str:
    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert f'sovereign_service_up{{service="{service}"}} 1' in body
    return body


def test_broker_metrics_endpoint(broker_module: Any) -> None:
    body = _assert_metrics_endpoint(broker_module.app, "broker")
    assert "sovereign_broker_renderers_registered" in body


def test_control_plane_metrics_endpoint(control_plane_module: Any) -> None:
    body = _assert_metrics_endpoint(control_plane_module.app, "control-plane")
    assert "sovereign_control_plane_renderers_registered" in body


def test_audit_service_metrics_endpoint(audit_service_module: Any) -> None:
    body = _assert_metrics_endpoint(audit_service_module.app, "audit-service")
    assert "sovereign_audit_buffered_events" in body
    assert "sovereign_audit_clickhouse_connected" in body


def test_metering_service_metrics_endpoint(metering_service_module: Any) -> None:
    body = _assert_metrics_endpoint(metering_service_module.app, "metering-service")
    assert "sovereign_metering_table_ensured" in body
