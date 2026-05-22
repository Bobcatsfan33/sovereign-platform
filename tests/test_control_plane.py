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
def test_render_writes_to_s3(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        r = client.post("/render", json=_render_request())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["key"] == "instances/demo-lb/v1/envoy.yaml"

    # The startup hook created the bucket; verify the object landed.
    s3 = boto3.client("s3", region_name="us-east-1")
    head = s3.head_object(Bucket="sovereign-configs-test", Key=body["key"])
    assert head["ContentLength"] > 0


@mock_aws
def test_get_config_returns_yaml(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        post = client.post("/render", json=_render_request())
        key_parts = post.json()["key"].split("/")
        instance_id, version = key_parts[1], int(key_parts[2].lstrip("v"))

        r = client.get(f"/instances/{instance_id}/versions/{version}/envoy.yaml")
        assert r.status_code == 200
        # The current route returns a Python str, which FastAPI JSON-encodes.
        # Task 0.5 will switch this to PlainTextResponse with the right
        # content-type; until then we just verify the rendered YAML
        # made it through round-trip (look for our cluster name).
        assert "app" in r.text
        assert "static_resources" in r.text


@mock_aws
def test_get_config_404_for_missing(control_plane_app: Any) -> None:
    with TestClient(control_plane_app.app) as client:
        r = client.get("/instances/missing/versions/1/envoy.yaml")
        assert r.status_code == 404


def test_healthz_open(control_plane_app: Any) -> None:
    client = TestClient(control_plane_app.app)
    r = client.get("/healthz")
    assert r.status_code == 200
