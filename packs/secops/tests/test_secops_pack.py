"""Tests for the SecOps pack (Tier-3)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

import sovereign_secops  # noqa: E402
from sovereign_secops.models import SiemWorkspaceParams  # noqa: E402
from sovereign_secops.renderers import (  # noqa: E402
    LogPipelineRenderer,
    SiemWorkspaceRenderer,
)


def _instance(instance_id="demo-siem", service_id="siem-workspace", **tags):  # type: ignore[no-untyped-def]
    from sovereign.models import LbParameters, ServiceInstance

    return ServiceInstance(
        instance_id=instance_id,
        service_id=service_id,
        plan_id="standard",
        parameters=LbParameters(tags={k: str(v) for k, v in tags.items()}),
    )


def test_siem_params_defaults() -> None:
    p = SiemWorkspaceParams()
    assert p.backend == "opensearch"
    assert p.immutable_storage is True
    assert p.retention_days == 90


async def test_siem_render_statefulset_with_au_annotations() -> None:
    r = SiemWorkspaceRenderer()
    artifact = await r.render(_instance(retention_days=120))
    doc = yaml.safe_load(artifact.config_files["siem.yaml"])
    assert doc["kind"] == "StatefulSet"
    ann = doc["metadata"]["annotations"]
    assert ann["sovereign.au11/retention-days"] == "120"
    assert ann["sovereign.au9/immutable"] == "true"
    assert artifact.deployment_manifest[0].kind == "k8s-apply"


async def test_siem_render_hardened_container() -> None:
    r = SiemWorkspaceRenderer()
    artifact = await r.render(_instance())
    doc = yaml.safe_load(artifact.config_files["siem.yaml"])
    sc = doc["spec"]["template"]["spec"]["containers"][0]["securityContext"]
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["allowPrivilegeEscalation"] is False


async def test_siem_validate_and_apply_delegates() -> None:
    from sovereign.executors import NoopExecutor, register_executor
    from sovereign.executors import registry as ex_registry
    from sovereign.executors.base import BaseExecutor, ExecResult

    r = SiemWorkspaceRenderer()
    artifact = await r.render(_instance())
    assert (await r.validate(artifact)).ok

    ex_registry.clear()
    register_executor(NoopExecutor())

    class _FakeK8s(BaseExecutor):
        kind = "k8s-apply"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=True)

    register_executor(_FakeK8s())
    ar = await r.apply(artifact)
    assert ar.ok


async def test_log_pipeline_render() -> None:
    r = LogPipelineRenderer()
    inst = _instance("pipe1", service_id="log-pipeline", sources="s3")
    artifact = await r.render(inst)
    doc = yaml.safe_load(artifact.config_files["pipeline.yaml"])
    assert doc["kind"] == "ConfigMap"
    assert artifact.deployment_manifest[0].kind == "k8s-apply"


def test_catalog_entries() -> None:
    siem = SiemWorkspaceRenderer.catalog_entry()
    assert siem.service_type == "siem-workspace"
    assert "AU-11" in siem.metadata["controls"]
    pipe = LogPipelineRenderer.catalog_entry()
    assert "AU-10" in pipe.metadata["controls"]


def test_pack_registers() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry
    from sovereign.renderers import registry as renderer_registry

    pack_registry.clear()
    register_pack(sovereign_secops.Pack())
    names = {p["name"] for p in __import__("sovereign.packs", fromlist=["registered_packs"]).registered_packs()}
    assert "sovereign-secops-pack" in names
    assert "siem-workspace" in renderer_registry.service_types()
    assert "log-pipeline" in renderer_registry.service_types()
    assert (sovereign_secops.Pack().policy_bundles[0] / "secops.rego").exists()
