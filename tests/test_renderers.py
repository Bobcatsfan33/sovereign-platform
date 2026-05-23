"""Tests for the pluggable renderer subsystem (Phase 1 tasks 1.1, 1.2, 1.3, 1.8)."""

from __future__ import annotations

from typing import ClassVar

import boto3
import pytest
from moto import mock_aws
from sovereign.models import (
    Cluster,
    LbParameters,
    Listener,
    Route,
    ServiceInstance,
)
from sovereign.renderers import (
    ApplyResult,
    BaseRenderer,
    DeploymentStep,
    RenderedArtifact,
    TeardownResult,
    ValidationResult,
    get_renderer,
    register_renderer,
    registry,
)
from sovereign.renderers.envoy import EnvoyRenderer


def _instance() -> ServiceInstance:
    return ServiceInstance(
        instance_id="demo-r",
        service_id="sovereign-envoy-lb",
        plan_id="standard-regional",
        parameters=LbParameters(
            listeners=[Listener(name="http", port=8080, protocol="HTTP")],
            routes=[Route(host="app.local", prefix="/", cluster="app")],
            clusters=[Cluster(name="app", endpoints=["127.0.0.1:3000"])],
        ),
    )


# ── BaseRenderer / registry contract ──────────────────────────────────


class _Dummy(BaseRenderer):
    service_type: ClassVar[str] = "test-dummy"

    async def render(self, instance):  # type: ignore[no-untyped-def]
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"x.txt": b"hello"},
        )

    async def validate(self, artifact):  # type: ignore[no-untyped-def]
        return ValidationResult(ok=True)

    async def apply(self, artifact):  # type: ignore[no-untyped-def]
        return ApplyResult(ok=True)

    async def teardown(self, instance):  # type: ignore[no-untyped-def]
        return TeardownResult(ok=True)


def test_subclass_requires_service_type() -> None:
    with pytest.raises(TypeError, match="service_type"):

        class _Bad(BaseRenderer):  # missing service_type
            async def render(self, instance):  # type: ignore[no-untyped-def]
                ...

            async def validate(self, artifact):  # type: ignore[no-untyped-def]
                ...

            async def apply(self, artifact):  # type: ignore[no-untyped-def]
                ...

            async def teardown(self, instance):  # type: ignore[no-untyped-def]
                ...


def test_register_and_get(caplog: pytest.LogCaptureFixture) -> None:
    register_renderer(_Dummy())
    r = get_renderer("test-dummy")
    assert r is not None
    assert r.service_type == "test-dummy"
    assert "test-dummy" in registry.service_types()


def test_require_unknown_raises_key_error() -> None:
    with pytest.raises(KeyError):
        registry.require("does-not-exist")


def test_register_with_missing_service_type_raises() -> None:
    class _Half(BaseRenderer):
        service_type: ClassVar[str] = "tmp"

        async def render(self, instance):  # type: ignore[no-untyped-def]
            ...

        async def validate(self, artifact):  # type: ignore[no-untyped-def]
            ...

        async def apply(self, artifact):  # type: ignore[no-untyped-def]
            ...

        async def teardown(self, instance):  # type: ignore[no-untyped-def]
            ...

    inst = _Half()
    inst.service_type = ""  # type: ignore[assignment]
    with pytest.raises(ValueError, match="service_type"):
        register_renderer(inst)


def test_override_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    register_renderer(_Dummy())

    class _Other(BaseRenderer):
        service_type: ClassVar[str] = "test-dummy"

        async def render(self, instance):  # type: ignore[no-untyped-def]
            ...

        async def validate(self, artifact):  # type: ignore[no-untyped-def]
            ...

        async def apply(self, artifact):  # type: ignore[no-untyped-def]
            ...

        async def teardown(self, instance):  # type: ignore[no-untyped-def]
            ...

    caplog.set_level(logging.WARNING, logger="sovereign.renderers")
    register_renderer(_Other())
    assert any("replaced" in r.message for r in caplog.records)


# ── EnvoyRenderer behaviour ───────────────────────────────────────────


async def test_envoy_render_returns_artifact_with_yaml() -> None:
    artifact = await EnvoyRenderer().render(_instance())
    assert artifact.service_type == "sovereign-envoy-lb"
    assert artifact.instance_id == "demo-r"
    assert artifact.version == 1
    assert "envoy.yaml" in artifact.config_files
    body = artifact.config_files["envoy.yaml"]
    assert b"static_resources" in body
    assert b"app.local" in body
    # Metadata records the shape so the state layer can summarise without
    # parsing the YAML again.
    assert artifact.metadata == {"listener_count": 1, "cluster_count": 1, "route_count": 1}
    # Manifest has the expected two steps.
    kinds = [s.kind for s in artifact.deployment_manifest]
    assert kinds == ["s3-put", "envoy-snapshot"]


async def test_envoy_validate_ok_for_good_artifact() -> None:
    r = EnvoyRenderer()
    artifact = await r.render(_instance())
    vr = await r.validate(artifact)
    assert vr.ok
    assert vr.errors == []


async def test_envoy_validate_fails_for_missing_yaml() -> None:
    r = EnvoyRenderer()
    artifact = await r.render(_instance())
    artifact.config_files.pop("envoy.yaml")
    vr = await r.validate(artifact)
    assert not vr.ok
    assert any("missing envoy.yaml" in e for e in vr.errors)


async def test_envoy_validate_fails_for_corrupted_yaml() -> None:
    r = EnvoyRenderer()
    artifact = await r.render(_instance())
    artifact.config_files["envoy.yaml"] = b"not: [valid: yaml"
    vr = await r.validate(artifact)
    assert not vr.ok


async def test_envoy_apply_writes_to_s3() -> None:
    # `mock_aws` as a context manager — its decorator form doesn't compose
    # with pytest-asyncio's auto-mode wrapping of async test functions.
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="sovereign-configs-test")
        r = EnvoyRenderer()
        artifact = await r.render(_instance())
        ar = await r.apply(artifact)
        assert ar.ok
        assert len(ar.applied_steps) == 2
        obj = boto3.client("s3", region_name="us-east-1").get_object(
            Bucket="sovereign-configs-test",
            Key="instances/demo-r/v1/envoy.yaml",
        )
        assert obj["ContentType"] == "application/x-yaml"
        assert b"static_resources" in obj["Body"].read()


async def test_envoy_apply_failure_returns_failed_step() -> None:
    with mock_aws():
        # Bucket NOT created -> S3 put fails -> apply returns failed_step.
        r = EnvoyRenderer()
        artifact = await r.render(_instance())
        ar = await r.apply(artifact)
        assert not ar.ok
        assert ar.failed_step is not None
        assert ar.failed_step.kind == "s3-put"


async def test_envoy_apply_skips_unknown_step_kinds() -> None:
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="sovereign-configs-test")
        r = EnvoyRenderer()
        artifact = await r.render(_instance())
        artifact.deployment_manifest.append(DeploymentStep(kind="unknown-kind", target="x"))
        ar = await r.apply(artifact)
        assert ar.ok  # skips unknown kinds rather than failing


async def test_envoy_teardown_deletes_s3_prefix() -> None:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="sovereign-configs-test")
        r = EnvoyRenderer()
        inst = _instance()
        # Lay down two versions then ensure teardown wipes both.
        await r.apply(await r.render(inst))
        inst.version = 2
        await r.apply(await r.render(inst))

        tr = await r.teardown(inst)
        assert tr.ok
        assert set(tr.removed) == {
            "instances/demo-r/v1/envoy.yaml",
            "instances/demo-r/v2/envoy.yaml",
        }
        # The prefix is now empty.
        resp = s3.list_objects_v2(Bucket="sovereign-configs-test", Prefix="instances/demo-r/")
        assert resp.get("KeyCount", 0) == 0


# ── End-to-end: control-plane dispatches through registry ─────────────


@mock_aws
def test_control_plane_render_returns_service_type_and_manifest(
    control_plane_module, monkeypatch
):  # type: ignore[no-untyped-def]
    """Sanity check that the control-plane response now carries the
    service_type and applied manifest from the new renderer pipeline."""
    from fastapi.testclient import TestClient

    from .conftest import AUTH_HEADER

    class FakeAudit:
        def emit(self, *a, **kw):  # type: ignore[no-untyped-def]
            ...

    monkeypatch.setattr(control_plane_module, "audit", FakeAudit())

    inst = _instance()
    body = {"instance": inst.model_dump(mode="json")}
    with TestClient(control_plane_module.app) as client:
        r = client.post("/render", json=body, headers=AUTH_HEADER)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["service_type"] == "sovereign-envoy-lb"
        assert j["key"] == "instances/demo-r/v1/envoy.yaml"
        assert j["manifest"][0]["kind"] == "s3-put"


@mock_aws
def test_control_plane_render_404_for_unknown_service_type(
    control_plane_module, monkeypatch
):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from .conftest import AUTH_HEADER

    inst = _instance()
    inst.service_id = "definitely-not-registered"
    body = {"instance": inst.model_dump(mode="json")}
    with TestClient(control_plane_module.app) as client:
        r = client.post("/render", json=body, headers=AUTH_HEADER)
        assert r.status_code == 404
        assert "no renderer" in r.json()["detail"]


@mock_aws
def test_healthz_lists_registered_renderers(control_plane_module) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    client = TestClient(control_plane_module.app)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert "sovereign-envoy-lb" in r.json()["renderers"]
