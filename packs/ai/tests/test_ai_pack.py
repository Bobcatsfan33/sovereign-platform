"""Tests for the AI pack (Tier-1 flagship pack).

Exercises the inference + RAG renderers (pure render → manifest), that
apply() delegates to the chassis executor subsystem, and that the Pack
registers and contributes its catalog entries through chassis machinery.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PACK_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK_ROOT))

import sovereign_ai  # noqa: E402
from sovereign_ai.models import (  # noqa: E402
    GPU_ACCELERATORS,
    InferenceEndpointParams,
    RagWorkspaceParams,
    is_gpu,
)
from sovereign_ai.renderers import (  # noqa: E402
    InferenceEndpointRenderer,
    RagWorkspaceRenderer,
)


def _instance(instance_id: str = "demo-infer", **tags):  # type: ignore[no-untyped-def]
    from sovereign.models import LbParameters, ServiceInstance

    return ServiceInstance(
        instance_id=instance_id,
        service_id="inference-endpoint",
        plan_id="a10",
        parameters=LbParameters(tags={k: str(v) for k, v in tags.items()}),
    )


# ── models ────────────────────────────────────────────────────────────


def test_is_gpu_classification() -> None:
    assert is_gpu("a100") is True
    assert is_gpu("h100") is True
    assert is_gpu("cpu") is False
    assert {"a10", "a100", "h100"} == GPU_ACCELERATORS


def test_inference_params_defaults() -> None:
    p = InferenceEndpointParams(model_id="llama-3-8b")
    assert p.engine == "vllm"
    assert p.pii_redaction is True
    assert p.classification == "U"


def test_rag_params_defaults() -> None:
    p = RagWorkspaceParams(name="docs")
    assert p.vector_store == "pgvector"
    assert p.encryption_at_rest is True


# ── inference renderer ────────────────────────────────────────────────


async def test_inference_render_emits_k8s_manifest() -> None:
    r = InferenceEndpointRenderer()
    artifact = await r.render(_instance(model_id="llama-3-8b", accelerator="a100"))
    assert artifact.service_type == "inference-endpoint"
    assert "deployment.yaml" in artifact.config_files
    assert artifact.metadata["gpu"] is True
    # Single k8s-apply step targeting the AI namespace.
    assert len(artifact.deployment_manifest) == 1
    step = artifact.deployment_manifest[0]
    assert step.kind == "k8s-apply"
    assert step.target == "sovereign-ai"


async def test_inference_render_gpu_resource_limit() -> None:
    import yaml

    r = InferenceEndpointRenderer()
    artifact = await r.render(_instance(model_id="m", accelerator="h100"))
    doc = yaml.safe_load(artifact.config_files["deployment.yaml"])
    limits = doc["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
    assert limits["nvidia.com/gpu"] == "1"
    # Hardened container context.
    sc = doc["spec"]["template"]["spec"]["containers"][0]["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["readOnlyRootFilesystem"] is True


async def test_inference_cpu_has_no_gpu_limit() -> None:
    import yaml

    r = InferenceEndpointRenderer()
    artifact = await r.render(_instance(model_id="m", accelerator="cpu"))
    doc = yaml.safe_load(artifact.config_files["deployment.yaml"])
    limits = doc["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
    assert "nvidia.com/gpu" not in limits


async def test_inference_validate_ok_and_apply_delegates() -> None:
    from sovereign.executors import NoopExecutor, register_executor
    from sovereign.executors import registry as ex_registry
    from sovereign.executors.base import BaseExecutor, ExecResult

    r = InferenceEndpointRenderer()
    artifact = await r.render(_instance(model_id="m"))
    vr = await r.validate(artifact)
    assert vr.ok

    # Register a fake k8s-apply executor so apply() round-trips through the
    # chassis dispatcher rather than touching a real cluster.
    ex_registry.clear()
    register_executor(NoopExecutor())

    class _FakeK8s(BaseExecutor):
        kind = "k8s-apply"

        async def execute(self, step):  # type: ignore[no-untyped-def]
            return ExecResult(ok=True, detail=f"applied {step.target}")

    register_executor(_FakeK8s())
    ar = await r.apply(artifact)
    assert ar.ok
    assert len(ar.applied_steps) == 1


async def test_inference_validate_rejects_garbage() -> None:
    from sovereign.renderers import RenderedArtifact

    r = InferenceEndpointRenderer()
    bad = RenderedArtifact(
        instance_id="x",
        service_type="inference-endpoint",
        version=1,
        config_files={"deployment.yaml": b"not: [valid"},
    )
    vr = await r.validate(bad)
    assert not vr.ok


# ── rag renderer ──────────────────────────────────────────────────────


async def test_rag_render_emits_configmap() -> None:
    import yaml

    r = RagWorkspaceRenderer()
    inst = _instance("docs-rag")
    inst.service_id = "rag-workspace"
    artifact = await r.render(inst)
    assert "rag.yaml" in artifact.config_files
    doc = yaml.safe_load(artifact.config_files["rag.yaml"])
    assert doc["kind"] == "ConfigMap"
    assert artifact.deployment_manifest[0].kind == "k8s-apply"


# ── catalog entries ───────────────────────────────────────────────────


def test_inference_catalog_entry_shape() -> None:
    e = InferenceEndpointRenderer.catalog_entry()
    assert e.service_type == "inference-endpoint"
    assert e.pack == "ai"
    assert {p.id for p in e.plans} == {"cpu-small", "a10", "a100", "h100"}
    assert "SC-8" in e.metadata["controls"]


def test_rag_catalog_entry_shape() -> None:
    e = RagWorkspaceRenderer.catalog_entry()
    assert e.service_type == "rag-workspace"
    assert "SC-28" in e.metadata["controls"]


# ── pack registration ─────────────────────────────────────────────────


def test_pack_registers_renderers_and_bundle() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry
    from sovereign.renderers import registry as renderer_registry

    pack_registry.clear()
    register_pack(sovereign_ai.Pack())

    names = {p["name"] for p in __import__("sovereign.packs", fromlist=["registered_packs"]).registered_packs()}
    assert "sovereign-ai-pack" in names
    assert "inference-endpoint" in renderer_registry.service_types()
    assert "rag-workspace" in renderer_registry.service_types()

    pack = sovereign_ai.Pack()
    assert len(pack.policy_bundles) == 1
    assert (pack.policy_bundles[0] / "ai.rego").exists()


def test_pack_policy_bundle_collected() -> None:
    from sovereign.packs import register_pack
    from sovereign.packs import registry as pack_registry
    from sovereign.packs.policy_bundles import collect_policy_bundle_dirs

    pack_registry.clear()
    register_pack(sovereign_ai.Pack())
    dirs = collect_policy_bundle_dirs()
    assert any("sovereign_ai/policies" in d for d in dirs)


# Suppress unused import in environments that skip async collection.
_ = pytest
