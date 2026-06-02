"""Blockchain pack renderer — permissioned ledger.

Pure renderer emitting a K8s manifest + a `k8s-apply` step; apply()
delegates to the chassis executor. The pack's value is its node-identity
/ key-custody policy bundle.
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

from .models import PermissionedLedgerParams

if TYPE_CHECKING:
    from sovereign.catalog import ServiceCatalogEntry
    from sovereign.models import ServiceInstance


def _tags(instance: ServiceInstance) -> dict[str, Any]:
    raw = instance.parameters.model_dump(mode="json")
    return raw.get("tags", {}) if isinstance(raw.get("tags"), dict) else {}


class PermissionedLedgerRenderer(BaseRenderer):
    service_type: ClassVar[str] = "permissioned-ledger"

    @classmethod
    def catalog_entry(cls) -> ServiceCatalogEntry:
        from sovereign.catalog import ParameterSchema, ServiceCatalogEntry, ServicePlan

        return ServiceCatalogEntry(
            service_type=cls.service_type,
            name="Permissioned ledger",
            description="Permissioned distributed ledger (Hyperledger Fabric/Besu) "
            "with closed membership, validator identity, and HSM key custody.",
            bindable=True,
            tags=["blockchain", "ledger", "fabric"],
            pack="blockchain",
            plans=[
                ServicePlan(id="fabric", name="fabric", description="Hyperledger Fabric, raft."),
                ServicePlan(id="besu", name="besu", description="Hyperledger Besu, IBFT2/QBFT."),
            ],
            parameter_schema=ParameterSchema(
                schema={
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string", "enum": ["fabric", "besu"], "default": "fabric"},
                        "consensus": {"type": "string", "enum": ["raft", "ibft2", "qbft"], "default": "raft"},
                        "classification": {"type": "string", "enum": ["U", "CUI", "SECRET"], "default": "CUI"},
                        "validator_count": {"type": "integer", "minimum": 1, "maximum": 100, "default": 4},
                        "permissioned": {"type": "boolean", "default": True},
                        "validator_identity_required": {"type": "boolean", "default": True},
                        "hsm_key_custody": {"type": "boolean", "default": True},
                        "fips_crypto": {"type": "boolean", "default": True},
                    },
                }
            ),
            metadata={"controls": ["AC-3", "IA-3", "SC-12", "SC-13"], "ui_section": "Blockchain"},
        )

    def _params(self, instance: ServiceInstance) -> PermissionedLedgerParams:
        extra = dict(_tags(instance))
        if "validator_count" in extra:
            extra["validator_count"] = int(extra["validator_count"])
        for boolf in ("permissioned", "validator_identity_required", "hsm_key_custody", "fips_crypto"):
            if boolf in extra:
                extra[boolf] = str(extra[boolf]).lower() in {"1", "true", "yes"}
        return PermissionedLedgerParams.model_validate(extra)

    async def render(self, instance: ServiceInstance) -> RenderedArtifact:
        params = self._params(instance)
        name = instance.instance_id
        manifest = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {
                "name": name,
                "namespace": params.namespace,
                "labels": {"app": name, "sovereign.pack": "blockchain", "sovereign.classification": params.classification},
                "annotations": {
                    "sovereign.ac3/permissioned": str(params.permissioned).lower(),
                    "sovereign.sc12/hsm-custody": str(params.hsm_key_custody).lower(),
                    "sovereign.ledger/consensus": params.consensus,
                },
            },
            "spec": {
                "serviceName": name,
                "replicas": params.validator_count,
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": {"app": name}},
                    "spec": {
                        "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [
                            {
                                "name": "ledger-node",
                                "image": f"sovereign/{params.platform}:latest",
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
            config_files={"ledger.yaml": yaml.safe_dump(manifest, sort_keys=False).encode()},
            metadata={
                "platform": params.platform,
                "consensus": params.consensus,
                "validator_count": params.validator_count,
                "classification": params.classification,
            },
            deployment_manifest=[
                DeploymentStep(kind="k8s-apply", target=params.namespace, payload={"manifest_path": f"/artifacts/{name}/ledger.yaml"})
            ],
        )

    async def validate(self, artifact: RenderedArtifact) -> ValidationResult:
        body = artifact.config_files.get("ledger.yaml")
        if body is None:
            return ValidationResult(ok=False, errors=["missing ledger.yaml"])
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
