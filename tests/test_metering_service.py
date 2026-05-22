"""Tests for the dedicated metering service (apps/metering-service).

Uses moto's `mock_aws` to stand up an in-process DynamoDB so the SUT's
real `UsageStore` is exercised end-to-end without touching a live AWS
or DynamoDB Local container.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from sovereign.models import Usage

from .conftest import AUTH_HEADER


@pytest.fixture
def metering_app(metering_service_module: Any) -> Any:
    """Reset the module-level store and let it bind to a fresh moto-backed
    DynamoDB inside the `mock_aws` context provided by each test."""
    metering_service_module._store = None
    metering_service_module._table_ensured = False
    return metering_service_module


def _usage_body(*, when: datetime | None = None, resource_id: str = "demo-lb") -> dict[str, Any]:
    u = Usage(
        ts=when or datetime.now(timezone.utc),
        tenant_id="acme",
        resource_id=resource_id,
        resource_type="lb-hour",
        quantity=1.5,
        unit="hour",
        metadata={"region": "us-east-1"},
    )
    return u.model_dump(mode="json")


@mock_aws
def test_healthz_open(metering_app: Any) -> None:
    client = TestClient(metering_app.app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["service"] == "metering-service"


@mock_aws
def test_record_requires_bearer(metering_app: Any) -> None:
    # Ensure DDB region matches the SUT
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    client = TestClient(metering_app.app)
    r = client.post("/usage", json=_usage_body())
    assert r.status_code == 401


@mock_aws
def test_record_and_query_round_trip(metering_app: Any) -> None:
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    client = TestClient(metering_app.app)
    # Trigger ensure_table by hitting startup once. TestClient runs startup on first request.
    client.get("/healthz")

    # POST three usage records
    now = datetime.now(timezone.utc)
    for i in range(3):
        r = client.post(
            "/usage",
            json=_usage_body(when=now - timedelta(minutes=i), resource_id=f"lb-{i}"),
            headers=AUTH_HEADER,
        )
        assert r.status_code == 202, r.text
        assert r.json()["accepted"] is True

    # Query with required tenant_id
    r = client.get("/usage", params={"tenant_id": "acme"}, headers=AUTH_HEADER)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    # ScanIndexForward=False means newest first
    assert body["usage"][0]["resource_id"] == "lb-0"


@mock_aws
def test_query_filters_by_resource_id(metering_app: Any) -> None:
    client = TestClient(metering_app.app)
    client.get("/healthz")
    now = datetime.now(timezone.utc)
    for i in range(3):
        client.post(
            "/usage",
            json=_usage_body(when=now - timedelta(minutes=i), resource_id=f"lb-{i}"),
            headers=AUTH_HEADER,
        )

    r = client.get(
        "/usage", params={"tenant_id": "acme", "resource_id": "lb-1"}, headers=AUTH_HEADER
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["usage"][0]["resource_id"] == "lb-1"


@mock_aws
def test_query_time_window(metering_app: Any) -> None:
    client = TestClient(metering_app.app)
    client.get("/healthz")
    base = datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        client.post(
            "/usage",
            json=_usage_body(when=base + timedelta(minutes=i), resource_id=f"lb-{i}"),
            headers=AUTH_HEADER,
        )

    since = (base + timedelta(minutes=1)).isoformat()
    until = (base + timedelta(minutes=4)).isoformat()
    r = client.get(
        "/usage",
        params={"tenant_id": "acme", "since": since, "until": until},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    body = r.json()
    # Expect items at minute 1, 2, 3 (until is exclusive)
    minutes_returned = sorted(int(u["resource_id"].split("-")[1]) for u in body["usage"])
    assert minutes_returned == [1, 2, 3]


@mock_aws
def test_query_requires_tenant_id(metering_app: Any) -> None:
    client = TestClient(metering_app.app)
    client.get("/healthz")
    r = client.get("/usage", headers=AUTH_HEADER)
    # tenant_id is a required Query param -> 422 from FastAPI
    assert r.status_code == 422


@mock_aws
def test_negative_quantity_rejected(metering_app: Any) -> None:
    client = TestClient(metering_app.app)
    client.get("/healthz")
    payload = _usage_body()
    payload["quantity"] = -0.5
    r = client.post("/usage", json=payload, headers=AUTH_HEADER)
    assert r.status_code == 422
