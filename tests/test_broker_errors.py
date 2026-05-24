"""Error-handling and downstream-failure tests for the broker.

These exercise the hardening added in task 0.5: RFC 7807 problem detail
on every error, graceful 503 when DynamoDB or the control plane is
unavailable, OSB-correct status codes (410 Gone on deprovision-missing).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws


def _provision_body() -> dict[str, Any]:
    return {
        "service_id": "sovereign-envoy-lb",
        "plan_id": "standard-regional",
        "parameters": {
            "listeners": [{"name": "http", "port": 8080, "protocol": "HTTP"}],
            "routes": [{"host": "app.local", "prefix": "/", "cluster": "app"}],
            "clusters": [{"name": "app", "endpoints": ["127.0.0.1:3000"]}],
        },
    }


def _broker_creds() -> tuple[str, str]:
    return ("broker", "broker")


@pytest.fixture
def broker_with_render(broker_module: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Broker with a working fake render and audit, used to test
    downstream-store failure modes."""
    from sovereign.models import PolicyDecision

    async def fake_render(instance: Any) -> dict[str, Any]:
        return {"bucket": "b", "key": f"instances/{instance.instance_id}/v1/envoy.yaml", "version": 1}

    class FakeAudit:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

    class FakePolicy:
        def evaluate(self, _input: Any) -> PolicyDecision:
            return PolicyDecision(allow=True, denies=[], matched_layers=[])

    monkeypatch.setattr(broker_module, "render", fake_render)
    monkeypatch.setattr(broker_module, "audit", FakeAudit())
    monkeypatch.setattr(broker_module, "policy", FakePolicy())
    return broker_module


@mock_aws
def test_deprovision_missing_returns_410(broker_with_render: Any) -> None:
    with TestClient(broker_with_render.app) as client:
        r = client.delete("/v2/service_instances/never-existed", auth=_broker_creds())
        assert r.status_code == 410
        body = r.json()
        assert body["title"] == "gone"
        assert body["status"] == 410


@mock_aws
def test_problem_detail_shape_on_unauthorized(broker_with_render: Any) -> None:
    with TestClient(broker_with_render.app) as client:
        r = client.get("/v2/catalog", auth=("bad", "creds"))
        assert r.status_code == 401
        body = r.json()
        assert body == {
            "type": "about:blank",
            "title": "unauthorized",
            "status": 401,
            "detail": "invalid credentials",
            "service": "broker",
        }


@mock_aws
def test_validation_error_returns_problem_detail(broker_with_render: Any) -> None:
    with TestClient(broker_with_render.app) as client:
        # Missing required service_id/plan_id
        r = client.put(
            "/v2/service_instances/bad-req",
            json={"parameters": {}},
            auth=_broker_creds(),
        )
        assert r.status_code == 422
        body = r.json()
        assert body["title"] == "unprocessable entity"
        assert "errors" in body


@mock_aws
def test_state_store_unavailable_returns_503(
    broker_with_render: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If DynamoDB raises ClientError on get_instance, the broker should
    surface 503 rather than 500."""

    def boom(_self: Any, _instance_id: str) -> None:
        raise ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "table missing"}},
            "GetItem",
        )

    monkeypatch.setattr("sovereign.store.Store.get_instance", boom)
    with TestClient(broker_with_render.app) as client:
        r = client.put(
            "/v2/service_instances/i1",
            json=_provision_body(),
            auth=_broker_creds(),
        )
        assert r.status_code == 503
        assert r.json()["title"] == "service unavailable"


@mock_aws
def test_control_plane_unavailable_returns_503(
    broker_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the control plane is unreachable from the broker, provision
    should surface 503 with a clear detail rather than 500."""

    from sovereign.models import PolicyDecision

    class FakeAudit:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

    class FakePolicy:
        def evaluate(self, _input: Any) -> PolicyDecision:
            return PolicyDecision(allow=True, denies=[], matched_layers=[])

    monkeypatch.setattr(broker_module, "audit", FakeAudit())
    monkeypatch.setattr(broker_module, "policy", FakePolicy())

    # Restore the real render() so we can exercise its error-handling
    # branch. Override httpx.AsyncClient to a mock transport that fails.
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("control plane down")

    real_async_client = httpx.AsyncClient

    def patched_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs.pop("timeout", None)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", patched_client)

    with TestClient(broker_module.app) as client:
        r = client.put(
            "/v2/service_instances/i-cp-down",
            json=_provision_body(),
            auth=_broker_creds(),
        )
        assert r.status_code == 503
        assert r.json()["status"] == 503
