"""SecOps pack renderers — SIEM workspace + log pipeline.

Pure renderers (K8s manifests + `k8s-apply` step, apply() delegates to
the chassis executor). Reuses the same executor the AI pack established;
the SecOps value is in its policy bundle (AU-family controls), not a new
backend.
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

from .models import LogPipelineParams, SiemWorkspaceParams

if TYPE_CHECKING:
    from sovereign.catalog import ServiceCatalogEntry
    from sovereign.models import ServiceInstance


def _siem_statefulset(params: SiemWorkspaceParams, name: str) -> dict[str, Any]:
    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": name,
            "namespace": params.namespace,
            "labels": {
                "app": name,
                "sovereign.pack": "secops",
                "sovereign.classification": params.classification,
            },
            "annotations": {
                "sovereign.au11/retention-days": str(params.retention_days),
                "sovereign.au9/immutable": str(params.immutable_storage).lower(),
            },
        },
        "spec": {
            "serviceName": name,
            "replicas": params.hot_nodes,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                    "containers": [
                        {
                            "name": "siem",
                            "image": f"sovereign/{params.backend}:latest",
                            "ports": [{"containerPort": 9200}],
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


def _tags(instance: ServiceInstance) -> dict[str, Any]:
    raw = instance.parameters.model_dump(mode="json")
    return raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}


class SiemWorkspaceRenderer(BaseRenderer):
    service_type: ClassVar[str] = "siem-workspace"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="SIEM workspace",
            description="Managed security-information-and-event-management workspace "
            "with immutable, retention-enforced audit storage.",
            bindable=True,
            tags=["secops", "siem", "audit"],
            pack="secops",
            plans=[
                ServicePlan(id="standard", name="standard", description="3 hot nodes."),
                ServicePlan(id="ha", name="ha", description="Multi-node HA."),
            ],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "backend": {"type": "string", "enum": ["elastic", "opensearch", "splunk"], "default": "opensearch"},
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "retention_days": {"type": "integer", "minimum": 1, "default": 90},
                        "immutable_storage": {"type": "boolean", "default": True},
                        "encryption_at_rest": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["AU-9", "AU-11", "SC-28", "SI-4"], "ui_section": "SecOps"},
        )

    def _params(self, instance: ServiceInstance) -> SiemWorkspaceParams:
        extra = dict(_tags(instance))
        if "retention_days" in extra:
            extra["retention_days"] = int(extra["retention_days"])
        if "hot_nodes" in extra:
            extra["hot_nodes"] = int(extra["hot_nodes"])
        for boolf in ("immutable_storage", "encryption_at_rest"):
            if boolf in extra:
                extra[boolf] = str(extra[boolf]).lower() in {"1", "true", "yes"}
        return SiemWorkspaceParams.model_validate(extra)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        manifest = _siem_statefulset(params, name)
        return RenderedArtifact(
            instance_id=name,
            service_type=self.service_type,
            version=instance.version,
            config_files={"siem.yaml": yaml.safe_dump(manifest, sort_keys=False).encode()},
            metadata={
                "backend": params.backend,
                "retention_days": params.retention_days,
                "immutable": params.immutable_storage,
                "classification": params.classification,
            },
            deployment_manifest=[
                DeploymentStep(
                    kind="k8s-apply",
                    target=params.namespace,
                    payload={"manifest_path": f"/artifacts/{name}/siem.yaml"},
                )
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("siem.yaml")
        if body is None:
            return ValidationResult(ok=False, errors=["missing siem.yaml"])
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        if doc.get("kind") != "StatefulSet":
            return ValidationResult(ok=False, errors=["artifact is not a StatefulSet"])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return await apply_manifest(artifact.deployment_manifest)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"statefulset/{instance.instance_id}"])


class LogPipelineRenderer(BaseRenderer):
    service_type: ClassVar[str] = "log-pipeline"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Log pipeline",
            description="Collection pipeline that forwards signed log records "
            "from chassis connectors into a SIEM workspace.",
            bindable=True,
            tags=["secops", "logging", "audit"],
            pack="secops",
            plans=[ServicePlan(id="standard", name="standard", description="Single pipeline.")],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "sources": {"type": "array", "items": {"type": "string"}},
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "sign_records": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["AU-2", "AU-10", "SI-4"], "ui_section": "SecOps"},
        )

    def _params(self, instance: ServiceInstance) -> LogPipelineParams:
        extra = dict(_tags(instance))
        merged: dict[str, Any] = {"name": extra.get("name", instance.instance_id), **extra}
        if "sign_records" in merged:
            merged["sign_records"] = str(merged["sign_records"]).lower() in {"1", "true", "yes"}
        # The chassis carries free-form params as the LbParameters.tags
        # string dict, so list-typed fields arrive comma-separated (or
        # already a list when constructed directly). Normalise both.
        for listf in ("sources", "sinks"):
            val = merged.get(listf)
            if isinstance(val, str):
                merged[listf] = [v.strip() for v in val.split(",") if v.strip()]
        return LogPipelineParams.model_validate(merged)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": f"{name}-pipeline", "namespace": params.namespace},
            "data": {
                "sources": ",".join(params.sources),
                "sinks": ",".join(params.sinks),
                "sign_records": str(params.sign_records).lower(),
            },
        }
        return RenderedArtifact(
            instance_id=name,
            service_type=self.service_type,
            version=instance.version,
            config_files={"pipeline.yaml": yaml.safe_dump(manifest, sort_keys=False).encode()},
            metadata={"sources": params.sources, "classification": params.classification},
            deployment_manifest=[
                DeploymentStep(
                    kind="k8s-apply",
                    target=params.namespace,
                    payload={"manifest_path": f"/artifacts/{name}/pipeline.yaml"},
                )
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("pipeline.yaml")
        if body is None:
            return ValidationResult(ok=False, errors=["missing pipeline.yaml"])
        try:
            yaml.safe_load(body)
        except yaml.YAMLError as exc:
            return ValidationResult(ok=False, errors=[str(exc)])
        return ValidationResult(ok=True)

    async def apply(self, artifact: RenderedArtifact) -> ApplyResult:
        return await apply_manifest(artifact.deployment_manifest)

    async def teardown(self, instance: ServiceInstance) -> TeardownResult:
        return TeardownResult(ok=True, removed=[f"configmap/{instance.instance_id}-pipeline"])
