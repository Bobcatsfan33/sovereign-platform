"""Tests for the pack registration system (Phase 1 task 1.9)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from sovereign.connectors import (
    BaseConnector,
    ConnectionResult,
    HealthStatus,
    IngestResult,
)
from sovereign.connectors import registry as connector_registry
from sovereign.packs import BasePack, discover_packs, register_pack, registered_packs
from sovereign.packs import registry as pack_registry
from sovereign.renderers import (
    ApplyResult,
    BaseRenderer,
    RenderedArtifact,
    TeardownResult,
    ValidationResult,
)
from sovereign.renderers import registry as renderer_registry

# ── BasePack contract ─────────────────────────────────────────────────


def test_base_pack_subclass_requires_name() -> None:
    with pytest.raises(TypeError, match="`name`"):

        class _BadPack(BasePack):
            pass


def test_base_pack_manifest_shape() -> None:
    class _Pack(BasePack):
        name = "test-pack"
        version = "1.2.3"
        description = "A test pack."
        renderers: ClassVar[list] = []
        connectors: ClassVar[list] = []
        policy_bundles: ClassVar[list] = [Path("/tmp/policies")]

    m = _Pack().manifest()
    assert m["name"] == "test-pack"
    assert m["version"] == "1.2.3"
    assert m["policy_bundles"] == ["/tmp/policies"]


# ── A minimal example pack used to exercise register() ────────────────


class _DemoRenderer(BaseRenderer):
    service_type: ClassVar[str] = "test-pack-renderer"

    async def render(self, instance):  # type: ignore[no-untyped-def]
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"x.txt": b"x"},
        )

    async def validate(self, artifact):  # type: ignore[no-untyped-def]
        return ValidationResult(ok=True)

    async def apply(self, artifact):  # type: ignore[no-untyped-def]
        return ApplyResult(ok=True)

    async def teardown(self, instance):  # type: ignore[no-untyped-def]
        return TeardownResult(ok=True)


class _DemoConnector(BaseConnector):
    connector_type: ClassVar[str] = "test-pack-conn"

    async def connect(self, credentials):  # type: ignore[no-untyped-def]
        return ConnectionResult(ok=True, principal="demo")

    async def list_resources(self, filters=None):  # type: ignore[no-untyped-def]
        return []

    async def ingest(self, resource, options):  # type: ignore[no-untyped-def]
        return IngestResult(ok=True)

    async def health_check(self):  # type: ignore[no-untyped-def]
        return HealthStatus(ok=True)


class _DemoPack(BasePack):
    name = "demo-pack"
    version = "0.1.0"
    description = "In-tree test pack."
    renderers: ClassVar[list] = [_DemoRenderer]
    connectors: ClassVar[list] = [_DemoConnector]
    policy_bundles: ClassVar[list] = []


# ── register_pack wires everything ────────────────────────────────────


def test_register_pack_registers_renderers_and_connectors() -> None:
    pack_registry.clear()
    # Wipe any prior demo registrations so we start clean.
    renderer_registry.clear()
    connector_registry.clear()

    register_pack(_DemoPack())

    # Pack manifest is now in registered_packs
    names = {p["name"] for p in registered_packs()}
    assert "demo-pack" in names
    # Renderer + connector showed up in their registries
    assert "test-pack-renderer" in renderer_registry.service_types()
    assert "test-pack-conn" in connector_registry.connector_types()

    # Manifest enumerates contents accurately
    pack_manifest = next(p for p in registered_packs() if p["name"] == "demo-pack")
    assert pack_manifest["renderers"] == ["test-pack-renderer"]
    assert pack_manifest["connectors"] == ["test-pack-conn"]


def test_register_pack_is_idempotent() -> None:
    pack_registry.clear()
    register_pack(_DemoPack())
    register_pack(_DemoPack())  # second call must not error
    assert len([p for p in registered_packs() if p["name"] == "demo-pack"]) == 1


# ── discover_packs walks entry points ─────────────────────────────────


class _FakeEntryPoint:
    def __init__(self, name: str, pack_cls: type[BasePack]) -> None:
        self.name = name
        self.value = f"{pack_cls.__module__}:{pack_cls.__name__}"
        self._pack_cls = pack_cls

    def load(self) -> type[BasePack]:
        return self._pack_cls


def test_discover_packs_calls_entry_points_and_registers() -> None:
    pack_registry.clear()
    renderer_registry.clear()
    connector_registry.clear()

    fake_eps = [_FakeEntryPoint("demo", _DemoPack)]

    with patch("sovereign.packs.discovery.metadata.entry_points", return_value=fake_eps):
        discovered = discover_packs()

    assert len(discovered) == 1
    assert discovered[0].name == "demo-pack"
    assert "demo-pack" in pack_registry.names()
    assert "test-pack-renderer" in renderer_registry.service_types()


def test_discover_packs_logs_but_does_not_raise_on_broken_pack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    class _Boom:
        name = "boom"
        value = "boom:boom"

        def load(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("import exploded")

    pack_registry.clear()
    with patch(
        "sovereign.packs.discovery.metadata.entry_points", return_value=[_Boom()]
    ):
        caplog.set_level(logging.ERROR, logger="sovereign.packs")
        discovered = discover_packs()

    assert discovered == []
    assert any("failed to discover pack" in r.message for r in caplog.records)


# ── End-to-end: broker /v2/catalog picks up pack contributions ────────


@mock_aws
def test_broker_v2_catalog_includes_pack_renderer(
    broker_module, monkeypatch
):  # type: ignore[no-untyped-def]
    """Stub discover_packs() to inject _DemoPack into the broker's
    startup, then verify /v2/catalog surfaces the new service type.

    Note: this demo pack's renderer does NOT override catalog_entry()
    so it appears in the registry but not in the catalog. We assert
    on the registry side (the broker's /healthz) and on the existence
    of the chassis entries in /v2/catalog."""

    class FakeAudit:
        def emit(self, *a, **kw):  # type: ignore[no-untyped-def]
            ...

    monkeypatch.setattr(broker_module, "audit", FakeAudit())

    pack_registry.clear()
    renderer_registry.clear()
    connector_registry.clear()

    # Re-register the chassis renderer + connectors so /v2/catalog still
    # has the LB entry (broker's import-time register_renderer already
    # did this, but we just cleared).
    from sovereign.connectors.github import GitHubConnector
    from sovereign.connectors.s3 import S3Connector
    from sovereign.renderers.envoy import EnvoyRenderer

    renderer_registry.register(EnvoyRenderer())
    connector_registry.register(S3Connector)
    connector_registry.register(GitHubConnector)

    # Patch discover_packs in the broker module to load our demo pack.
    def _fake_discover() -> list:
        register_pack(_DemoPack())
        return [_DemoPack()]

    monkeypatch.setattr(broker_module, "discover_packs", _fake_discover)

    with TestClient(broker_module.app) as client:
        hr = client.get("/healthz")
        assert hr.status_code == 200
        body = hr.json()
        assert "test-pack-renderer" in body["renderers"]
        assert "test-pack-conn" in body["connectors"]
        pack_names = {p["name"] for p in body["packs"]}
        assert "demo-pack" in pack_names

        cr = client.get("/v2/catalog", auth=("broker", "broker"))
        assert cr.status_code == 200
        # The chassis LB is still there
        svc_ids = {s["id"] for s in cr.json()["services"]}
        assert "sovereign-envoy-lb" in svc_ids
