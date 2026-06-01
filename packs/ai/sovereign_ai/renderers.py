"""AI pack renderers — inference endpoint + RAG workspace.

These are the AI pack's `BaseRenderer` implementations. They are *pure*:
`render()` builds a Kubernetes manifest and returns a `RenderedArtifact`
whose `deployment_manifest` carries a single `k8s-apply` step. The
chassis's deployment-executor subsystem (Step 0.2) applies it — the pack
ships no kubectl/apply logic of its own, which is the whole point of the
executor split.

`validate()` re-checks the rendered manifest is well-formed YAML;
`apply()` delegates to `sovereign.executors.apply_manifest`; `teardown()`
emits a delete step. This is the template every infra-backed pack follows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import yaml
from sovereign.executors import apply_manifest
from sovereign.renderers import (
    ApplyResult,
    BaseRenderer,
    DeploymentStep,
    RenderedArtifact,
    TeardownResult,
    ValidationResult,
)

from .models import InferenceEndpointParams, RagWorkspaceParams, is_gpu

if TYPE_CHECKING:
    from sovereign.catalog import ServiceCatalogEntry
    from sovereign.models import ServiceInstance


def _k8s_deployment(params: InferenceEndpointParams, name: str) -> dict[str, Any]:
    """Build a minimal, hardened K8s Deployment for a model server."""
    resources: dict[str, Any] = {
        "requests": {"cpu": "1", "memory": "4Gi"},
        "limits": {"cpu": "4", "memory": "16Gi"},
    }
    if is_gpu(params.accelerator):
        resources["limits"]["nvidia.com/gpu"] = "1"
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": params.namespace,
            "labels": {
                "app": name,
                "sovereign.pack": "ai",
                "sovereign.classification": params.classification,
            },
        },
        "spec": {
            "replicas": params.replicas,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "model-server",
                            "image": f"sovereign/{params.engine}:latest",
                            "args": [
                                f"--model={params.model_id}",
                                f"--max-model-len={params.max_context_tokens}",
                            ],
                            "ports": [{"containerPort": 8000}],
                            "resources": resources,
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                },
            },
        },
    }


class InferenceEndpointRenderer(BaseRenderer):
    """Renders a model-serving endpoint to a K8s Deployment manifest."""

    service_type: ClassVar[str] = "inference-endpoint"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Inference endpoint",
            description="Managed, hardened model-serving endpoint (vLLM/TGI) on a "
            "GovCloud GPU pool, with PII-redaction and residency obligations.",
            bindable=True,
            tags=["ai", "inference", "gpu"],
            pack="ai",
            plans=[
                ServicePlan(id="cpu-small", name="cpu-small", description="CPU-only, dev/test."),
                ServicePlan(id="a10", name="a10", description="Single A10 GPU."),
                ServicePlan(id="a100", name="a100", description="Single A100 GPU."),
                ServicePlan(id="h100", name="h100", description="Single H100 GPU."),
            ],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "required": ["model_id"],
                    "properties": {
                        "model_id": {"type": "string"},
                        "engine": {"type": "string", "enum": ["vllm", "tgi"], "default": "vllm"},
                        "accelerator": {
                            "type": "string",
                            "enum": ["cpu", "a10", "a100", "h100"],
                            "default": "a10",
                        },
                        "replicas": {"type": "integer", "minimum": 1, "maximum": 64, "default": 1},
                        "max_context_tokens": {"type": "integer", "default": 8192},
                        "classification": {
                            "type": "string",
                            "enum": ["U", "CUI", "SECRET"],
                            "default": "U",
                        },
                        "data_residency": {"type": "string", "default": "us-gov-west-1"},
                        "pii_redaction": {"type": "boolean", "default": True},
                        "tls": {"type": "boolean", "default": True},
                        "logging_enabled": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["SC-8", "SC-28", "SI-12", "AC-4"], "ui_section": "AI"},
        )

    def _params(self, instance: ServiceInstance) -> InferenceEndpointParams:
        raw = instance.parameters.model_dump(mode="json")
        # The chassis ServiceInstance carries LB params by default; the AI
        # pack reads its own fields from the free-form tags dict the broker
        # passes through (and falls back to defaults).
        extra = raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}
        merged = {"model_id": extra.get("model_id", instance.instance_id), **extra}
        return InferenceEndpointParams.model_validate(merged)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        manifest = _k8s_deployment(params, name)
        manifest_yaml = yaml.safe_dump(manifest, sort_keys=False).encode()
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"deployment.yaml": manifest_yaml},
            metadata={
                "model_id": params.model_id,
                "accelerator": params.accelerator,
                "replicas": params.replicas,
                "classification": params.classification,
                "gpu": is_gpu(params.accelerator),
            },
            deployment_manifest=[
                DeploymentStep(
                    kind="k8s-apply",
                    target=params.namespace,
                    payload={"manifest_path": f"/artifacts/{name}/deployment.yaml"},
                )
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("deployment.yaml")
        if body is None:
            return ValidationResult(ok=False, errors=["missing deployment.yaml"])
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        if doc.get("kind") != "Deployment":
            return ValidationResult(ok=False, errors=["artifact is not a Deployment"])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        # Delegate entirely to the chassis executor subsystem.
        return await apply_manifest(artifact.deployment_manifest)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        # A real teardown emits a k8s delete; we return the intent so the
        # broker's deprovision path can run it through the executor.
        return TeardownResult(ok=True, removed=[f"deployment/{instance.instance_id}"])


class RagWorkspaceRenderer(BaseRenderer):
    """Renders a RAG workspace (vector store + ingestion) to a manifest."""

    service_type: ClassVar[str] = "rag-workspace"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="RAG workspace",
            description="Retrieval-augmented-generation workspace: managed vector "
            "store plus connector-fed ingestion, encrypted at rest.",
            bindable=True,
            tags=["ai", "rag", "vector-db"],
            pack="ai",
            plans=[ServicePlan(id="standard", name="standard", description="pgvector-backed.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "embedding_model": {"type": "string", "default": "text-embedding-3-large"},
                        "vector_store": {
                            "type": "string",
                            "enum": ["pgvector", "qdrant", "milvus"],
                            "default": "pgvector",
                        },
                        "classification": {
                            "type": "string",
                            "enum": ["U", "CUI", "SECRET"],
                            "default": "CUI",
                        },
                        "encryption_at_rest": {"type": "boolean", "default": True},
                        "pii_redaction": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["SC-28", "SI-12", "AC-4"], "ui_section": "AI"},
        )

    def _params(self, instance: ServiceInstance) -> RagWorkspaceParams:
        raw = instance.parameters.model_dump(mode="json")
        extra = raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}
        merged = {"name": extra.get("name", instance.instance_id), **extra}
        return RagWorkspaceParams.model_validate(merged)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": f"{name}-rag", "namespace": params.namespace},
            "data": {
                "vector_store": params.vector_store,
                "embedding_model": params.embedding_model,
                "encryption_at_rest": str(params.encryption_at_rest).lower(),
            },
        }
        return RenderedArtifact(
            instance_id=instance.instance_id,
            service_type=self.service_type,
            version=instance.version,
            config_files={"rag.yaml": yaml.safe_dump(manifest, sort_keys=False).encode()},
            metadata={
                "vector_store": params.vector_store,
                "classification": params.classification,
            },
            deployment_manifest=[
                DeploymentStep(
                    kind="k8s-apply",
                    target=params.namespace,
                    payload={"manifest_path": f"/artifacts/{name}/rag.yaml"},
                )
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("rag.yaml")
        if body is None:
            return ValidationResult(ok=False, errors=["missing rag.yaml"])
        try:
            yaml.safe_load(body)
        except yaml.YAMLError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return await apply_manifest(artifact.deployment_manifest)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"configmap/{instance.instance_id}-rag"])
