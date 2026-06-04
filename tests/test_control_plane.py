"""Tests for the Envoy control plane (apps/control-plane)."""

from __future__ import annotations

from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sovereign.models import (
    Cluster,
    LbParameters,
    Listener,
    RenderRequest,
    Route,
    ServiceInstance,
)

from .conftest import AUTH_HEADER  # noqa: E402


@pytest.fixture
def control_plane_app(control_plane_module: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Replace the control-plane's outbound audit emit with a no-op so
    tests don't try to hit a real audit-service."""

    class FakeAudit:
        def emit(self, *args: Any, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr(control_plane_module, "audit", FakeAudit())
    return control_plane_module


def _render_request() -> dict[str, Any]:
    inst = ServiceInstance(
        instance_id="demo-lb",
        service_id="sovereign-envoy-lb",
        plan_id="standard-regional",
        parameters=LbParameters(
            region="us-east-1",
            listeners=[Listener(name="http", port=8080, protocol="HTTP")],
            routes=[Route(host="app.local", prefix="/", cluster="app")],
            clusters=[Cluster(name="app", endpoints=["127.0.0.1:3000"])],
        ),
    )
    return RenderRequest(instance=inst).model_dump(mode="json")


@mock_aws
def test_render_requires_bearer(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        r = client.post("/render", json=_render_request())
        assert r.status_code == 401


@mock_aws
def test_render_writes_to_s3(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        r = client.post("/render", json=_render_request(), headers=AUTH_HEADER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["key"] == "instances/demo-lb/v1/envoy.yaml"

    s3 = boto3.client("s3", region_name="us-east-1")
    head = s3.head_object(Bucket="sovereign-configs-test", Key=body["key"])
    assert head["ContentLength"] > 0


@mock_aws
def test_get_config_returns_yaml(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        post = client.post("/render", json=_render_request(), headers=AUTH_HEADER)
        assert post.status_code == 200, post.text
        key_parts = post.json()["key"].split("/")
        instance_id, version = key_parts[1], int(key_parts[2].lstrip("v"))

        r = client.get(f"/instances/{instance_id}/versions/{version}/envoy.yaml")
        assert r.status_code == 200
        # 0.5 fixed get_config to return raw YAML with the correct
        # content-type rather than a JSON-encoded string.
        assert r.headers["content-type"].startswith("application/x-yaml")
        assert "static_resources" in r.text
        # Round-trip parses to a real document.
        import yaml

        doc = yaml.safe_load(r.text)
        assert any(c["name"] == "app" for c in doc["static_resources"]["clusters"])


@mock_aws
def test_get_config_404_for_missing(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        r = client.get("/instances/missing/versions/1/envoy.yaml")
        assert r.status_code == 404
        # Problem-detail shape installed in 0.5
        body = r.json()
        assert body["status"] == 404
        assert body["title"] == "not found"


def test_healthz_open(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert "envoy-snapshot" in r.json()["executors"]


# ── /diff drift-detection endpoint (ADR-0004) ──────────────────────────


@mock_aws
def test_diff_requires_bearer(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        r = client.post("/diff", json=_render_request())
        assert r.status_code == 401


@mock_aws
def test_diff_returns_drift_shape(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        r = client.post("/diff", json=_render_request(), headers=AUTH_HEADER)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["instance_id"] == "demo-lb"
        assert body["service_type"] == "sovereign-envoy-lb"
        # The Envoy LB manifest is s3-put (no executor → unchecked) +
        # envoy-snapshot (noop → in sync). Fail-safe: unknown, not drifted.
        assert body["drifted"] is False
        assert body["unknown"] is True
        assert isinstance(body["details"], list) and body["details"]


@mock_aws
def test_diff_unknown_service_404(control_plane_app: Any) -> None:
    inst = {
        "instance_id": "nope",
        "service_id": "does-not-exist",
        "plan_id": "x",
        "parameters": LbParameters().model_dump(mode="json"),
    }
    with TestClient(control_plane_app.app) as client:
        r = client.post("/diff", json={"instance": inst}, headers=AUTH_HEADER)
        assert r.status_code == 404
