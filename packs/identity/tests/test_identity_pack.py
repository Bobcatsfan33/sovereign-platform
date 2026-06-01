"""Tests for the Identity pack (Tier-3, config-driven)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

import sovereign_identity  # noqa: E402
from sovereign_identity.models import IdpBrokerParams, ScimBridgeParams  # noqa: E402
from sovereign_identity.renderers import (  # noqa: E402
    IdpBrokerRenderer,
    ScimBridgeRenderer,
)


def _instance(instance_id="idp-acme", service_id="idp-broker", **tags):  # type: ignore[no-untyped-def]
    from sovereign.models import LbParameters, ServiceInstance

    return ServiceInstance(
        instance_id=instance_id,
        service_id=service_id,
        plan_id="standard",
        parameters=LbParameters(tags={k: str(v) for k, v in tags.items()}),
    )


def test_idp_params_defaults() -> None:
    p = IdpBrokerParams(issuer_url="https://idp.gov")
    assert p.protocol == "oidc"
    assert p.require_mfa is True
    assert p.required_aal == "aal2"


def test_scim_params_defaults() -> None:
    p = ScimBridgeParams(endpoint_url="https://scim.gov")
    assert p.deprovision_on_remove is True


async def test_idp_render_config_only() -> None:
    r = IdpBrokerRenderer()
    artifact = await r.render(_instance(issuer_url="https://idp.agency.gov", required_aal="aal3"))
    assert "idp.json" in artifact.config_files
    cfg = json.loads(artifact.config_files["idp.json"])
    assert cfg["issuer_url"] == "https://idp.agency.gov"
    assert cfg["required_aal"] == "aal3"
    # Config-only: no deployment steps.
    assert artifact.deployment_manifest == []


async def test_idp_apply_is_noop_success() -> None:
    r = IdpBrokerRenderer()
    artifact = await r.render(_instance())
    assert (await r.validate(artifact)).ok
    ar = await r.apply(artifact)
    assert ar.ok
    assert ar.applied_steps == []


async def test_idp_validate_rejects_garbage() -> None:
    from sovereign.renderers import RenderedArtifact

    r = IdpBrokerRenderer()
    bad = RenderedArtifact(
        instance_id="x",
        service_type="idp-broker",
        version=1,
        config_files={"idp.json": b"{bad"},
    )
    assert not (await r.validate(bad)).ok


async def test_scim_render() -> None:
    r = ScimBridgeRenderer()
    inst = _instance("scim-acme", service_id="scim-bridge", endpoint_url="https://scim.gov", sync_interval_minutes=30)
    artifact = await r.render(inst)
    cfg = json.loads(artifact.config_files["scim.json"])
    assert cfg["sync_interval_minutes"] == 30
    assert cfg["deprovision_on_remove"] is True


def test_catalog_entries() -> None:
    idp = IdpBrokerRenderer.catalog_entry()
    assert idp.service_type == "idp-broker"
    assert "IA-2" in idp.metadata["controls"]
    scim = ScimBridgeRenderer.catalog_entry()
    assert "IA-4" in scim.metadata["controls"]


def test_pack_registers() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry
    from sovereign.renderers import registry as renderer_registry

    pack_registry.clear()
    register_pack(sovereign_identity.Pack())
    names = {p["name"] for p in __import__("sovereign.packs", fromlist=["registered_packs"]).registered_packs()}
    assert "sovereign-identity-pack" in names
    assert "idp-broker" in renderer_registry.service_types()
    assert "scim-bridge" in renderer_registry.service_types()
    assert (sovereign_identity.Pack().policy_bundles[0] / "identity.rego").exists()
