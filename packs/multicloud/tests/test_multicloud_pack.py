"""Tests for the Multi-Cloud pack (Tier-4, terraform-apply reuse)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

import sovereign_multicloud  # noqa: E402
from sovereign_multicloud.models import (  # noqa: E402
    APPROVED_REGIONS,
    CloudAccountParams,
    region_is_approved,
)
from sovereign_multicloud.renderers import (  # noqa: E402
    CloudAccountRenderer,
    LandingZoneRenderer,
)


def _instance(instance_id="acct", service_id="cloud-account", **tags):  # type: ignore[no-untyped-def]
    from sovereign.models import LbParameters, ServiceInstance

    return ServiceInstance(
        instance_id=instance_id,
        service_id=service_id,
        plan_id="baseline",
        parameters=LbParameters(tags={k: str(v) for k, v in tags.items()}),
    )


def test_region_approval_helper() -> None:
    assert region_is_approved("aws-govcloud", "us-gov-west-1") is True
    assert region_is_approved("aws-govcloud", "us-east-1") is False
    assert region_is_approved("azure-gov", "usgovvirginia") is True
    assert "us-central1" in APPROVED_REGIONS["gcp"]


def test_account_params_defaults() -> None:
    p = CloudAccountParams()
    assert p.provider == "aws-govcloud"
    assert p.guardrails_enabled is True
    assert p.org_audit_enabled is True


async def test_account_render_terraform_step() -> None:
    r = CloudAccountRenderer()
    artifact = await r.render(_instance(provider="azure-gov", region="usgovvirginia"))
    doc = json.loads(artifact.config_files["main.tf.json"])
    acct = doc["resource"]["sovereign_cloud_account"]["acct"]
    assert acct["provider"] == "azure-gov"
    assert artifact.deployment_manifest[0].kind == "terraform-apply"


async def test_account_validate_and_apply_delegates() -> None:
    from sovereign.executors import register_executor
    from sovereign.executors import registry as ex_registry
    from sovereign.executors.base import BaseExecutor, ExecResult

    r = CloudAccountRenderer()
    artifact = await r.render(_instance("a1"))
    assert (await r.validate(artifact)).ok

    ex_registry.clear()

    class _FakeTf(BaseExecutor):
        kind = "terraform-apply"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=True)

    register_executor(_FakeTf())
    assert (await r.apply(artifact)).ok


async def test_landing_zone_render() -> None:
    r = LandingZoneRenderer()
    inst = _instance("lz1", service_id="landing-zone", account_count=5)
    artifact = await r.render(inst)
    doc = json.loads(artifact.config_files["main.tf.json"])
    assert doc["resource"]["sovereign_landing_zone"]["lz1"]["account_count"] == 5
    assert artifact.deployment_manifest[0].kind == "terraform-apply"


def test_catalog_entries() -> None:
    acct = CloudAccountRenderer.catalog_entry()
    assert acct.service_type == "cloud-account"
    assert "CM-2" in acct.metadata["controls"]
    lz = LandingZoneRenderer.catalog_entry()
    assert "SC-7" in lz.metadata["controls"]


def test_pack_registers() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry
    from sovereign.renderers import registry as renderer_registry

    pack_registry.clear()
    register_pack(sovereign_multicloud.Pack())
    names = {p["name"] for p in __import__("sovereign.packs", fromlist=["registered_packs"]).registered_packs()}
    assert "sovereign-multicloud-pack" in names
    assert "cloud-account" in renderer_registry.service_types()
    assert "landing-zone" in renderer_registry.service_types()
    assert (sovereign_multicloud.Pack().policy_bundles[0] / "multicloud.rego").exists()
