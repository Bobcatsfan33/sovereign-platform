"""Edge pack renderers — edge node + edge cluster.

Pure renderers emitting K8s manifests + a `k8s-apply` step (edge K8s).
apply() delegates to the chassis executor. The pack's value is its
supply-chain / boot-integrity policy bundle.
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

from .models import EdgeClusterParams, EdgeNodeParams

if TYPE_CHECKING:
    from sovereign.catalog import ServiceCatalogEntry
    from sovereign.models import ServiceInstance


def _tags(instance: ServiceInstance) -> dict[str, Any]:
    raw = instance.parameters.model_dump(mode="json")
    return raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}


def _coerce_bool(d: dict[str, Any], *keys: str) -> None:
    for k in keys:
        if k in d:
            d[k] = str(d[k]).lower() in {"1", "true", "yes"}


class EdgeNodeRenderer(BaseRenderer):
    service_type: ClassVar[str] = "edge-node"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Edge node",
            description="Hardened single edge node (FIPS image, attestation, disk "
            "encryption) for forward/disconnected sites.",
            bindable=True,
            tags=["edge", "node", "fips"],
            pack="edge",
            plans=[ServicePlan(id="standard", name="standard", description="One node.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "fips_image": {"type": "boolean", "default": True},
                        "attestation_required": {"type": "boolean", "default": True},
                        "disk_encryption": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["SI-7", "SI-7(9)", "SC-28", "SR-11"], "ui_section": "Edge"},
        )

    def _params(self, instance: ServiceInstance) -> EdgeNodeParams:
        extra = dict(_tags(instance))
        _coerce_bool(extra, "fips_image", "attestation_required", "disk_encryption")
        return EdgeNodeParams.model_validate(extra)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": name,
                "namespace": params.namespace,
                "labels": {"app": name, "sovereign.pack": "edge", "sovereign.classification": params.classification},
                "annotations": {
                    "sovereign.si7/fips-image": str(params.fips_image).lower(),
                    "sovereign.si7-9/attestation": str(params.attestation_required).lower(),
                },
            },
            "spec": {
                "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [
                    {
                        "name": "edge-agent",
                        "image": "sovereign/edge-agent:fips",
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]},
                        },
                    }
                ],
            },
        }
        return RenderedArtifact(
            instance_id=name,
            service_type=self.service_type,
            version=instance.version,
            config_files={"node.yaml": yaml.safe_dump(manifest, sort_keys=False).encode()},
            metadata={"fips_image": params.fips_image, "classification": params.classification},
            deployment_manifest=[
                DeploymentStep(kind="k8s-apply", target=params.namespace, payload={"manifest_path": f"/artifacts/{name}/node.yaml"})
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("node.yaml")
        if body is None:
            return ValidationResult(ok=False, errors=["missing node.yaml"])
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        if doc.get("kind") != "Pod":
            return ValidationResult(ok=False, errors=["artifact is not a Pod"])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return await apply_manifest(artifact.deployment_manifest)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"pod/{instance.instance_id}"])


class EdgeClusterRenderer(BaseRenderer):
    service_type: ClassVar[str] = "edge-cluster"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Edge cluster",
            description="Small hardened edge cluster (K3s-style) with FIPS images, "
            "attestation, and offline store-and-forward.",
            bindable=True,
            tags=["edge", "cluster", "fips"],
            pack="edge",
            plans=[ServicePlan(id="standard", name="standard", description="3-node cluster.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "node_count": {"type": "integer", "minimum": 1, "maximum": 50, "default": 3},
                        "fips_image": {"type": "boolean", "default": True},
                        "attestation_required": {"type": "boolean", "default": True},
                        "offline_mode": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["SI-7", "SI-7(9)", "AC-4", "SR-11"], "ui_section": "Edge"},
        )

    def _params(self, instance: ServiceInstance) -> EdgeClusterParams:
        extra = dict(_tags(instance))
        if "node_count" in extra:
            extra["node_count"] = int(extra["node_count"])
        _coerce_bool(extra, "fips_image", "attestation_required", "offline_mode")
        return EdgeClusterParams.model_validate(extra)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "DaemonSet",
            "metadata": {
                "name": name,
                "namespace": params.namespace,
                "labels": {"app": name, "sovereign.pack": "edge", "sovereign.classification": params.classification},
                "annotations": {
                    "sovereign.si7/fips-image": str(params.fips_image).lower(),
                    "sovereign.edge/offline-mode": str(params.offline_mode).lower(),
                    "sovereign.edge/node-count": str(params.node_count),
                },
            },
            "spec": {
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": {"app": name}},
                    "spec": {
                        "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [
                            {
                                "name": "edge-agent",
                                "image": "sovereign/edge-agent:fips",
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
        return RenderedArtifact(
            instance_id=name,
            service_type=self.service_type,
            version=instance.version,
            config_files={"cluster.yaml": yaml.safe_dump(manifest, sort_keys=False).encode()},
            metadata={"node_count": params.node_count, "offline_mode": params.offline_mode},
            deployment_manifest=[
                DeploymentStep(kind="k8s-apply", target=params.namespace, payload={"manifest_path": f"/artifacts/{name}/cluster.yaml"})
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("cluster.yaml")
        if body is None:
            return ValidationResult(ok=False, errors=["missing cluster.yaml"])
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        if doc.get("kind") != "DaemonSet":
            return ValidationResult(ok=False, errors=["artifact is not a DaemonSet"])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return await apply_manifest(artifact.deployment_manifest)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"daemonset/{instance.instance_id}"])
