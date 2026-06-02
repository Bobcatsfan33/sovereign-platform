"""Tests for the Edge pack (Tier-4)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

import sovereign_edge  # noqa: E402
from sovereign_edge.models import EdgeNodeParams  # noqa: E402
from sovereign_edge.renderers import EdgeClusterRenderer, EdgeNodeRenderer  # noqa: E402


def _instance(instance_id="edge1", service_id="edge-node", **tags):  # type: ignore[no-untyped-def]
    from sovereign.models import LbParameters, ServiceInstance

    return ServiceInstance(
        instance_id=instance_id,
        service_id=service_id,
        plan_id="standard",
        parameters=LbParameters(tags={k: str(v) for k, v in tags.items()}),
    )


def test_node_params_defaults() -> None:
    p = EdgeNodeParams()
    assert p.fips_image is True
    assert p.attestation_required is True
    assert p.disk_encryption is True


async def test_node_render_pod_with_integrity_annotations() -> None:
    r = EdgeNodeRenderer()
    artifact = await r.render(_instance())
    doc = yaml.safe_load(artifact.config_files["node.yaml"])
    assert doc["kind"] == "Pod"
    ann = doc["metadata"]["annotations"]
    assert ann["sovereign.si7/fips-image"] == "true"
    assert ann["sovereign.si7-9/attestation"] == "true"
    assert artifact.deployment_manifest[0].kind == "k8s-apply"


async def test_node_hardened_container() -> None:
    r = EdgeNodeRenderer()
    artifact = await r.render(_instance())
    doc = yaml.safe_load(artifact.config_files["node.yaml"])
    sc = doc["spec"]["containers"][0]["securityContext"]
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"]["drop"] == ["ALL"]


async def test_node_validate_and_apply_delegates() -> None:
    from sovereign.executors import NoopExecutor, register_executor
    from sovereign.executors import registry as ex_registry
    from sovereign.executors.base import BaseExecutor, ExecResult

    r = EdgeNodeRenderer()
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


async def test_cluster_render_daemonset() -> None:
    r = EdgeClusterRenderer()
    inst = _instance("edge-cl", service_id="edge-cluster", node_count=5)
    artifact = await r.render(inst)
    doc = yaml.safe_load(artifact.config_files["cluster.yaml"])
    assert doc["kind"] == "DaemonSet"
    assert doc["metadata"]["annotations"]["sovereign.edge/node-count"] == "5"


def test_catalog_entries() -> None:
    node = EdgeNodeRenderer.catalog_entry()
    assert node.service_type == "edge-node"
    assert "SI-7" in node.metadata["controls"]
    cluster = EdgeClusterRenderer.catalog_entry()
    assert "AC-4" in cluster.metadata["controls"]


def test_pack_registers() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry
    from sovereign.renderers import registry as renderer_registry

    pack_registry.clear()
    register_pack(sovereign_edge.Pack())
    names = {p["name"] for p in __import__("sovereign.packs", fromlist=["registered_packs"]).registered_packs()}
    assert "sovereign-edge-pack" in names
    assert "edge-node" in renderer_registry.service_types()
    assert "edge-cluster" in renderer_registry.service_types()
    assert (sovereign_edge.Pack().policy_bundles[0] / "edge.rego").exists()
