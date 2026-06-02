"""Tests for the Blockchain pack (Tier-4, final pack)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

import sovereign_blockchain  # noqa: E402
from sovereign_blockchain.models import PermissionedLedgerParams, is_bft  # noqa: E402
from sovereign_blockchain.renderers import PermissionedLedgerRenderer  # noqa: E402


def _instance(instance_id="ledger1", **tags):  # type: ignore[no-untyped-def]
    from sovereign.models import LbParameters, ServiceInstance

    return ServiceInstance(
        instance_id=instance_id,
        service_id="permissioned-ledger",
        plan_id="fabric",
        parameters=LbParameters(tags={k: str(v) for k, v in tags.items()}),
    )


def test_bft_helper() -> None:
    assert is_bft("qbft") is True
    assert is_bft("ibft2") is True
    assert is_bft("raft") is False


def test_ledger_params_defaults() -> None:
    p = PermissionedLedgerParams()
    assert p.platform == "fabric"
    assert p.permissioned is True
    assert p.hsm_key_custody is True
    assert p.fips_crypto is True


async def test_render_statefulset_with_governance_annotations() -> None:
    r = PermissionedLedgerRenderer()
    artifact = await r.render(_instance(platform="besu", consensus="qbft", validator_count=10))
    doc = yaml.safe_load(artifact.config_files["ledger.yaml"])
    assert doc["kind"] == "StatefulSet"
    assert doc["spec"]["replicas"] == 10
    ann = doc["metadata"]["annotations"]
    assert ann["sovereign.ac3/permissioned"] == "true"
    assert ann["sovereign.sc12/hsm-custody"] == "true"
    assert ann["sovereign.ledger/consensus"] == "qbft"
    assert artifact.deployment_manifest[0].kind == "k8s-apply"


async def test_render_hardened_container() -> None:
    r = PermissionedLedgerRenderer()
    artifact = await r.render(_instance())
    doc = yaml.safe_load(artifact.config_files["ledger.yaml"])
    sc = doc["spec"]["template"]["spec"]["containers"][0]["securityContext"]
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"]["drop"] == ["ALL"]


async def test_validate_and_apply_delegates() -> None:
    from sovereign.executors import NoopExecutor, register_executor
    from sovereign.executors import registry as ex_registry
    from sovereign.executors.base import BaseExecutor, ExecResult

    r = PermissionedLedgerRenderer()
    artifact = await r.render(_instance())
    assert (await r.validate(artifact)).ok

    ex_registry.clear()
    register_executor(NoopExecutor())

    class _FakeK8s(BaseExecutor):
        kind = "k8s-apply"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=True)

    register_executor(_FakeK8s())
    assert (await r.apply(artifact)).ok


async def test_validate_rejects_garbage() -> None:
    from sovereign.renderers import RenderedArtifact

    r = PermissionedLedgerRenderer()
    bad = RenderedArtifact(
        instance_id="x", service_type="permissioned-ledger", version=1,
        config_files={"ledger.yaml": b"not: [valid"},
    )
    assert not (await r.validate(bad)).ok


def test_catalog_entry() -> None:
    e = PermissionedLedgerRenderer.catalog_entry()
    assert e.service_type == "permissioned-ledger"
    assert e.pack == "blockchain"
    assert "SC-12" in e.metadata["controls"]
    assert {p.id for p in e.plans} == {"fabric", "besu"}


def test_pack_registers() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry
    from sovereign.renderers import registry as renderer_registry

    pack_registry.clear()
    register_pack(sovereign_blockchain.Pack())
    names = {p["name"] for p in __import__("sovereign.packs", fromlist=["registered_packs"]).registered_packs()}
    assert "sovereign-blockchain-pack" in names
    assert "permissioned-ledger" in renderer_registry.service_types()
    assert (sovereign_blockchain.Pack().policy_bundles[0] / "blockchain.rego").exists()
