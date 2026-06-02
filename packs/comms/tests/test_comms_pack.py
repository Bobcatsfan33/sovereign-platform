"""Tests for the Comms pack (Tier-4, config-driven)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

import sovereign_comms  # noqa: E402
from sovereign_comms.models import SecureEmailParams, is_fips_suite  # noqa: E402
from sovereign_comms.renderers import (  # noqa: E402
    SecureChatRenderer,
    SecureEmailRenderer,
)


def _instance(instance_id="mail1", service_id="secure-email", **tags):  # type: ignore[no-untyped-def]
    from sovereign.models import LbParameters, ServiceInstance

    return ServiceInstance(
        instance_id=instance_id,
        service_id=service_id,
        plan_id="standard",
        parameters=LbParameters(tags={k: str(v) for k, v in tags.items()}),
    )


def test_fips_suite_helper() -> None:
    assert is_fips_suite("TLS_AES_256_GCM_SHA384") is True
    assert is_fips_suite("TLS_RSA_WITH_RC4_128_SHA") is False


def test_email_params_defaults() -> None:
    p = SecureEmailParams()
    assert p.tls_required is True
    assert p.dlp_enabled is True
    assert p.retention_days == 2555


async def test_email_render_config_only() -> None:
    r = SecureEmailRenderer()
    artifact = await r.render(_instance(retention_days=3000))
    cfg = json.loads(artifact.config_files["email.json"])
    assert cfg["retention_days"] == 3000
    assert artifact.deployment_manifest == []


async def test_email_apply_noop_success() -> None:
    r = SecureEmailRenderer()
    artifact = await r.render(_instance())
    assert (await r.validate(artifact)).ok
    ar = await r.apply(artifact)
    assert ar.ok
    assert ar.applied_steps == []


async def test_email_validate_rejects_garbage() -> None:
    from sovereign.renderers import RenderedArtifact

    r = SecureEmailRenderer()
    bad = RenderedArtifact(
        instance_id="x", service_type="secure-email", version=1,
        config_files={"email.json": b"{bad"},
    )
    assert not (await r.validate(bad)).ok


async def test_chat_render() -> None:
    r = SecureChatRenderer()
    inst = _instance("chat1", service_id="secure-chat", external_federation="false")
    artifact = await r.render(inst)
    cfg = json.loads(artifact.config_files["chat.json"])
    assert cfg["external_federation"] is False


def test_catalog_entries() -> None:
    email = SecureEmailRenderer.catalog_entry()
    assert email.service_type == "secure-email"
    assert "AU-11" in email.metadata["controls"]
    chat = SecureChatRenderer.catalog_entry()
    assert "AC-4" in chat.metadata["controls"]


def test_pack_registers() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry
    from sovereign.renderers import registry as renderer_registry

    pack_registry.clear()
    register_pack(sovereign_comms.Pack())
    names = {p["name"] for p in __import__("sovereign.packs", fromlist=["registered_packs"]).registered_packs()}
    assert "sovereign-comms-pack" in names
    assert "secure-email" in renderer_registry.service_types()
    assert "secure-chat" in renderer_registry.service_types()
    assert (sovereign_comms.Pack().policy_bundles[0] / "comms.rego").exists()
